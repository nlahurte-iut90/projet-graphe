"""Scorer unifié basé sur l'analyse de corrélation temporelle."""

import math
import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict

import networkx as nx

from src.services.scoring.base import SimilarityStrategy, NodeScore


@dataclass
class TemporalScorerConfig:
    """Configuration pour TemporalScorer.

    Paramètres calibrés selon la spécification formelle :
    - lambda_rec: demi-vie ~15 jours (4500 blocs) -> ln(2)/4500 ≈ 0.000154
    - lambda_chain: atténuation temporelle par saut
    - theta: facteur d'amortissement Katz (0.4)
    - rho: sévérité conservation volume (1.5)
    - delta_t_blocks: fenêtre de synchronie temporelle (±100 blocs)
    - tau: constante de saturation fréquentielle (20.0)
    """
    lambda_rec: float = 0.000154      # Décroissance récence (demi-vie 15j)
    lambda_chain: float = 0.0001      # Décroissance temporelle chaîne
    theta: float = 0.4                # Atténuation profondeur Katz
    rho: float = 1.5                  # Sévérité conservation volume
    delta_t_blocks: int = 100         # Fenêtre synchronie (±100 blocs)
    max_degree_explore: int = 100     # Early stopping hubs
    k_max: int = 2                    # Profondeur max recherche (réduit pour graphes peu profonds)
    v_percentile_ref: float = 90.0    # Percentile pour normalisation volume (réduit pour plus de sensibilité)
    tau: float = 15.0                 # Constante saturation (augmenté pour moins de saturation rapide)
    # Paramètres de normalisation du volume (P1-003)
    volume_normalization_mode: str = "relative"  # "absolute" ou "relative"
    absolute_v_ref: float = 100.0     # Référence fixe pour mode absolu (100 ETH)
    max_paths: int = 500              # Limite de chemins pour indirect
    epsilon: float = 1e-9             # Précision numérique
    # Paramètres sigmoïde ajustés : S_indirect=0 doit donner ~0, pas ~0.27
    kappa_sigmoid: float = 6.0        # Paramètre sigmoïde (plus raide)
    tau_median_ref: float = 0.15      # Médiane de référence pour sigmoïde (plus basse = score plus faible quand pas de chemins)


