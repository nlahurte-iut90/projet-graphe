"""Scorer basé sur les métriques de multiplicité des chemins."""

from typing import Dict, Any, List, Optional
from collections import Counter
import math
import numpy as np
import networkx as nx
from datetime import datetime

from src.services.scoring.base import SimilarityStrategy, NodeScore


class MultipathScorer(SimilarityStrategy):
    """
    Scorer basé sur la robustesse des connexions via multiplicité des chemins.

    Utilise des métriques de théorie des graphes avancées:
    - Connectivité de nœuds/arêtes
    - Résistance effective (analogie électrique)
    - Entropie des chemins
    - Betweenness centrality restreinte
    """

    def __init__(self, graph: nx.MultiDiGraph, max_path_length: int = 4):
        super().__init__(graph)
        self.max_path_length = max_path_length
        self._undirected = None
        self._L_pinv = None
        self._node_to_idx = None

    def get_name(self) -> str:
        return "MultipathScorer"

    def get_description(self) -> str:
        return ("Scorer basé sur la robustesse des connexions: "
                "connectivité, résistance effective, entropie des chemins")

    def _get_undirected(self) -> nx.Graph:
        """Retourne la version non orientée du graphe (avec cache)."""
        if self._undirected is None:
            self._undirected = self.graph.to_undirected()
        return self._undirected

    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule le score basé sur la robustesse des connexions.

        Combine plusieurs métriques:
        - Connectivité de nœuds (30%)
        - Résistance effective (40%)
        - Entropie des chemins (20%)
        - Betweenness restreinte (10%)
        """
        if main_address == node:
            return NodeScore(
                total=100.0,
                activity=100.0,
                proximity=100.0,
                recency=0.0,
                metrics={'self': True}
            )

        # Vérifier que les deux nœuds existent dans le graphe
        if main_address not in self.graph or node not in self.graph:
            return NodeScore(
                total=0.0,
                activity=0.0,
                proximity=0.0,
                recency=0.0,
                metrics={'error': 'Node not in graph'}
            )

        # Calcul des métriques
        connectivity_score = self._calc_connectivity_score(main_address, node)
        resistance_score = self._calc_effective_resistance_score(main_address, node)
        entropy_score = self._calc_path_entropy_score(main_address, node)
        betweenness_score = self._calc_restricted_betweenness(main_address, node)

        # Combinaison pondérée
        total = (
            0.30 * connectivity_score +
            0.40 * resistance_score +
            0.20 * entropy_score +
            0.10 * betweenness_score
        )

        # Activité = robustesse de connexion
        activity = (connectivity_score + resistance_score) / 2

        # Proximité = score combiné
        proximity = total

        # Récence basée sur les chemins
        recency = self._calc_path_recency(main_address, node)

        return NodeScore(
            total=round(min(total, 100.0), 2),
            activity=round(activity, 2),
            proximity=round(proximity, 2),
            recency=round(recency, 2),
            metrics={
                'connectivity_score': connectivity_score,
                'resistance_score': resistance_score,
                'entropy_score': entropy_score,
                'betweenness_score': betweenness_score,
                'vertex_connectivity': self._get_vertex_connectivity(main_address, node),
                'effective_resistance': self._get_effective_resistance(main_address, node),
                'num_paths': self._count_paths(main_address, node)
            }
        )

    def _calc_connectivity_score(self, u: str, v: str) -> float:
        """
        Score basé sur la connectivité de nœuds.

        - 0 chemins disjoints: 0
        - 1 chemin: 30
        - 2 chemins: 55
        - 3+ chemins: 75 (avec bonus par chemin supplémentaire)
        """
        conn = self._get_vertex_connectivity(u, v)

        if conn == 0:
            return 0.0
        elif conn == 1:
            return 30.0
        elif conn == 2:
            return 55.0
        else:
            return min(75.0 + (conn - 3) * 5, 100.0)

    def _get_vertex_connectivity(self, u: str, v: str) -> int:
        """Calcule la connectivité de nœuds entre u et v."""
        try:
            undirected = self._get_undirected()
            return nx.node_connectivity(undirected, u, v)
        except (nx.NetworkXError, nx.NodeNotFound):
            return 0

    def _calc_effective_resistance_score(self, u: str, v: str) -> float:
        """
        Score inversement proportionnel à la résistance effective.

        Résistance faible = connexion forte = score élevé.
        """
        resistance = self._get_effective_resistance(u, v)

        if resistance == float('inf'):
            return 0.0

        # Normalisation: R=0 -> 100, R=1 -> 50, R=5 -> 20
        score = 100 * math.exp(-resistance / 1.5)
        return min(score, 100.0)

    def _get_effective_resistance(self, u: str, v: str) -> float:
        """
        Calcule la résistance effective entre deux nœuds.

        Utilise la pseudoinverse du Laplacien du graphe.
        """
        try:
            # Calcul du Laplacien et sa pseudoinverse (avec cache)
            if self._L_pinv is None:
                undirected = self._get_undirected()
                L = nx.laplacian_matrix(undirected).astype(float)
                self._L_pinv = np.linalg.pinv(L.toarray())
                self._node_to_idx = {node: i for i, node in enumerate(undirected.nodes())}

            i = self._node_to_idx.get(u)
            j = self._node_to_idx.get(v)

            if i is None or j is None:
                return float('inf')

            # Résistance effective = L^+_ii + L^+_jj - 2*L^+_ij
            resistance = (
                self._L_pinv[i, i] +
                self._L_pinv[j, j] -
                2 * self._L_pinv[i, j]
            )

            return max(0, resistance)

        except Exception:
            return float('inf')

    def _calc_path_entropy_score(self, u: str, v: str) -> float:
        """
        Score basé sur l'entropie des longueurs de chemins.

        - Entropie basse = structure régulière (prédictible) = score élevé
        - Entropie haute = distribution uniforme (opportuniste) = score moyen
        """
        entropy_normalized = self._calc_path_entropy(u, v)

        # Score: entropie moyenne = 50, faible = 70 (prédictible), haute = 30 (aléatoire)
        score = 70 - 40 * (entropy_normalized - 0.5)
        return max(0, min(100, score))

    def _calc_path_entropy(self, u: str, v: str) -> float:
        """
        Calcule l'entropie de Shannon normalisée des longueurs de chemins.

        Returns:
            Entropie normalisée entre 0 et 1
        """
        path_lengths = []

        try:
            for path in nx.all_simple_paths(
                self._get_undirected(), u, v, cutoff=self.max_path_length
            ):
                path_lengths.append(len(path) - 1)
        except nx.NetworkXNoPath:
            pass

        if not path_lengths:
            return 0.0

        # Distribution de probabilité
        counts = Counter(path_lengths)
        total = sum(counts.values())
        probs = [c / total for c in counts.values()]

        # Entropie de Shannon
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)
        max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1

        return entropy / max_entropy if max_entropy > 0 else 0

    def _calc_restricted_betweenness(self, u: str, v: str) -> float:
        """
        Score de betweenness centrality restreinte.

        Mesure l'importance des nœuds intermédiaires sur les chemins u-v.
        """
        try:
            undirected = self._get_undirected()

            # Trouver tous les chemins les plus courts
            all_paths = list(nx.all_shortest_paths(undirected, u, v))
            total_paths = len(all_paths)

            if total_paths == 0:
                return 0.0

            # Calculer le score moyen de betweenness des nœuds intermédiaires
            betweenness_sum = 0.0

            for path in all_paths:
                for intermediate in path[1:-1]:  # Exclure u et v
                    # Compter combien de chemins passent par ce nœud
                    paths_through = sum(
                        1 for p in all_paths if intermediate in p
                    )
                    betweenness_sum += paths_through / total_paths

            # Normaliser à 0-100
            # Compter le nombre total de nœuds intermédiaires sur tous les chemins
            total_intermediate = sum(max(len(path) - 2, 0) for path in all_paths)
            if total_intermediate == 0:
                return 0.0
            avg_betweenness = betweenness_sum / total_intermediate
            return min(avg_betweenness * 100, 100.0)

        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return 0.0

    def _calc_path_recency(self, u: str, v: str) -> float:
        """
        Calcule un score de récence basé sur les transactions des chemins.
        """
        edges = self._get_all_edges(u, v)

        if not edges:
            return 0.0

        timestamps = []
        for e in edges:
            ts = e.get('time')
            if ts and ts != 'unknown':
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    elif isinstance(ts, datetime):
                        dt = ts
                    else:
                        continue
                    timestamps.append(dt)
                except (ValueError, TypeError):
                    continue

        if not timestamps:
            return 50.0  # Neutre si pas d'info

        # Dernière transaction
        last_tx = max(timestamps)
        now = datetime.now().astimezone() if last_tx.tzinfo else datetime.now()
        days_ago = max(0, (now - last_tx).total_seconds() / 86400)

        return 100 * math.exp(-days_ago / 30)

    def _count_paths(self, u: str, v: str) -> int:
        """Compte le nombre de chemins simples entre u et v."""
        try:
            return sum(
                1 for _ in nx.all_simple_paths(
                    self._get_undirected(), u, v, cutoff=self.max_path_length
                )
            )
        except nx.NetworkXNoPath:
            return 0

    def get_metrics(self, u: str, v: str) -> Dict[str, Any]:
        """Retourne toutes les métriques détaillées pour analyse."""
        return {
            'vertex_connectivity': self._get_vertex_connectivity(u, v),
            'effective_resistance': self._get_effective_resistance(u, v),
            'path_entropy': self._calc_path_entropy(u, v),
            'num_paths': self._count_paths(u, v),
            'path_length_distribution': self._get_path_length_distribution(u, v)
        }

    def _get_path_length_distribution(self, u: str, v: str) -> Dict[int, int]:
        """Distribution des longueurs de chemins."""
        lengths = []

        try:
            for path in nx.all_simple_paths(
                self._get_undirected(), u, v, cutoff=self.max_path_length
            ):
                lengths.append(len(path) - 1)
        except nx.NetworkXNoPath:
            pass

        return dict(Counter(lengths))
