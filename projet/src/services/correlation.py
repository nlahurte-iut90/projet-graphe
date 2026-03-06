import networkx as nx
import matplotlib
matplotlib.use('tkAgg')
import matplotlib.pyplot as plt
from src.domain.models import Address, CorrelationResult, RelationshipScore, AddressRelationshipTable, PathInfo, PropagatedPathInfo
from src.adapters.dune import DuneAdapter
import pandas as pd
import math
import time
from typing import Tuple, List, Optional, Dict, Set, Any
from datetime import datetime

from src.services.interactive_viz import InteractiveGraphVisualizer
from src.services.scoring import SimpleNodeScorer


class CorrelationService:
    def __init__(self, dune_adapter: DuneAdapter):
        self.dune_adapter = dune_adapter
        self.graph = nx.MultiDiGraph()
        self._table1: Optional[AddressRelationshipTable] = None
        self._table2: Optional[AddressRelationshipTable] = None

    def _add_transactions_to_graph(self, df: pd.DataFrame) -> Set[str]:
        """Helper pour ajouter un DataFrame de transactions au graphe.

        Returns:
            Set des nouveaux nœuds découverts (pas déjà dans le graphe avant l'ajout)
        """
        newly_discovered: Set[str] = set()

        if df.empty:
            return newly_discovered

        for _, row in df.iterrows():
            sender = str(row['from']).strip().lower()
            receiver = str(row['to']).strip().lower()

            if not sender or not receiver:
                continue

            # Tracker les nouveaux nœuds
            if sender not in self.graph:
                newly_discovered.add(sender)
            if receiver not in self.graph:
                newly_discovered.add(receiver)

            tx_hash = row.get('hash', 'unknown')
            value = float(row['value_eth'])
            value_wei = int(row.get('value_wei', value * 1e18))
            timestamp = row.get('block_time', 'unknown')

            self.graph.add_node(sender)
            self.graph.add_node(receiver)
            self.graph.add_edge(sender, receiver, weight=value, weight_wei=value_wei, hash=tx_hash, time=timestamp)

        return newly_discovered

    def _get_transaction_metrics(self, addr1: str, addr2: str) -> Optional[dict]:
        """Extract transaction metrics between two addresses from the graph."""
        edges_forward = self.graph.get_edge_data(addr1, addr2, default={})
        edges_backward = self.graph.get_edge_data(addr2, addr1, default={})

        all_edges = list(edges_forward.values()) + list(edges_backward.values())

        if not all_edges:
            return None

        values = [data['weight'] for data in all_edges]
        values_wei = [data.get('weight_wei', 0) for data in all_edges]
        timestamps = [data.get('time') for data in all_edges if data.get('time')]

        return {
            'tx_count': len(values),
            'total_volume': sum(values),
            'total_volume_wei': sum(values_wei),
            'avg_value': sum(values) / len(values) if values else 0,
            'max_value': max(values) if values else 0,
            'min_value': min(values) if values else 0,
            'timestamps': timestamps
        }

    def _calculate_recency_score(self, timestamps: List) -> float:
        """Calculate recency score based on transaction timestamps."""
        if not timestamps:
            return 0.5

        try:
            dates = []
            for ts in timestamps:
                if isinstance(ts, str):
                    try:
                        dates.append(pd.to_datetime(ts))
                    except:
                        continue
                elif isinstance(ts, datetime):
                    dates.append(ts)

            if not dates:
                return 0.5

            now = datetime.now()
            days_ago = [(now - d).days for d in dates]
            avg_days = sum(days_ago) / len(days_ago)

            score = max(0.0, 1.0 - (avg_days / 365))
            return score
        except Exception:
            return 0.5

    def _calculate_direct_score(self, addr1: Address, addr2: Address) -> Tuple[float, dict]:
        """
        Calculate direct relationship score using SimpleNodeScorer.
        
        Returns score based on: Activity (50%), Proximity (30%), Recency (20%)
        """
        scorer = SimpleNodeScorer(self.graph)
        node_score = scorer.score(addr1.address, addr2.address)
        
        # Conserver les métriques brutes pour compatibilité
        metrics = self._get_transaction_metrics(addr1.address, addr2.address) or {}
        metrics['node_score_breakdown'] = {
            'activity': node_score.activity,
            'proximity': node_score.proximity,
            'recency': node_score.recency
        }
        
        return node_score.total, metrics

    def _calculate_indirect_score(self, addr1: Address, addr2: Address, max_depth: int = 3) -> Tuple[float, List[PathInfo]]:
        """Calculate indirect relationship score via intermediate nodes."""
        paths = []
        total_score = 0.0

        # Vérifier que les deux nœuds sont dans le graphe
        if addr1.address not in self.graph or addr2.address not in self.graph:
            return 0.0, []

        try:
            for path in nx.all_simple_paths(self.graph, addr1.address, addr2.address, cutoff=max_depth):
                if len(path) <= 2:
                    continue

                path_score = 1.0
                decay = 0.5 ** (len(path) - 2)

                for i in range(len(path) - 1):
                    edge_metrics = self._get_transaction_metrics(path[i], path[i+1])
                    if edge_metrics:
                        edge_score = min(math.log10(edge_metrics['total_volume'] + 1) / 3, 1.0)
                        path_score *= edge_score
                    else:
                        path_score *= 0.1

                path_score *= decay * 100
                total_score += path_score

                paths.append(PathInfo(
                    nodes=[Address(a) for a in path],
                    score=path_score,
                    depth=len(path) - 1
                ))
        except nx.NetworkXNoPath:
            pass

        try:
            for path in nx.all_simple_paths(self.graph, addr2.address, addr1.address, cutoff=max_depth):
                if len(path) <= 2:
                    continue

                path_score = 1.0
                decay = 0.5 ** (len(path) - 2)

                for i in range(len(path) - 1):
                    edge_metrics = self._get_transaction_metrics(path[i], path[i+1])
                    if edge_metrics:
                        edge_score = min(math.log10(edge_metrics['total_volume'] + 1) / 3, 1.0)
                        path_score *= edge_score
                    else:
                        path_score *= 0.1

                path_score *= decay * 100
                total_score += path_score

                paths.append(PathInfo(
                    nodes=[Address(a) for a in reversed(path)],
                    score=path_score,
                    depth=len(path) - 1
                ))
        except nx.NetworkXNoPath:
            pass

        return min(total_score, 100.0), paths

    def _calculate_edge_propagation_weight(self, from_addr: str, to_addr: str) -> float:
        """
        Calcule le poids de propagation entre deux adresses.

        Basé sur:
        - Nombre de transactions
        - Volume total échangé
        - Récence des transactions

        Returns:
            Poids entre 0.0 et 1.0
        """
        metrics = self._get_transaction_metrics(from_addr, to_addr)
        if not metrics:
            return 0.0

        # Normaliser les métriques
        tx_count = metrics['tx_count']
        volume = metrics['total_volume']
        timestamps = metrics.get('timestamps', [])

        # Score de fréquence (0-1): asymptotique vers 1
        freq_score = min(tx_count / (tx_count + 5), 1.0)

        # Score de volume (0-1): logarithmique
        vol_score = min(math.log10(volume + 1) / 3, 1.0) if volume > 0 else 0

        # Score de récence (0-1)
        recency_score = self._calculate_recency_score(timestamps)

        # Poids combiné (priorité au volume, puis fréquence)
        weight = (0.5 * vol_score + 0.3 * freq_score + 0.2 * recency_score)

        return weight

    def _propagate_score_recursive(
        self,
        current_node: str,
        target_node: str,
        main_address: Address,
        current_score: float,
        current_depth: int,
        max_depth: int,
        visited: Set[str],
        path: List[str],
        path_scores: List[Tuple[str, float]],
        all_paths: List[Tuple[List[str], float, List[Tuple[str, float]]]]
    ) -> None:
        """
        DFS récursif pour propager les scores.

        Args:
            current_node: Nœud actuel dans la traversée
            target_node: Nœud cible final
            main_address: Adresse principale (pour le calcul des scores directs)
            current_score: Score accumulé jusqu'à ce nœud
            current_depth: Profondeur actuelle dans l'arbre de propagation
            max_depth: Profondeur maximale autorisée
            visited: Nœuds déjà visités (évite les cycles)
            path: Chemin actuel depuis main_address
            path_scores: Scores locaux pour chaque nœud du chemin
            all_paths: Liste accumulée de (chemin, score, path_scores)
        """
        # On a atteint la cible avec un chemin valide (au moins 1 hop)
        if current_node == target_node and len(path) > 1:
            all_paths.append((path.copy(), current_score, path_scores.copy()))
            return

        if current_depth >= max_depth:
            return

        # Explorer les voisins
        for neighbor in self.graph.successors(current_node):
            if neighbor in visited:
                continue

            # Calculer le poids de l'arête current -> neighbor
            edge_weight = self._calculate_edge_propagation_weight(current_node, neighbor)

            # Decay plus doux que l'actuel (0.7 vs 0.5)
            decay = 0.7 ** current_depth
            new_score = current_score * edge_weight * decay

            # Seuil minimal pour continuer (optimisation)
            if new_score < 0.01:  # Moins de 1% de contribution
                continue

            visited.add(neighbor)
            path.append(neighbor)
            path_scores.append((neighbor, edge_weight))

            self._propagate_score_recursive(
                neighbor, target_node, main_address,
                new_score, current_depth + 1, max_depth,
                visited, path, path_scores, all_paths
            )

            path_scores.pop()
            path.pop()
            visited.remove(neighbor)

    def _calculate_propagated_score(
        self,
        main_address: Address,
        target: Address,
        max_depth: int = 3
    ) -> Tuple[float, List[PropagatedPathInfo]]:
        """
        Calcule le score par propagation depuis main_address vers target.

        L'idée est que si main_address a une forte relation avec node1,
        et node1 a une forte relation avec node2 (target),
        alors main_address a une relation indirecte significative avec node2.

        Args:
            main_address: Adresse principale (source de la propagation)
            target: Adresse cible
            max_depth: Profondeur maximale de propagation

        Returns:
            Tuple de (score_propagé_total, liste des chemins de propagation)
        """
        if main_address.address == target.address:
            return 0.0, []

        # Vérifier si main_address et target sont dans le graphe
        if main_address.address not in self.graph or target.address not in self.graph:
            return 0.0, []

        # Étape 1: Obtenir tous les scores directs depuis main_address
        direct_scores = {}
        scorer = SimpleNodeScorer(self.graph)
        for neighbor in self.graph.neighbors(main_address.address):
            node_score = scorer.score(main_address.address, neighbor)
            if node_score.total > 0:
                # Normaliser le score à 0-1 pour la propagation
                direct_scores[neighbor] = node_score.total / 100.0

        if not direct_scores:
            return 0.0, []

        # Étape 2: Propagation DFS depuis chaque voisin direct
        all_contributions = []

        for start_node, start_score in direct_scores.items():
            if start_score <= 0:
                continue

            # Initialiser le DFS depuis ce nœud
            visited = {main_address.address, start_node}
            path = [main_address.address, start_node]
            path_scores = [(start_node, start_score)]

            self._propagate_score_recursive(
                current_node=start_node,
                target_node=target.address,
                main_address=main_address,
                current_score=start_score,
                current_depth=1,
                max_depth=max_depth,
                visited=visited,
                path=path,
                path_scores=path_scores,
                all_paths=all_contributions
            )

        # Étape 3: Agréger les contributions
        if not all_contributions:
            return 0.0, []

        # Calculer le score total et créer les objets PropagatedPathInfo
        total_score = 0.0
        propagation_paths = []

        for path_nodes, score, scores in all_contributions:
            total_score += score

            # Créer les objets Address pour le chemin
            intermediate = [Address(a) for a in path_nodes[1:-1]]  # Exclure source et target

            # Calculer le decay factor utilisé
            decay = 0.7 ** (len(path_nodes) - 2) if len(path_nodes) > 2 else 1.0

            propagation_paths.append(PropagatedPathInfo(
                source=main_address,
                intermediate=intermediate,
                target=target,
                propagated_score=score * 100,  # Remettre à l'échelle 0-100
                path_scores=scores,
                decay_factor=decay
            ))

        # Normaliser à 0-100
        final_score = min(total_score * 100, 100.0)

        return final_score, propagation_paths

    def calculate_relationship_scores(self, main_address: Address) -> AddressRelationshipTable:
        """
        Generate relationship score table for a main address using SimpleNodeScorer.
        
        Le scoring utilise 3 dimensions:
        - Activity (50%): volume, fréquence, bidirectionnalité
        - Proximity (30%): distance dans le graphe
        - Recency (20%): fraîcheur de la dernière transaction
        """
        relationships = {}
        connected_nodes = set(self.graph.nodes())
        
        # Initialiser le scorer une fois pour tout le graphe
        scorer = SimpleNodeScorer(self.graph)

        for node_address in connected_nodes:
            if node_address == main_address.address:
                continue

            target = Address(node_address)
            
            # NOUVEAU: Utiliser SimpleNodeScorer pour le score direct
            node_score = scorer.score(main_address.address, node_address)
            direct_score = node_score.total
            
            # Récupérer les métriques détaillées
            direct_metrics = node_score.metrics
            direct_metrics['score_breakdown'] = {
                'activity': node_score.activity,
                'proximity': node_score.proximity,
                'recency': node_score.recency
            }
            
            # Scores indirect et propagé (inchangés)
            indirect_score, indirect_paths = self._calculate_indirect_score(main_address, target)
            propagated_score, propagation_paths = self._calculate_propagated_score(
                main_address, target, max_depth=3
            )

            # Total = max des trois scores
            total_score = max(direct_score, indirect_score, propagated_score)

            relationships[node_address] = RelationshipScore(
                source=main_address,
                target=target,
                direct_score=direct_score,
                indirect_score=indirect_score,
                propagated_score=propagated_score,
                total_score=total_score,
                metrics={
                    **direct_metrics,
                    'indirect_paths': indirect_paths,
                    'propagation_paths': propagation_paths
                }
            )

        return AddressRelationshipTable(
            main_address=main_address,
            relationships=relationships
        )

    def _select_top_candidates_from_tables(
        self,
        table1: AddressRelationshipTable,
        table2: AddressRelationshipTable,
        candidate_nodes: List[Address],
        top_n: int,
        visited: Set[str]
    ) -> List[Address]:
        """
        Sélectionne les top_n nœuds avec les meilleurs scores de corrélation
        parmi les nœuds candidats découverts au niveau précédent.

        Args:
            table1: Table des relations depuis l'adresse 1
            table2: Table des relations depuis l'adresse 2
            candidate_nodes: Liste des nœuds candidats (découverts au niveau précédent)
            top_n: Nombre de nœuds à sélectionner par table
            visited: Set des adresses déjà visitées/exclues

        Returns:
            Liste des adresses uniques à expandre
        """
        # Filtrer pour ne garder que les candidats non visités
        candidate_set = {addr.address for addr in candidate_nodes if addr.address not in visited}

        if not candidate_set:
            return []

        candidates = {}

        # Récupérer les relations des candidats depuis la table 1
        sorted1 = table1.get_top_relationships(n=len(table1.relationships))
        count = 0
        for rel in sorted1:
            if rel.target.address in candidate_set and rel.target.address not in visited:
                candidates[rel.target.address] = rel.target
                count += 1
                if count >= top_n:
                    break

        # Récupérer les relations des candidats depuis la table 2
        sorted2 = table2.get_top_relationships(n=len(table2.relationships))
        count = 0
        for rel in sorted2:
            if rel.target.address in candidate_set and rel.target.address not in visited:
                candidates[rel.target.address] = rel.target
                count += 1
                if count >= top_n:
                    break

        return list(candidates.values())

    def build_graph_with_expansion(
        self,
        address1: Address,
        address2: Address,
        expansion_depth: int = 1,
        top_n: int = 5,
        base_tx_limit: int = 5,
        expansion_tx_limit: int = 3
    ) -> Tuple[AddressRelationshipTable, AddressRelationshipTable]:
        """
        Construit le graphe avec expansion basée sur les scores de corrélation.

        Workflow:
        1. Niveau 0: Récupère transactions des adresses principales
        2. Calcule les scores de relation initiaux
        3. Pour chaque niveau d'expansion:
           - Sélectionne top_n nœuds avec meilleurs scores
           - Récupère leurs transactions (expansion_tx_limit)
           - Ajoute au graphe
           - Recalcule les scores (indirects peuvent changer !)

        Args:
            address1: Première adresse principale
            address2: Deuxième adresse principale
            expansion_depth: Nombre d'itérations d'expansion
                - 1: Uniquement niveau 0 (pas d'expansion)
                - 2: Niveau 0 + 1 expansion
                - 3: Niveau 0 + 2 expansions, etc.
            top_n: Nombre de nœuds à sélectionner par adresse principale
            base_tx_limit: Nombre de transactions à récupérer pour les adresses principales
            expansion_tx_limit: Nombre de transactions à récupérer pour les nœuds d'expansion

        Returns:
            Tuple des tables de relation finales (table1, table2)
        """
        self.graph.clear()

        # Track visited pour éviter les cycles
        visited = {address1.address, address2.address}

        print(f"\n[Expansion] Configuration: depth={expansion_depth}, top_n={top_n}, base_tx_limit={base_tx_limit}, expansion_tx_limit={expansion_tx_limit}")

        # ═══════════════════════════════════════════════════════
        # NIVEAU 0: Base - Transactions des adresses principales
        # ═══════════════════════════════════════════════════════
        print(f"\n[Expansion] === LEVEL 0 (Base) ===")
        print(f"[Expansion] Fetching transactions for main addresses...")

        df_base = self.dune_adapter.get_transactions(address1.address, address2.address, limit=base_tx_limit)
        if df_base is None:
            print("[Expansion] WARNING: Failed to fetch base transactions, using empty graph")
            df_base = pd.DataFrame()
        level0_discovered = self._add_transactions_to_graph(df_base)

        print(f"[Expansion] Level 0: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")
        print(f"[Expansion] Level 0 discovered: {len(level0_discovered)} new nodes")

        # Calcul initial des scores
        print(f"[Expansion] Calculating initial relationship scores...")
        self._table1 = self.calculate_relationship_scores(address1)
        self._table2 = self.calculate_relationship_scores(address2)

        # Afficher les meilleurs scores du niveau 0
        top1 = self._table1.get_top_relationships(n=3)
        top2 = self._table2.get_top_relationships(n=3)
        print(f"[Expansion] Top correlations from Addr1: {[r.target.address[:10] + '...' for r in top1]}")
        print(f"[Expansion] Top correlations from Addr2: {[r.target.address[:10] + '...' for r in top2]}")

        # ═══════════════════════════════════════════════════════
        # EXPANSION ITÉRATIVE (expansion_depth - 1 itérations)
        # ═══════════════════════════════════════════════════════

        # Le premier niveau d'expansion utilise les nœuds découverts au niveau 0
        # comme candidats (tous les voisins des adresses principales)
        current_level_candidates = [Address(addr) for addr in level0_discovered]

        for level in range(1, expansion_depth):
            print(f"\n[Expansion] === LEVEL {level} (Expansion {level}/{expansion_depth - 1}) ===")

            # ÉTAPE 1: SÉLECTION - Top nœuds parmi les candidats du niveau courant
            # Seuls les nœuds découverts au niveau précédent sont éligibles
            candidates = self._select_top_candidates_from_tables(
                self._table1, self._table2, current_level_candidates, top_n, visited
            )

            if not candidates:
                print(f"[Expansion] No new candidates to expand from {len(current_level_candidates)} candidates, stopping")
                break

            print(f"[Expansion] Selected {len(candidates)} candidates from {len(current_level_candidates)} candidates")
            print(f"[Expansion] Selected addresses: {[c.address[:10] + '...' for c in candidates]}")

            # ÉTAPE 2: RÉCUPÉRATION - Fetch transactions pour chaque candidat
            print(f"[Expansion] Fetching transactions for selected candidates...")
            newly_discovered: Set[str] = set()
            successful_fetches = 0
            failed_fetches = 0

            for i, candidate in enumerate(candidates):
                if i > 0:
                    time.sleep(0.5)

                df = self.dune_adapter.get_transactions_for_address(candidate.address, limit=expansion_tx_limit)

                # Check if the fetch returned valid data
                # An empty DataFrame means successful fetch but no transactions
                # None means fetch failed (e.g., rate limiting after retries)
                if df is not None:
                    new_nodes = self._add_transactions_to_graph(df)
                    newly_discovered.update(new_nodes)
                    visited.add(candidate.address)
                    successful_fetches += 1
                else:
                    # Fetch failed (e.g., rate limiting after retries)
                    # Don't mark as visited - it will remain in candidate list for potential retry
                    failed_fetches += 1

            print(f"[Expansion] After fetch: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")
            print(f"[Expansion] Successful fetches: {successful_fetches}, Failed: {failed_fetches}")
            print(f"[Expansion] Newly discovered at this level: {len(newly_discovered)} nodes")

            # ÉTAPE 3: RECALCUL - Les scores peuvent changer (nouveaux chemins indirects !)
            print(f"[Expansion] Recalculating relationship scores with new data...")
            self._table1 = self.calculate_relationship_scores(address1)
            self._table2 = self.calculate_relationship_scores(address2)

            # Afficher l'évolution
            new_top1 = self._table1.get_top_relationships(n=3)
            new_top2 = self._table2.get_top_relationships(n=3)
            print(f"[Expansion] Top correlations from Addr1: {[r.target.address[:10] + '...' for r in new_top1]}")
            print(f"[Expansion] Top correlations from Addr2: {[r.target.address[:10] + '...' for r in new_top2]}")

            # Préparer les candidats pour le prochain niveau
            # Seuls les nœuds nouvellement découverts sont éligibles pour l'expansion suivante
            current_level_candidates = [Address(addr) for addr in newly_discovered]

        print(f"\n[Expansion] === COMPLETE ===")
        print(f"[Expansion] Final graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

        return self._table1, self._table2

    def visualize_graph(self, address1: Address, address2: Address):
        """Visualize the graph using Matplotlib."""
        if self.graph.number_of_nodes() == 0:
            print("Graph is empty, nothing to visualize.")
            return

        plt.figure(figsize=(16, 10))

        viz_graph = self.graph
        pos = {}

        p1 = (-3.0, 0.0)
        p2 = (3.0, 0.0)
        pos[address1.address] = p1
        pos[address2.address] = p2

        undirected = viz_graph.to_undirected()

        try:
            dist_from_1 = nx.single_source_shortest_path_length(undirected, address1.address)
        except:
            dist_from_1 = {address1.address: 0}

        try:
            dist_from_2 = nx.single_source_shortest_path_length(undirected, address2.address)
        except:
            dist_from_2 = {address2.address: 0}

        depth_groups = {}
        max_depth = 0

        for node in viz_graph.nodes():
            if node == address1.address or node == address2.address:
                continue

            d1 = dist_from_1.get(node, float('inf'))
            d2 = dist_from_2.get(node, float('inf'))
            depth = min(d1, d2)

            if depth < float('inf'):
                if depth not in depth_groups:
                    depth_groups[depth] = []
                depth_groups[depth].append((node, d1, d2))
                max_depth = max(max_depth, depth)

        for depth in range(1, max_depth + 1):
            if depth not in depth_groups:
                continue

            nodes_at_depth = depth_groups[depth]
            left_nodes = []
            right_nodes = []
            center_nodes = []

            for node, d1, d2 in nodes_at_depth:
                if d1 < d2:
                    left_nodes.append(node)
                elif d2 < d1:
                    right_nodes.append(node)
                else:
                    center_nodes.append(node)

            radius = 1.5 + (depth - 1) * 1.0

            if left_nodes:
                n = len(left_nodes)
                start_ang = math.pi / 2
                end_ang = 3 * math.pi / 2
                step = (end_ang - start_ang) / max(n, 1)
                for i, node in enumerate(sorted(left_nodes)):
                    ang = start_ang + i * step + step/2
                    pos[node] = (p1[0] + radius * math.cos(ang), p1[1] + radius * math.sin(ang))

            if right_nodes:
                n = len(right_nodes)
                start_ang = -math.pi / 2
                end_ang = math.pi / 2
                step = (end_ang - start_ang) / max(n, 1)
                for i, node in enumerate(sorted(right_nodes)):
                    ang = start_ang + i * step + step/2
                    pos[node] = (p2[0] + radius * math.cos(ang), p2[1] + radius * math.sin(ang))

            if center_nodes:
                n = len(center_nodes)
                h_step = 4.0 / max(n + 1, 1)
                start_y = -2.0
                for i, node in enumerate(sorted(center_nodes)):
                    pos[node] = (0, start_y + (i + 1) * h_step)

        remaining = set(viz_graph.nodes()) - set(pos.keys())
        if remaining:
            sub_pos = nx.spring_layout(viz_graph.subgraph(remaining), center=(0, 0))
            pos.update(sub_pos)

        node_colors = []
        node_sizes = []
        for node in viz_graph.nodes():
            if node == address1.address or node == address2.address:
                node_colors.append('#ff7f0e')
                node_sizes.append(1000)
            else:
                node_colors.append('#1f77b4')
                node_sizes.append(600)

        nx.draw_networkx_nodes(viz_graph, pos, node_color=node_colors, node_size=node_sizes, alpha=0.9, edgecolors='white', linewidths=1.5)

        ax = plt.gca()

        edge_groups = {}
        for u, v, k, data in viz_graph.edges(data=True, keys=True):
            if (u, v) not in edge_groups:
                edge_groups[(u, v)] = []
            edge_groups[(u, v)].append(data)

        for (u, v), datas in edge_groups.items():
            total = len(datas)
            for i, data in enumerate(datas):
                rad = 0.1 + (i * 0.1)
                weight = data.get('weight', 0)
                width = 2.0 + min(weight, 5.0)

                nx.draw_networkx_edges(
                    viz_graph, pos,
                    edgelist=[(u, v)],
                    width=width,
                    arrowstyle='-|>',
                    arrowsize=25,
                    edge_color='black',
                    alpha=0.8,
                    connectionstyle=f"arc3,rad={rad}"
                )

                val = data.get('weight', 0)
                x1, y1 = pos[u]
                x2, y2 = pos[v]
                mx = (x1 + x2) / 2
                my = (y1 + y2) / 2
                dx = x2 - x1
                dy = y2 - y1
                lx = mx + (dy * rad * 0.5)
                ly = my - (dx * rad * 0.5)
                label_text = f"{val:.4f}"

                ax.text(
                    lx, ly,
                    label_text,
                    fontsize=7,
                    color='black',
                    fontweight='bold',
                    horizontalalignment='center',
                    verticalalignment='center',
                    bbox=dict(boxstyle='round,pad=0.2', fc='#fff', alpha=0.9, ec='#ccc', lw=0.5)
                )

        labels = {}
        for node in viz_graph.nodes():
            if node == address1.address:
                labels[node] = "Addr1"
            elif node == address2.address:
                labels[node] = "Addr2"
            else:
                labels[node] = f"{node[:4]}..{node[-3:]}"

        nx.draw_networkx_labels(viz_graph, pos, labels=labels, font_size=8, font_weight='bold', font_color='black')

        plt.title(f"Transaction Graph (Individual Txs)", fontsize=14)
        plt.axis('off')
        plt.show()

    def calculate_score(
        self,
        address1: Address,
        address2: Address,
        expansion_depth: int = 1,
        top_n: int = 5,
        base_tx_limit: int = 5,
        expansion_tx_limit: int = 3
    ) -> CorrelationResult:
        """Calculate correlation score between two addresses with graph expansion."""
        table1, table2 = self.build_graph_with_expansion(
            address1, address2,
            expansion_depth=expansion_depth,
            top_n=top_n,
            base_tx_limit=base_tx_limit,
            expansion_tx_limit=expansion_tx_limit
        )

        relationship = table1.get_relationship(address2)

        num_nodes = self.graph.number_of_nodes()
        num_edges = self.graph.number_of_edges()
        try:
            has_path = nx.has_path(self.graph, address1.address, address2.address) or nx.has_path(self.graph, address2.address, address1.address)
        except nx.NodeNotFound:
            has_path = False

        score = relationship.total_score if relationship else 0.0

        return CorrelationResult(
            source=address1,
            target=address2,
            score=score,
            path=[address1, address2] if relationship else [],
            details={
                "nodes": num_nodes,
                "edges": num_edges,
                "notes": f"Graph built with expansion_depth={expansion_depth}, top_n={top_n}, base_tx_limit={base_tx_limit}, expansion_tx_limit={expansion_tx_limit}",
                "has_path": has_path,
                "direct_score": relationship.direct_score if relationship else 0.0,
                "indirecte_score": relationship.propagated_score if relationship else 0.0,
                "tx_count": relationship.metrics.get('tx_count', 0) if relationship else 0,
                "total_volume": relationship.metrics.get('total_volume', 0) if relationship else 0,
                "expansion_depth": expansion_depth,
                "top_n": top_n,
                "base_tx_limit": base_tx_limit,
                "expansion_tx_limit": expansion_tx_limit,
            }
        )

    def visualize_interactive(
        self,
        address1: Address,
        address2: Address,
        tables: Optional[List[AddressRelationshipTable]] = None,
        auto_open: bool = True,
        params: Optional[Dict[str, Any]] = None
    ) -> str:
        """Crée une visualisation HTML interactive du graphe."""
        if self.graph.number_of_nodes() == 0:
            raise ValueError("Graph is empty. Call build_graph_with_expansion first.")

        visualizer = InteractiveGraphVisualizer()
        if tables:
            visualizer.set_relationship_tables(tables)
        elif self._table1 and self._table2:
            visualizer.set_relationship_tables([self._table1, self._table2])

        return visualizer.visualize(
            graph=self.graph,
            main_addresses=[address1, address2],
            title=f"Ethereum Correlation: {address1.address[:10]}... vs {address2.address[:10]}...",
            auto_open=auto_open,
            params=params
        )