class TemporalScorer(SimilarityStrategy):
    """
    Scorer unifié basé sur l'analyse de corrélation temporelle.

    Algorithme :
    1. Score Direct (SD) = 0.50×S_intensite + 0.25×S_recence + 0.15×S_sync + 0.10×S_equilibre
    2. Score Indirect (SI) = Katz temporel avec conservation progressive
    3. Score Total = w_dir×SD + w_ind×SI + 0.05×SD×SI + bonus_communaute

    Les poids w_dir/w_ind sont dynamiques selon le nombre de transactions directes.
    """

    # Ethereum constants
    ETH_BLOCK_TIME = 12               # Secondes par bloc
    ETH_GENESIS_TIMESTAMP = 1438269970  # Timestamp bloc 0

    # Poids pour le score direct (rééquilibrés selon P1-001)
    # Anciens: I=0.50, R=0.25, S=0.15, Eq=0.10
    # Nouveaux: I=0.40, R=0.20, S=0.15, Eq=0.25 (plus de poids à l'équilibre)
    W_INTENSITE = 0.40
    W_RECENCE = 0.20
    W_SYNC = 0.15
    W_EQUILIBRE = 0.25

    def __init__(self, graph: nx.MultiDiGraph, config: Optional[TemporalScorerConfig] = None):
        super().__init__(graph)
        self.config = config or TemporalScorerConfig()
        # Cache pour les stats de référence par adresse principale
        self._ref_stats_cache: Dict[str, Dict] = {}
        # Cache pour les blocs courants estimés
        self._current_block: Optional[int] = None
        # Snapshot du graphe pour détecter les changements
        self._graph_snapshot = self._compute_graph_hash()

    def _compute_graph_hash(self) -> str:
        """Calcule un hash simple du graphe pour détecter les changements."""
        edges_str = str(sorted(self.graph.edges(data=True), key=lambda x: (x[0], x[1])))
        return str(hash(edges_str))

    def _is_cache_valid(self) -> bool:
        """Vérifie si le cache correspond au graphe actuel."""
        current_hash = self._compute_graph_hash()
        return current_hash == self._graph_snapshot

    def get_name(self) -> str:
        """Retourne le nom de la stratégie."""
        return "TemporalScorer"

    def get_description(self) -> str:
        """Retourne une description de la stratégie."""
        return (
            "Scorer unifié basé sur l'analyse temporelle: "
            "intensité (40%), équilibre (25%), récence (20%), synchronie (15%). "
            "Score indirect via Katz temporel avec conservation de volume."
        )

    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule le score de similarité entre main_address et node.

        Args:
            main_address: Adresse principale de référence
            node: Nœud cible à évaluer

        Returns:
            NodeScore avec les dimensions temporelles
        """
        # Invalider le cache si le graphe a changé
        if not self._is_cache_valid():
            self._ref_stats_cache.clear()
            self._current_block = None
            self._graph_snapshot = self._compute_graph_hash()

        # Normaliser les adresses (Ethereum addresses are case-insensitive)
        main_address = main_address.lower()
        node = node.lower()

        # Cas trivial: adresse principale elle-même
        if main_address == node:
            return NodeScore(
                total=100.0,
                direct=1.0,
                indirect=0.0,
                intensite=1.0,
                recence=1.0,
                synchronie=1.0,
                equilibre=1.0,
                interaction=0.0,
                confidence="high",
                metrics={"self": True}
            )

        # Créer un mapping des adresses en minuscules vers les adresses originales
        node_map = {n.lower(): n for n in self.graph.nodes()}

        # Vérifier que les nœuds existent dans le graphe
        if main_address not in node_map or node not in node_map:
            return NodeScore(
                total=0.0,
                direct=0.0,
                indirect=0.0,
                confidence="low",
                metrics={"error": "nodes not in graph"}
            )

        main_orig = node_map[main_address]
        node_orig = node_map[node]

        # Calcul du score direct
        direct_components = self._compute_direct_score(main_orig, node_orig)

        # Calcul du score indirect (Katz temporel)
        indirect_score = self._compute_indirect_score(main_orig, node_orig)

        # Combinaison en score total
        total_score = self._compute_total_score(
            direct_components,
            indirect_score,
            direct_components.get('tx_count', 0)
        )

        # Détermination de la confiance
        confidence = self._determine_confidence(
            direct_components.get('tx_count', 0),
            direct_components.get('v_total', 0)
        )

        # Classification du score direct
        classification = self._classify_score(direct_components['s_direct'])

        # Compatibilité avec le format attendu par table_formatter
        # score_breakdown utilise les noms legacy (activity, proximity, recency)
        score_breakdown = {
            'activity': round(direct_components['s_intensite'] * 100, 2),  # Intensité -> Activity
            'proximity': round(direct_components['s_sync'] * 100, 2),      # Synchronie -> Proximity
            'recency': round(direct_components['s_recence'] * 100, 2),     # Récence -> Recency
            # Dimensions spécifiques au TemporalScorer
            'intensite': round(direct_components['s_intensite'], 4),
            'synchronie': round(direct_components['s_sync'], 4),
            'equilibre': round(direct_components['s_equilibre'], 4),
            'interaction': round(0.05 * direct_components['s_direct'] * indirect_score, 4),
        }

        return NodeScore(
            total=round(total_score, 2),
            direct=round(direct_components['s_direct'], 4),
            indirect=round(indirect_score, 4),
            intensite=round(direct_components['s_intensite'], 4),
            recence=round(direct_components['s_recence'], 4),
            synchronie=round(direct_components['s_sync'], 4),
            equilibre=round(direct_components['s_equilibre'], 4),
            interaction=round(0.05 * direct_components['s_direct'] * indirect_score, 4),
            confidence=confidence,
            metrics={
                # Clés pour table_formatter (compatibilité)
                'tx_count': direct_components.get('tx_count', 0),
                'total_volume': direct_components.get('v_total', 0),
                # Clés internes détaillées
                'v_out': direct_components.get('v_out', 0),
                'v_in': direct_components.get('v_in', 0),
                'v_total': direct_components.get('v_total', 0),
                'n_out': direct_components.get('n_out', 0),
                'n_in': direct_components.get('n_in', 0),
                'n_total': direct_components.get('tx_count', 0),
                'v_ref': direct_components.get('v_ref', 0),
                'w_direct': direct_components.get('w_direct', 0.7),
                'w_indirect': direct_components.get('w_indirect', 0.25),
                'paths_found': direct_components.get('paths_found', 0),
                'classification': classification,
                'score_breakdown': score_breakdown,
            }
        )

    def _compute_direct_score(self, main_address: str, node: str) -> Dict[str, float]:
        """
        Calcule les 4 composantes du score direct.

        Returns:
            Dict avec s_intensite, s_recence, s_sync, s_equilibre, s_direct
        """
        # Extraction des transactions
        tx_out = self._get_tx_out(main_address, node)
        tx_in = self._get_tx_in(main_address, node)

        # Agrégation des volumes et comptages
        v_out = sum(tx.get("weight", 0) for tx in tx_out)
        v_in = sum(tx.get("weight", 0) for tx in tx_in)
        v_total = v_out + v_in
        n_out = len(tx_out)
        n_in = len(tx_in)
        n_total = n_out + n_in

        # Valeur de référence pour normalisation (percentile 95 du volume principal)
        v_ref = self._get_reference_volume(main_address)

        # Calcul des sous-scores
        s_intensite = self._calc_intensite(v_total, n_total, v_ref)
        s_recence = self._calc_recence(tx_out + tx_in)
        s_sync = self._calc_synchronie(tx_out, tx_in)
        s_equilibre = self._calc_equilibre(v_out, v_in, v_total) if n_out > 0 and n_in > 0 else 0.0

        # Score direct combiné
        s_direct = (
            self.W_INTENSITE * s_intensite +
            self.W_RECENCE * s_recence +
            self.W_SYNC * s_sync +
            self.W_EQUILIBRE * s_equilibre
        )

        return {
            's_intensite': s_intensite,
            's_recence': s_recence,
            's_sync': s_sync,
            's_equilibre': s_equilibre,
            's_direct': s_direct,
            'v_out': v_out,
            'v_in': v_in,
            'v_total': v_total,
            'n_out': n_out,
            'n_in': n_in,
            'tx_count': n_total,
            'v_ref': v_ref,
        }

    def _calc_intensite(self, v_total: float, n_total: int, v_ref: float) -> float:
        """
        Calcule le score d'intensité.

        S_intensite = min(ln(1 + V_total) / ln(1 + V_ref), 1.0) × (1 - exp(-N_total/τ))

        Pour les micro-volumes, on utilise une échelle améliorée qui préserve
        la sensibilité aux petits montants.
        """
        if v_total <= 0 or v_ref <= 0:
            return 0.0

        # Volume factor - échelle adaptative selon le volume de référence
        if v_total < 0.00001:  # Moins de 0.00001 ETH (10e-5)
            # Micro-volumes: échelle linéaire très sensible
            volume_factor = min(v_total / max(v_ref, 0.00001), 1.0)
        elif v_ref < 0.01:
            # Petits volumes: échelle linéaire
            volume_factor = min(v_total / max(v_ref, 0.00001), 1.0)
        elif v_ref < 1.0:
            # Volumes moyens: échelle semi-linéaire
            volume_factor = min(v_total / v_ref, 1.0)
        else:
            # Gros volumes: échelle logarithmique
            volume_factor = min(
                math.log(1 + v_total) / math.log(1 + v_ref),
                1.0
            )

        # Facteur de fréquence (saturation progressive)
        freq_factor = 1.0 - math.exp(-n_total / self.config.tau)

        return volume_factor * freq_factor

    def _calc_recence(self, transactions: List[Dict[str, Any]]) -> float:
        """
        Calcule le score de récence.

        Pour chaque tx: weight_tx = value × exp(-λ_rec × (current_block - block_number))
        S_recence = sum(weights) / sum(values)
        """
        if not transactions:
            return 0.0

        current_block = self._get_current_block()
        weights = []
        values = []

        for tx in transactions:
            value = tx.get("weight", 0)
            if value <= 0:
                continue

            timestamp = tx.get("time")
            block = self._approximate_block_number(timestamp)

            if block is not None:
                # Poids exponentiellement décroissant avec l'âge
                age_blocks = max(0, current_block - block)
                weight = value * math.exp(-self.config.lambda_rec * age_blocks)
            else:
                # Sans timestamp, on donne un poids moyen
                weight = value * 0.5

            weights.append(weight)
            values.append(value)

        if not values:
            return 0.0

        return sum(weights) / sum(values)

    def _calc_synchronie(self, tx_out: List[Dict], tx_in: List[Dict]) -> float:
        """
        Calcule le score de synchronie temporelle avec fenêtre dynamique (P1-004).

        La fenêtre de synchronie varie selon le volume moyen:
        - Gros volumes (> 100 ETH): fenêtre large ~1h40 (500 blocs) pour déplacements de fonds
        - Volumes moyens (> 10 ETH): fenêtre moyenne ~40 min (200 blocs)
        - Petits volumes: fenêtre standard ~20 min (100 blocs) pour arbitrages

        Le score est pondéré par le volume et dégressif avec la distance temporelle.
        """
        if not tx_out or not tx_in:
            return 0.0

        # Convertir en blocs avec poids (volumes)
        out_txs = []  # List of (block, weight)
        for tx in tx_out:
            block = self._approximate_block_number(tx.get("time"))
            if block is not None:
                out_txs.append((block, tx.get("weight", 0)))

        in_txs = []  # List of (block, weight)
        for tx in tx_in:
            block = self._approximate_block_number(tx.get("time"))
            if block is not None:
                in_txs.append((block, tx.get("weight", 0)))

        if not out_txs or not in_txs:
            return 0.0

        # Calculer le volume moyen pour déterminer la fenêtre dynamique
        all_volumes = [w for _, w in out_txs + in_txs]
        avg_volume = sum(all_volumes) / len(all_volumes) if all_volumes else 0

        # Fenêtre dynamique basée sur le volume (P1-004)
        if avg_volume > 100:  # > 100 ETH
            delta = 500  # ~1h40 (déplacement de fonds)
        elif avg_volume > 10:  # > 10 ETH
            delta = 200  # ~40 min
        else:
            delta = self.config.delta_t_blocks  # ~20 min (arbitrage rapide)

        # Trier les transactions entrantes par bloc pour recherche efficace
        in_txs_sorted = sorted(in_txs, key=lambda x: x[0])
        in_blocks = [b for b, _ in in_txs_sorted]
        import bisect

        # Calcul du score de synchronie pondéré
        sync_score = 0.0
        total_weight = 0.0

        for out_block, out_weight in out_txs:
            best_match = 0.0

            # Recherche dichotomique de la position
            idx = bisect.bisect_left(in_blocks, out_block)

            # Vérifier les voisins proches
            for offset in [0, -1, 1]:
                check_idx = idx + offset
                if 0 <= check_idx < len(in_blocks):
                    in_block = in_blocks[check_idx]
                    gap = abs(in_block - out_block)

                    if gap <= delta:
                        # Score dégressif avec la distance temporelle
                        # Pondéré par le minimum des volumes (synchronie significative)
                        in_weight = in_txs_sorted[check_idx][1]
                        time_factor = 1 - gap / delta
                        volume_factor = min(out_weight, in_weight)
                        match_score = time_factor * volume_factor
                        best_match = max(best_match, match_score)

            sync_score += best_match
            total_weight += out_weight

        return sync_score / total_weight if total_weight > 0 else 0.0

    def _calc_equilibre(self, v_out: float, v_in: float, v_total: float) -> float:
        """
        Calcule le score d'équilibre (bonus uniquement).

        Si bidirectionnel: S_equilibre = 0.5 × min(V_out, V_in) / V_total
        """
        if v_total <= 0:
            return 0.0

        return 0.5 * min(v_out, v_in) / v_total

    def _compute_indirect_score(self, main_address: str, target: str) -> float:
        """
        Implémente l'algorithme de Katz temporel avec beam search.

        Args:
            main_address: Adresse principale (déjà normalisée, origine du graphe)
            target: Adresse cible (déjà normalisée, origine du graphe)

        Returns:
            Score indirect SI [0, 1]
        """
        # Vérifier que les nœuds existent dans le graphe
        if main_address not in self.graph or target not in self.graph:
            return 0.0

        # Vérifier s'il existe un chemin direct
        if self.graph.has_edge(main_address, target) or self.graph.has_edge(target, main_address):
            # S'il y a des transactions directes, le score indirect est moins important
            # mais on le calcule quand même pour détecter les patterns complexes
            pass

        # Priority queue: (-score, depth, node, path_times, first_volume)
        # On utilise une heap pour avoir les meilleurs scores en premier
        heap: List[Tuple[float, int, str, List[int], float]] = []
        heapq.heappush(heap, (-1.0, 0, main_address, [], 0.0))

        total_contribution = 0.0
        visited_paths: Set[Tuple[str, ...]] = set()
        paths_explored = 0

        while heap and paths_explored < self.config.max_paths:
            neg_score, depth, current, path_times, first_volume = heapq.heappop(heap)
            current_score = -neg_score

            if depth >= self.config.k_max:
                continue

            # Récupérer les voisins
            neighbors = list(self.graph.successors(current)) + list(self.graph.predecessors(current))
            neighbors = list(set(neighbors))  # Dédupliquer

            for neighbor in neighbors:
                if neighbor == main_address:  # Éviter les cycles vers le départ
                    continue

                # Vérifier le degré (early stopping pour les hubs)
                degree = self.graph.degree(neighbor)
                if depth == 0 and degree > self.config.max_degree_explore:
                    continue

                # Récupérer les arêtes entre current et neighbor
                edges = self._get_all_edges(current, neighbor)

                for edge in edges:
                    # Vérifier la causalité temporelle
                    timestamp = edge.get("time")
                    block = self._approximate_block_number(timestamp)

                    if block is None:
                        continue

                    # Vérifier que la transaction est après le dernier bloc du chemin
                    if path_times and block <= max(path_times):
                        continue

                    # Calculer le score local de l'arête
                    s_edge = self._compute_local_edge_score(edge)

                    # Calculer la pénalité temporelle
                    if path_times:
                        time_gap = block - max(path_times)
                        time_penalty = math.exp(-self.config.lambda_chain * time_gap)
                    else:
                        time_penalty = 1.0

                    # Calculer la pénalité hub
                    if depth == 0:
                        hub_penalty = 1.0 / math.sqrt(max(degree, 1))
                    else:
                        hub_penalty = 1.0

                    # Nouveau score pour ce chemin
                    new_score = current_score * s_edge * time_penalty * hub_penalty

                    # Déterminer le premier volume pour la conservation
                    if depth == 0:
                        new_first_volume = edge.get("weight", 0)
                    else:
                        new_first_volume = first_volume

                    # Si on atteint la cible via un chemin indirect (depth >= 1)
                    # Les chemins de longueur 1 (directs) ne comptent pas pour le score indirect
                    if neighbor == target and depth >= 1:
                        # Calculer la conservation de volume
                        last_volume = edge.get("weight", 0)
                        if new_first_volume > 0 and last_volume > 0:
                            ratio = min(new_first_volume, last_volume) / max(new_first_volume, last_volume)
                            conservation = ratio ** self.config.rho
                        else:
                            conservation = 0.0

                        # Contribution avec atténuation Katz
                        contribution = (self.config.theta ** depth) * new_score * conservation
                        total_contribution += contribution

                        path_tuple = tuple([main_address] + path_times + [neighbor])
                        visited_paths.add(path_tuple)
                    else:
                        # Continuer l'exploration
                        new_path_times = path_times + [block]
                        heapq.heappush(
                            heap,
                            (-new_score, depth + 1, neighbor, new_path_times, new_first_volume)
                        )

            paths_explored += 1

        # Si aucun chemin trouvé, retourner 0 explicitement
        if total_contribution == 0.0:
            return 0.0

        # Normalisation sigmoïde finale
        # S_indirect^norm = 1 / (1 + exp(-κ * (S_indirect - τ_med)))
        kappa = self.config.kappa_sigmoid
        tau_med = self.config.tau_median_ref

        normalized = 1.0 / (1.0 + math.exp(-kappa * (total_contribution - tau_med)))
        return min(normalized, 1.0)

    def _compute_local_edge_score(self, edge: Dict[str, Any]) -> float:
        """
        Calcule un score local [0, 1] pour une arête.

        Basé sur la valeur de la transaction relative au volume total du graphe.
        """
        weight = edge.get("weight", 0)
        if weight <= 0:
            return 0.0

        # Normalisation logarithmique
        # Supposons qu'une transaction de 100 ETH est "parfaite" (score 1.0)
        ref_value = 100.0
        return min(math.log(1 + weight) / math.log(1 + ref_value), 1.0)

    def _compute_total_score(
        self,
        direct_components: Dict[str, float],
        indirect_score: float,
        n_tx: int
    ) -> float:
        """
        Combine direct et indirect avec pondération dynamique.

        Si N_tx < 3:
            w_dir, w_ind = 0.4, 0.55  # Peu d'historique → plus d'indirect
        Sinon:
            w_dir, w_ind = 0.7, 0.25  # Suffisamment d'historique → privilégier direct

        S_total = w_dir×S_dir + w_ind×S_ind + 0.05×S_dir×S_ind
        """
        s_direct = direct_components['s_direct']

        if n_tx < 3:
            w_dir, w_ind = 0.4, 0.55
        else:
            w_dir, w_ind = 0.7, 0.25

        # Stocker les poids pour les métriques
        direct_components['w_direct'] = w_dir
        direct_components['w_indirect'] = w_ind

        # Formule avec terme d'interaction
        interaction = 0.05 * s_direct * indirect_score
        total = w_dir * s_direct + w_ind * indirect_score + interaction

        return min(total * 100, 100.0)  # Convertir en [0, 100]

    def _determine_confidence(self, tx_count: int, v_total: float) -> str:
        """
        Détermine le niveau de confiance du score.

        high: >= 5 transactions ou >= 10 ETH
        medium: >= 2 transactions ou >= 1 ETH
        low: sinon
        """
        if tx_count >= 5 or v_total >= 10.0:
            return "high"
        elif tx_count >= 2 or v_total >= 1.0:
            return "medium"
        else:
            return "low"

    def _classify_score(self, score: float) -> str:
        """
        Classification du score selon les seuils d'interprétation formels.

        | Score | Classification | Signification |
        |-------|---------------|---------------|
        | 0.90 - 1.00 | entity_unique | Contrôle total, probablement même propriétaire |
        | 0.75 - 0.90 | economic_partner | Relation privilégiée (client/fournisseur régulier) |
        | 0.50 - 0.75 | structural_relation | Contact occasionnel mais via réseau cohérent |
        | 0.30 - 0.50 | occasional_contact | Interaction indirecte via hub ou unique |
        | 0.00 - 0.30 | no_correlation | Bruit ou relation trop faible |
        """
        if score >= 0.90:
            return "entity_unique"
        elif score >= 0.75:
            return "economic_partner"
        elif score >= 0.50:
            return "structural_relation"
        elif score >= 0.30:
            return "occasional_contact"
        else:
            return "no_correlation"

    def get_score_classification(self, main_address: str, node: str) -> Dict[str, Any]:
        """
        Retourne le score complet avec classification et interprétation.

        Returns:
            Dict avec score, classification, et description textuelle
        """
        score_result = self.score(main_address, node)

        classification = self._classify_score(score_result.direct)

        descriptions = {
            "entity_unique": "Contrôle total, probablement même propriétaire",
            "economic_partner": "Relation privilégiée (client/fournisseur régulier)",
            "structural_relation": "Contact occasionnel mais via réseau cohérent",
            "occasional_contact": "Interaction indirecte via hub ou unique",
            "no_correlation": "Bruit ou relation trop faible"
        }

        return {
            "score": score_result,
            "classification": classification,
            "description": descriptions.get(classification, "Inconnu"),
            "interpretation": {
                "direct_score": score_result.direct,
                "indirect_score": score_result.indirect,
                "total_score": score_result.total,
                "confidence": score_result.confidence,
                "intensite": score_result.intensite,
                "recence": score_result.recence,
                "synchronie": score_result.synchronie,
                "equilibre": score_result.equilibre
            }
        }

    def _get_tx_out(self, main_address: str, node: str) -> List[Dict[str, Any]]:
        """Extrait les transactions sortantes (main_address -> node)."""
        edges = []
        edge_data = self.graph.get_edge_data(main_address, node, default={})
        for key, data in edge_data.items():
            edge = dict(data)
            edge["from"] = main_address
            edge["to"] = node
            edges.append(edge)
        return edges

    def _get_tx_in(self, main_address: str, node: str) -> List[Dict[str, Any]]:
        """Extrait les transactions entrantes (node -> main_address)."""
        edges = []
        edge_data = self.graph.get_edge_data(node, main_address, default={})
        for key, data in edge_data.items():
            edge = dict(data)
            edge["from"] = node
            edge["to"] = main_address
            edges.append(edge)
        return edges

    def _get_reference_volume(self, main_address: str) -> float:
        """
        Calcule le volume de référence pour la normalisation du score d'intensité.

        Mode absolu: utilise absolute_v_ref comme référence globale
        Mode relatif: utilise le percentile 95 des volumes de l'adresse principale
        """
        if main_address in self._ref_stats_cache:
            return self._ref_stats_cache[main_address]['v_ref']

        # Mode absolu: référence fixe (P1-003)
        if self.config.volume_normalization_mode == "absolute":
            v_ref = self.config.absolute_v_ref
            self._ref_stats_cache[main_address] = {'v_ref': v_ref}
            return v_ref

        # Mode relatif: calculer à partir des données locales
        volumes = []

        # Voisins sortants
        for _, _, data in self.graph.out_edges(main_address, data=True):
            volumes.append(data.get('weight', 0))

        # Voisins entrants
        for _, _, data in self.graph.in_edges(main_address, data=True):
            volumes.append(data.get('weight', 0))

        if not volumes:
            v_ref = 1.0  # Valeur par défaut minimale
        else:
            # Calculer le percentile configuré
            sorted_volumes = sorted(volumes)
            idx = int(len(sorted_volumes) * self.config.v_percentile_ref / 100)
            idx = min(idx, len(sorted_volumes) - 1)
            v_ref = sorted_volumes[idx] if idx >= 0 else sorted_volumes[-1]

            # Pour les micro-transactions, utiliser le max si le percentile 95 est trop faible
            if v_ref < 0.001:
                v_ref = max(v_ref, max(volumes) * 0.5)

        # Pour les micro-volumes, utiliser le max réel comme référence
        # mais garantir une valeur minimale pour éviter la division par zéro
        if not volumes:
            v_ref = 1.0
        elif max(volumes) < 0.001:
            # Très petits volumes: utiliser le max comme référence
            v_ref = max(volumes)
        else:
            # Normal: utiliser le percentile avec un minimum raisonnable
            v_ref = max(v_ref, max(volumes) * 0.01)

        self._ref_stats_cache[main_address] = {'v_ref': max(v_ref, 0.00001)}
        return self._ref_stats_cache[main_address]['v_ref']

    def _approximate_block_number(self, timestamp: Any) -> Optional[int]:
        """
        Convertit un timestamp en numéro de bloc approximatif.

        Args:
            timestamp: Timestamp (str ISO ou datetime)

        Returns:
            Numéro de bloc approximatif ou None si invalide
        """
        try:
            if isinstance(timestamp, str):
                if timestamp == 'unknown':
                    return None
                # Parser ISO format
                ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            elif isinstance(timestamp, datetime):
                ts = timestamp
            else:
                return None

            # Conversion en timestamp Unix
            seconds_since_genesis = ts.timestamp() - self.ETH_GENESIS_TIMESTAMP

            # Conversion en blocs (approximatif)
            blocks = int(seconds_since_genesis / self.ETH_BLOCK_TIME)

            return max(0, blocks)
        except (ValueError, TypeError, AttributeError):
            return None

    def _get_current_block(self) -> int:
        """
        Retourne le numéro de bloc courant (ou estimation).

        Utilise le timestamp le plus récent du graphe + marge.
        """
        if self._current_block is not None:
            return self._current_block

        max_block = 0
        for _, _, data in self.graph.edges(data=True):
            timestamp = data.get('time')
            block = self._approximate_block_number(timestamp)
            if block is not None:
                max_block = max(max_block, block)

        # Si aucun bloc trouvé, utiliser une estimation (Ethereum ~ Mars 2026)
        if max_block == 0:
            max_block = 22000000  # ~Mars 2026

        # Ajouter une marge pour les nouvelles transactions
        self._current_block = max_block + 1000
        return self._current_block
