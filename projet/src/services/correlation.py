import networkx as nx
import matplotlib
matplotlib.use('tkAgg')
import matplotlib.pyplot as plt
from src.domain.models import Address, CorrelationResult, RelationshipScore, AddressRelationshipTable
from src.adapters.dune import DuneAdapter
import pandas as pd
import math
import time
from typing import Tuple, List, Optional, Dict, Set, Any
from datetime import datetime

from src.services.interactive_viz import InteractiveGraphVisualizer
from src.services.scoring import TemporalScorer


class CorrelationService:
    """
    Service de corrélation utilisant TemporalScorer unifié.

    Le TemporalScorer combine:
    - Score Direct: Intensité (50%), Récence (25%), Synchronie (15%), Équilibre (10%)
    - Score Indirect: Algorithme de Katz temporel avec conservation de volume
    - Score Total: Combinaison dynamique avec terme d'interaction
    """

    def __init__(self, dune_adapter: DuneAdapter):
        """
        Initialise le service de corrélation.

        Args:
            dune_adapter: Adaptateur pour récupérer les transactions
        """
        self.dune_adapter = dune_adapter
        self.graph = nx.MultiDiGraph()
        self._table1: Optional[AddressRelationshipTable] = None
        self._table2: Optional[AddressRelationshipTable] = None
        self._scorer: Optional[TemporalScorer] = None

    def _get_scorer(self) -> TemporalScorer:
        """Retourne le scorer temporel pour le graphe actuel."""
        # Recréer toujours le scorer pour éviter les caches obsolètes
        # quand le graphe est modifié lors de l'expansion
        return TemporalScorer(self.graph)

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


    def calculate_initial_scores(
        self,
        main_address: Address,
        base_nodes: Optional[Set[str]] = None
    ) -> AddressRelationshipTable:
        """
        Calcule les scores initiaux pour les nœuds de base avec TemporalScorer.

        Cette méthode évalue les relations directes avec les dimensions temporelles:
        - Intensité (50%): Volume et fréquence des transactions
        - Récence (25%): Fraîcheur des transactions
        - Synchronie (15%): Corrélation temporelle entrées/sorties
        - Équilibre (10%): Bonus pour bidirectionnalité

        Args:
            main_address: Adresse principale
            base_nodes: Ensemble des nœuds de base à évaluer (voisins directs).
                       Si None, tous les nœuds connectés sont évalués.

        Returns:
            AddressRelationshipTable avec les scores initiaux
        """
        relationships = {}
        scorer = self._get_scorer()

        # Déterminer les nœuds à évaluer
        if base_nodes is None:
            base_nodes = set(self.graph.nodes())

        for node_address in base_nodes:
            if node_address == main_address.address:
                continue

            target = Address(node_address)

            # Score avec TemporalScorer (dimensions temporelles)
            node_score = scorer.score(main_address.address, node_address)

            # Créer le RelationshipScore avec les nouvelles dimensions
            # Le score_breakdown est déjà inclus dans node_score.metrics par TemporalScorer
            rel_score = RelationshipScore(
                source=main_address,
                target=target,
                direct_score=node_score.direct,
                indirect_score=node_score.indirect,
                confidence=node_score.confidence,
                metrics={
                    **node_score.metrics,
                    'scorer_used': 'temporal'
                }
            )

            relationships[node_address] = rel_score

        return AddressRelationshipTable(
            main_address=main_address,
            relationships=relationships
        )

    def calculate_relationship_scores(
        self,
        main_address: Address
    ) -> AddressRelationshipTable:
        """
        Génère la table des scores de relation pour une adresse principale.

        Utilise TemporalScorer pour tous les nœuds avec les dimensions:
        - Intensité (50%): Volume et fréquence
        - Récence (25%): Fraîcheur des transactions
        - Synchronie (15%): Corrélation temporelle
        - Équilibre (10%): Bonus bidirectionnalité
        - Indirect: Score Katz temporel

        Args:
            main_address: Adresse principale

        Returns:
            AddressRelationshipTable avec les scores de relation
        """
        relationships = {}
        connected_nodes = set(self.graph.nodes())
        scorer = self._get_scorer()

        for node_address in connected_nodes:
            if node_address == main_address.address:
                continue

            target = Address(node_address)

            # Score avec TemporalScorer (tous les nœuds)
            node_score = scorer.score(main_address.address, node_address)

            # Récupérer les métriques détaillées
            # Le score_breakdown est déjà inclus dans node_score.metrics par TemporalScorer
            metrics = node_score.metrics
            metrics['scorer_used'] = 'temporal'

            # Créer le RelationshipScore avec direct et indirect
            rel_score = RelationshipScore(
                source=main_address,
                target=target,
                direct_score=node_score.direct,
                indirect_score=node_score.indirect,
                confidence=node_score.confidence,
                metrics=metrics
            )

            relationships[node_address] = rel_score

        return AddressRelationshipTable(
            main_address=main_address,
            relationships=relationships
        )

    def _select_top_candidates_from_scores(
        self,
        newly_discovered: Set[str],
        table1: AddressRelationshipTable,
        table2: AddressRelationshipTable,
        top_n: int,
        visited: Set[str]
    ) -> List[Address]:
        """
        Sélectionne les top_n nœuds avec les meilleurs scores de corrélation
        parmi les nouveaux nœuds découverts, en utilisant les scores TemporalScorer.

        Args:
            newly_discovered: Set des nœuds découverts au niveau précédent
            table1: Table des relations depuis l'adresse 1 (avec scores TemporalScorer)
            table2: Table des relations depuis l'adresse 2 (avec scores TemporalScorer)
            top_n: Nombre de nœuds à sélectionner par adresse principale
            visited: Set des adresses déjà visitées/exclues

        Returns:
            Liste des adresses uniques à expandre
        """
        # Filtrer pour ne garder que les nœuds non visités
        candidates = {addr for addr in newly_discovered if addr not in visited}

        if not candidates:
            return []

        selected = {}

        # Fonction helper pour récupérer le score max d'un nœud entre les deux tables
        def get_max_score(node_addr: str) -> float:
            scores = []
            rel1 = table1.get_relationship(Address(node_addr))
            if rel1:
                scores.append(rel1.total_score)
            rel2 = table2.get_relationship(Address(node_addr))
            if rel2:
                scores.append(rel2.total_score)
            return max(scores) if scores else 0.0

        # Créer une liste de (score, address) pour tous les candidats
        scored_candidates = [
            (get_max_score(addr), addr)
            for addr in candidates
        ]

        # Trier par score décroissant
        scored_candidates.sort(reverse=True)

        # Sélectionner les top_n par adresse principale (jusqu'à 2*top_n total)
        count = 0
        for score, addr in scored_candidates:
            if addr not in selected:
                selected[addr] = Address(addr)
                count += 1
                if count >= top_n * 2:  # top_n par adresse principale
                    break

        return list(selected.values())

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
           - Recalcule les scores

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
        self._add_transactions_to_graph(df_base)

        print(f"[Expansion] Level 0: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

        # Récupérer explicitement tous les voisins des deux adresses principales
        # (pas seulement les "nouveaux" nœuds pour éviter l'asymétrie)
        level0_neighbors: Set[str] = set()
        for addr in [address1.address, address2.address]:
            if addr in self.graph:
                level0_neighbors.update(self.graph.predecessors(addr))
                level0_neighbors.update(self.graph.successors(addr))

        # Exclure les adresses principales elles-mêmes
        level0_neighbors.discard(address1.address)
        level0_neighbors.discard(address2.address)

        print(f"[Expansion] Level 0 neighbors (from both addresses): {len(level0_neighbors)} nodes")

        # ═══════════════════════════════════════════════════════
        # SCORING INITIAL (Niveau 0) - Utilise TemporalScorer
        # ═══════════════════════════════════════════════════════
        print(f"[Expansion] Calculating initial scores for base nodes (using TemporalScorer)...")
        self._table1 = self.calculate_initial_scores(address1, level0_neighbors)
        self._table2 = self.calculate_initial_scores(address2, level0_neighbors)

        # Afficher les meilleurs scores du niveau 0 (calculés par TemporalScorer)
        top1 = self._table1.get_top_relationships(n=3)
        top2 = self._table2.get_top_relationships(n=3)
        print(f"[Expansion] Top correlations from Addr1 (TemporalScorer):")
        for r in top1:
            print(f"    {r.target.address[:10]}...: total={r.total_score:.1f}, direct={r.direct_score:.2f}, indirect={r.indirect_score:.2f}, conf={r.confidence}")
        print(f"[Expansion] Top correlations from Addr2 (TemporalScorer):")
        for r in top2:
            print(f"    {r.target.address[:10]}...: total={r.total_score:.1f}, direct={r.direct_score:.2f}, indirect={r.indirect_score:.2f}, conf={r.confidence}")

        # ═══════════════════════════════════════════════════════
        # EXPANSION ITÉRATIVE (expansion_depth - 1 itérations)
        # ═══════════════════════════════════════════════════════

        # Le premier niveau d'expansion utilise les nœuds découverts au niveau 0
        # comme candidats (tous les voisins des adresses principales)
        newly_discovered = level0_neighbors.copy()

        for level in range(1, expansion_depth):
            print(f"\n[Expansion] === LEVEL {level} (Expansion {level}/{expansion_depth - 1}) ===")

            # ÉTAPE 1: SÉLECTION - Top nœuds parmi les candidats découverts au niveau précédent
            # Utilise les scores TemporalScorer pour sélectionner les meilleurs candidats
            candidates = self._select_top_candidates_from_scores(
                newly_discovered, self._table1, self._table2, top_n, visited
            )

            if not candidates:
                print(f"[Expansion] No new candidates to expand from {len(newly_discovered)} newly discovered nodes, stopping")
                break

            print(f"[Expansion] Selected {len(candidates)} candidates from {len(newly_discovered)} newly discovered nodes")
            print(f"[Expansion] Selected addresses: {[c.address[:10] + '...' for c in candidates]}")

            # ÉTAPE 2: RÉCUPÉRATION - Fetch transactions pour chaque candidat
            print(f"[Expansion] Fetching transactions for selected candidates...")
            newly_discovered = set()  # Réinitialiser pour ce niveau d'expansion
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

            # ÉTAPE 3: RECALCUL - Les scores peuvent changer avec les nouvelles données
            print(f"[Expansion] Recalculating relationship scores with new data...")
            self._table1 = self.calculate_relationship_scores(address1)
            self._table2 = self.calculate_relationship_scores(address2)

            # Afficher l'évolution avec les scores TemporalScorer
            new_top1 = self._table1.get_top_relationships(n=3)
            new_top2 = self._table2.get_top_relationships(n=3)
            print(f"[Expansion] Top correlations from Addr1 (by TemporalScorer):")
            for r in new_top1:
                print(f"    {r.target.address[:10]}...: total={r.total_score:.1f}, direct={r.direct_score:.2f}, indirect={r.indirect_score:.2f}, conf={r.confidence}")
            print(f"[Expansion] Top correlations from Addr2 (by TemporalScorer):")
            for r in new_top2:
                print(f"    {r.target.address[:10]}...: total={r.total_score:.1f}, direct={r.direct_score:.2f}, indirect={r.indirect_score:.2f}, conf={r.confidence}")

            # Les nouveaux nœuds découverts deviennent les candidats pour le prochain niveau
            # Leur scores ont été calculés par TemporalScorer ci-dessus

        print(f"\n[Expansion] === COMPLETE ===")
        print(f"[Expansion] Final graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

        # === NOUVELLES ANALYSES DE GRAPHE ===
        print(f"\n[Analysis] Running graph connectivity analysis...")
        connectivity = self._analyze_graph_connectivity()
        self._print_connectivity_summary(connectivity)

        print(f"\n[Analysis] Running centrality analysis...")
        centrality = self._analyze_centrality()
        self._print_centrality_summary(centrality)

        print(f"\n[Analysis] Running community detection...")
        communities = self._analyze_communities()
        self._print_communities_summary(communities)

        # Stocker les résultats pour utilisation ultérieure
        self._graph_analysis = {
            'connectivity': connectivity,
            'centrality': centrality,
            'communities': communities
        }

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
        """
        Calcule le score de corrélation entre deux adresses avec expansion du graphe.

        Args:
            address1: Première adresse
            address2: Deuxième adresse
            expansion_depth: Profondeur d'expansion du graphe
            top_n: Nombre de nœuds à sélectionner à chaque niveau
            base_tx_limit: Limite de transactions pour les adresses principales
            expansion_tx_limit: Limite de transactions pour les nœuds d'expansion

        Returns:
            CorrelationResult avec le score et les détails
        """
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
                "indirect_score": relationship.indirect_score if relationship else 0.0,
                "confidence": relationship.confidence if relationship else "low",
                "tx_count": relationship.metrics.get('n_total', 0) if relationship else 0,
                "total_volume": relationship.metrics.get('v_total', 0) if relationship else 0,
                "expansion_depth": expansion_depth,
                "top_n": top_n,
                "base_tx_limit": base_tx_limit,
                "expansion_tx_limit": expansion_tx_limit
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

        # Calculer le score global entre les deux adresses principales
        global_score = None
        if tables and len(tables) >= 2:
            # Récupérer le score depuis la première table (address1 -> address2)
            rel1 = tables[0].get_relationship(address2)
            rel2 = tables[1].get_relationship(address1)
            if rel1 and rel2:
                global_score = (rel1.total_score + rel2.total_score) / 2
            elif rel1:
                global_score = rel1.total_score
            elif rel2:
                global_score = rel2.total_score
        elif self._table1 and self._table2:
            rel1 = self._table1.get_relationship(address2)
            rel2 = self._table2.get_relationship(address1)
            if rel1 and rel2:
                global_score = (rel1.total_score + rel2.total_score) / 2
            elif rel1:
                global_score = rel1.total_score
            elif rel2:
                global_score = rel2.total_score

        # Récupérer l'analyse de graphe si disponible
        graph_analysis = getattr(self, '_graph_analysis', None)

        return visualizer.visualize(
            graph=self.graph,
            main_addresses=[address1, address2],
            title=f"Ethereum Correlation: {address1.address[:10]}... vs {address2.address[:10]}...",
            auto_open=auto_open,
            params=params,
            global_score=global_score,
            graph_analysis=graph_analysis
        )

    def _analyze_graph_connectivity(self) -> Dict[str, Any]:
        """
        Analyse la connectivité du graphe pour détecter les clusters.

        Returns:
            Dict avec:
            - sccs: Liste des composantes fortement connexes
            - wccs: Liste des composantes faiblement connexes
            - articulation_points: Points pivots reliant des écosystèmes
            - scc_count: Nombre de SCCs
            - largest_scc_size: Taille de la plus grande SCC
        """
        if self.graph.number_of_nodes() < 2:
            return {}

        # Composantes fortement connexes (cycles de transactions)
        sccs = list(nx.strongly_connected_components(self.graph))

        # Composantes faiblement connexes (écosystèmes isolés)
        wccs = list(nx.weakly_connected_components(self.graph))

        # Points d'articulation (convertir en graphe non orienté)
        undirected = self.graph.to_undirected()
        try:
            articulation_points = list(nx.articulation_points(undirected))
        except nx.NetworkXError:
            articulation_points = []

        return {
            'sccs': sccs,
            'wccs': wccs,
            'articulation_points': articulation_points,
            'scc_count': len(sccs),
            'largest_scc_size': len(max(sccs, key=len)) if sccs else 0,
            'wcc_count': len(wccs),
            'articulation_count': len(articulation_points)
        }

    def _analyze_centrality(self) -> Dict[str, Any]:
        """
        Calcule les mesures de centralité du graphe.

        Returns:
            Dict avec:
            - pagerank: Dict {address: score} pondéré par volume
            - betweenness: Dict {address: score} pondéré par volume
            - top_pagerank: Top 5 adresses par PageRank
            - top_betweenness: Top 5 adresses par betweenness
        """
        if self.graph.number_of_nodes() < 3:
            return {}

        # PageRank pondéré par volume
        pagerank = nx.pagerank(self.graph, weight='weight')

        # Betweenness centrality pondéré (inverse du volume comme distance)
        betweenness = nx.betweenness_centrality(
            self.graph,
            weight=lambda u, v, d: 1.0 / (d.get('weight', 1) + 0.001)
        )

        # Top 5 pour chaque métrique
        top_pagerank = sorted(pagerank.items(), key=lambda x: x[1], reverse=True)[:5]
        top_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            'pagerank': pagerank,
            'betweenness': betweenness,
            'top_pagerank': top_pagerank,
            'top_betweenness': top_betweenness,
            'avg_pagerank': sum(pagerank.values()) / len(pagerank) if pagerank else 0
        }

    def _analyze_communities(self) -> Dict[str, Any]:
        """
        Détecte les communautés et motifs dans le graphe.

        Returns:
            Dict avec:
            - cliques: Liste des cliques maximales
            - max_clique_size: Taille de la plus grande clique
            - clique_count: Nombre de cliques
            - largest_cliques: Top 3 plus grandes cliques
        """
        if self.graph.number_of_nodes() < 3:
            return {}

        # Convertir en graphe non orienté pour les cliques
        undirected = self.graph.to_undirected()

        # Cliques maximales
        cliques = list(nx.find_cliques(undirected))

        # Trier par taille
        cliques_by_size = sorted(cliques, key=len, reverse=True)

        return {
            'cliques': cliques,
            'max_clique_size': len(cliques_by_size[0]) if cliques else 0,
            'clique_count': len(cliques),
            'largest_cliques': cliques_by_size[:3]  # Top 3 plus grandes
        }

    def _print_connectivity_summary(self, connectivity: Dict):
        """Affiche un résumé de l'analyse de connectivité."""
        if not connectivity:
            print("  [Connectivity] Graph too small for analysis")
            return

        print(f"  Strongly Connected Components: {connectivity['scc_count']}")
        print(f"  Largest SCC size: {connectivity['largest_scc_size']} nodes")
        print(f"  Weakly Connected Components: {connectivity['wcc_count']}")
        print(f"  Articulation points: {connectivity['articulation_count']}")

        if connectivity['articulation_points']:
            print(f"  Pivot addresses: {[ap[:10] + '...' for ap in connectivity['articulation_points'][:3]]}")

    def _print_centrality_summary(self, centrality: Dict):
        """Affiche un résumé de l'analyse de centralité."""
        if not centrality:
            print("  [Centrality] Graph too small for analysis")
            return

        print(f"  Top PageRank:")
        for addr, score in centrality['top_pagerank'][:3]:
            print(f"    {addr[:10]}...: {score:.4f}")

        print(f"  Top Betweenness (intermediaries):")
        for addr, score in centrality['top_betweenness'][:3]:
            print(f"    {addr[:10]}...: {score:.4f}")

    def _print_communities_summary(self, communities: Dict):
        """Affiche un résumé de la détection de communautés."""
        if not communities:
            print("  [Communities] Graph too small for analysis")
            return

        print(f"  Cliques found: {communities['clique_count']}")
        print(f"  Max clique size: {communities['max_clique_size']}")

        if communities['max_clique_size'] >= 3:
            print(f"  Largest clique members:")
            for clique in communities['largest_cliques'][:1]:
                for addr in list(clique)[:3]:
                    print(f"    - {addr[:10]}...")
