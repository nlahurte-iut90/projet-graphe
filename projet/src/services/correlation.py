import networkx as nx
import matplotlib
matplotlib.use('tkAgg')
import matplotlib.pyplot as plt
from src.domain.models import Address, CorrelationResult, RelationshipScore, AddressRelationshipTable, PathInfo
from src.adapters.dune import DuneAdapter
import pandas as pd
import math
import time
from typing import Tuple, List, Optional, Dict, Set
from datetime import datetime

from src.services.interactive_viz import InteractiveGraphVisualizer

class CorrelationService:
    def __init__(self, dune_adapter: DuneAdapter):
        self.dune_adapter = dune_adapter
        self.graph = nx.MultiDiGraph()

    def _add_transactions_to_graph(self, df: pd.DataFrame):
        """Helper pour ajouter un DataFrame de transactions au graphe."""
        if df.empty:
            return

        for _, row in df.iterrows():
            sender = str(row['from']).strip().lower()
            receiver = str(row['to']).strip().lower()

            if not sender or not receiver:
                continue

            tx_hash = row.get('hash', 'unknown')
            value = float(row['value_eth'])
            value_wei = int(row.get('value_wei', value * 1e18))
            timestamp = row.get('block_time', 'unknown')

            self.graph.add_node(sender)
            self.graph.add_node(receiver)
            self.graph.add_edge(sender, receiver, weight=value, weight_wei=value_wei, hash=tx_hash, time=timestamp)

    def _get_top_candidates_from_nodes(
        self,
        nodes: List[Address],
        top_n: int,
        visited: Set[str],
        max_nodes_to_process: int = 10
    ) -> List[Address]:
        """
        Sélectionne les meilleurs candidats d'expansion depuis une liste de nœuds.

        Processus correct d'expansion:
        1. Récupère les transactions des nœuds du niveau actuel (appels API)
        2. Ajoute ces transactions au graphe (découvre de nouvelles adresses)
        3. Sélectionne les top_n nouvelles adresses pour le niveau suivant

        Args:
            nodes: Liste des nœuds à expandre (niveau actuel)
            top_n: Nombre de candidats à retourner pour le niveau suivant
            visited: Set des adresses déjà visitées
            max_nodes_to_process: Nombre max de nœuds à expandre (limiter les appels API)

        Returns:
            Liste des top_n meilleurs candidats découverts
        """
        if not nodes:
            return []

        # Trier les nœuds par activité (degré dans le graphe) pour prioriser les plus connectés
        nodes_by_activity = sorted(
            nodes,
            key=lambda addr: self.graph.degree(addr.address),
            reverse=True
        )

        # Limiter le nombre de nœuds à expandre (optimisation nombre d'appels API)
        nodes_to_expand = nodes_by_activity[:max_nodes_to_process]

        print(f"[Expansion] Expanding {len(nodes_to_expand)}/{len(nodes)} nodes from current level...")

        # AVANT de chercher des candidats, il faut d'abord récupérer les transactions
        # des nœuds du niveau actuel pour découvrir de nouvelles adresses
        newly_discovered = {}  # addr -> (Address, score/heuristic)

        for i, node_addr in enumerate(nodes_to_expand):
            # Petit délai pour éviter le rate limit de l'API Dune
            if i > 0:
                time.sleep(0.5)

            # Récupérer les transactions de ce nœud (appel API Dune)
            df = self.dune_adapter.get_transactions_for_address(node_addr.address, limit=5)

            if df.empty:
                continue

            # Identifier les nouvelles adresses découvertes dans ces transactions
            existing_nodes = set(self.graph.nodes())
            for _, row in df.iterrows():
                sender = str(row['from']).strip().lower()
                receiver = str(row['to']).strip().lower()

                for addr in [sender, receiver]:
                    # Une adresse est "nouvelle" si elle n'est pas dans visited ET pas déjà dans le graphe
                    if addr and addr not in visited and addr not in existing_nodes and addr != node_addr.address:
                        # Calculer un score heuristique basé sur la valeur des transactions
                        value = float(row.get('value_eth', 0))
                        if addr not in newly_discovered:
                            newly_discovered[addr] = {'addr': Address(addr), 'total_value': 0, 'tx_count': 0}
                        newly_discovered[addr]['total_value'] += value
                        newly_discovered[addr]['tx_count'] += 1

            # Ajouter toutes les transactions au graphe (même celles vers des adresses connues)
            self._add_transactions_to_graph(df)

        if not newly_discovered:
            print(f"[Expansion] No new addresses discovered from {len(nodes_to_expand)} nodes")
            return []

        print(f"[Expansion] Discovered {len(newly_discovered)} new unique addresses")

        # Trier les nouvelles adresses par valeur totale des transactions (proxy de l'importance)
        sorted_new = sorted(
            newly_discovered.values(),
            key=lambda x: (x['total_value'], x['tx_count']),
            reverse=True
        )

        # Retourner les top_n meilleures nouvelles adresses
        return [item['addr'] for item in sorted_new[:top_n]]

    def build_graph(
        self,
        address1: Address,
        address2: Address,
        expansion_depth: int = 1,
        top_n: int = 5
    ):
        """
        Construit le graphe avec expansion récursive optionnelle.

        Processus:
        1. Niveau 0: Récupère les transactions des 2 adresses principales (1 appel API)
        2. Niveau 1+: Pour chaque niveau d'expansion, sélectionne les top_n meilleurs
           candidats parmi les voisins et récupère leurs transactions

        Args:
            address1: Première adresse principale
            address2: Deuxième adresse principale
            expansion_depth: Nombre de niveaux d'expansion
                - 1: Uniquement les adresses principales (niveau 0)
                - 2: Niveau 0 + 1 niveau d'expansion (voisins des principales)
                - 3: Niveau 0 + 2 niveaux d'expansion (voisins des voisins)
            top_n: Nombre de nœuds à sélectionner par niveau d'expansion
        """
        # Clear the graph to avoid duplicating edges when build_graph is called multiple times
        self.graph.clear()

        # 1. Init main nodes
        self.graph.add_node(address1.address, type='main', label='Address 1')
        self.graph.add_node(address2.address, type='main', label='Address 2')

        # Track visited addresses to avoid cycles
        visited = {address1.address, address2.address}

        print(f"\n[Expansion] Configuration: depth={expansion_depth}, top_n={top_n}")

        # NIVEAU 0: Utiliser get_transactions pour les 2 adresses principales (1 seul appel API)
        print(f"[Expansion] Level 0 (base): Fetching transactions for main addresses...")

        df_base = self.dune_adapter.get_transactions(address1.address, address2.address, limit=5)
        self._add_transactions_to_graph(df_base)

        level0_nodes = self.graph.number_of_nodes()
        level0_edges = self.graph.number_of_edges()
        print(f"[Expansion] Level 0 complete: {level0_nodes} nodes, {level0_edges} edges")

        # NIVEAUX SUIVANTS: Expansion récursive avec get_transactions_for_address
        # expansion_depth=1 : uniquement niveau 0 (base)
        # expansion_depth=2 : niveau 0 + 1 niveau d'expansion
        # expansion_depth=3 : niveau 0 + 2 niveaux d'expansion, etc.
        if expansion_depth > 1:
            # Niveau 1 : tous les voisins directs des adresses principales
            current_level = [Address(addr) for addr in set(self.graph.nodes()) - visited]

            for depth in range(1, expansion_depth):
                print(f"\n[Expansion] Level {depth}/{expansion_depth - 1} (iteration {depth})")

                if not current_level:
                    print(f"[Expansion] No nodes to expand at this level, stopping")
                    break

                # Cette méthode va :
                # 1. Récupérer les transactions des nœuds du niveau actuel
                # 2. Découvrir les nouvelles adresses
                # 3. Retourner les top_n nouvelles adresses
                candidates = self._get_top_candidates_from_nodes(
                    current_level,
                    top_n=top_n,
                    visited=visited,
                    max_nodes_to_process=10
                )

                if not candidates:
                    print(f"[Expansion] No new candidates found, stopping expansion early")
                    break

                # Marquer les nœuds du niveau actuel comme visités (on ne les retraitera pas)
                visited.update(a.address for a in current_level)
                # Marquer aussi les nouveaux candidats comme visités
                visited.update(a.address for a in candidates)
                # Les nouveaux candidats deviennent le niveau suivant
                current_level = candidates
                print(f"[Expansion] Level complete: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

        print(f"\n[Expansion] Graph built: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")


    def visualize_graph(self, address1: Address, address2: Address):
        """
        Visualize the graph using Matplotlib.
        addr1 is fixed on the left, addr2 on the right.
        Tous les nœuds du graphe sont positionnés selon leur distance aux adresses principales.
        """
        if self.graph.number_of_nodes() == 0:
            print("Graph is empty, nothing to visualize.")
            return

        plt.figure(figsize=(16, 10))

        viz_graph = self.graph
        pos = {}

        # Positions fixes pour les adresses principales
        p1 = (-3.0, 0.0)
        p2 = (3.0, 0.0)
        pos[address1.address] = p1
        pos[address2.address] = p2

        # Calculer les distances (profondeur) depuis chaque adresse principale
        undirected = viz_graph.to_undirected()

        try:
            dist_from_1 = nx.single_source_shortest_path_length(undirected, address1.address)
        except:
            dist_from_1 = {address1.address: 0}

        try:
            dist_from_2 = nx.single_source_shortest_path_length(undirected, address2.address)
        except:
            dist_from_2 = {address2.address: 0}

        # Grouper les nœuds par profondeur minimale
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

        # Positionner les nœuds par profondeur
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

            # Rayon augmente avec la profondeur
            radius = 1.5 + (depth - 1) * 1.0

            # Positionner à gauche (proche de addr1)
            if left_nodes:
                n = len(left_nodes)
                # Arc de 90° à 270° (gauche)
                start_ang = math.pi / 2
                end_ang = 3 * math.pi / 2
                step = (end_ang - start_ang) / max(n, 1)
                for i, node in enumerate(sorted(left_nodes)):
                    ang = start_ang + i * step + step/2
                    pos[node] = (p1[0] + radius * math.cos(ang), p1[1] + radius * math.sin(ang))

            # Positionner à droite (proche de addr2)
            if right_nodes:
                n = len(right_nodes)
                # Arc de -90° à 90° (droite)
                start_ang = -math.pi / 2
                end_ang = math.pi / 2
                step = (end_ang - start_ang) / max(n, 1)
                for i, node in enumerate(sorted(right_nodes)):
                    ang = start_ang + i * step + step/2
                    pos[node] = (p2[0] + radius * math.cos(ang), p2[1] + radius * math.sin(ang))

            # Positionner au centre (distance égale)
            if center_nodes:
                n = len(center_nodes)
                h_step = 4.0 / max(n + 1, 1)
                start_y = -2.0
                for i, node in enumerate(sorted(center_nodes)):
                    pos[node] = (0, start_y + (i + 1) * h_step)

        # Fallback pour les nœuds non positionnés
        remaining = set(viz_graph.nodes()) - set(pos.keys())
        if remaining:
            sub_pos = nx.spring_layout(viz_graph.subgraph(remaining), center=(0, 0))
            pos.update(sub_pos)
        
        # 3. Draw Nodes
        node_colors = []
        node_sizes = []
        for node in viz_graph.nodes():
            if node == address1.address or node == address2.address:
                node_colors.append('#ff7f0e') # Orange
                node_sizes.append(1000)      # Bigger main nodes
            else:
                node_colors.append('#1f77b4') # Blue
                node_sizes.append(600)
                
        nx.draw_networkx_nodes(viz_graph, pos, node_color=node_colors, node_size=node_sizes, alpha=0.9, edgecolors='white', linewidths=1.5)
        
        # 4. Draw Edges with separate curves for parallel edges
        ax = plt.gca()
        
        # Group edges by (u, v)
        edge_groups = {}
        for u, v, k, data in viz_graph.edges(data=True, keys=True):
            if (u, v) not in edge_groups:
                edge_groups[(u, v)] = []
            edge_groups[(u, v)].append(data)

        # Draw each group
        for (u, v), datas in edge_groups.items():
            total = len(datas)
            for i, data in enumerate(datas):
                # Varies curvature: 0.1, 0.2, 0.3... etc
                # If there are many edges, this might get wide, but it separates them.
                rad = 0.1 + (i * 0.1)
                
                # Determine width based on value
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

                # Custom Label Placement for Curved Edges (Manual)
                val = data.get('weight', 0)
                
                # Calculate position
                x1, y1 = pos[u]
                x2, y2 = pos[v]
                
                # Midpoint of the chord
                mx = (x1 + x2) / 2
                my = (y1 + y2) / 2
                
                # Chord vector
                dx = x2 - x1
                dy = y2 - y1
                
                # The arc3 connection with positive rad bends to the RIGHT.
                # So we need the Right Normal vector to position the label on the curve.
                # Vector (dx, dy).
                # Right Normal is (dy, -dx).
                # We scale by rad * 0.5 (approximate peak of bezier with control point at distance dist*rad).
                
                lx = mx + (dy * rad * 0.5)
                ly = my - (dx * rad * 0.5)
                
                # Create label text
                label_text = f"{val:.4f}"
                
                # Draw text with a background box for readability
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

        # 5. Draw Node Labels
        labels = {}
        for node in viz_graph.nodes():
            if node == address1.address:
                labels[node] = "Addr1"
            elif node == address2.address:
                labels[node] = "Addr2"
            else:
                 labels[node] = f"{node[:4]}..{node[-3:]}"
            
        nx.draw_networkx_labels(viz_graph, pos, labels=labels, font_size=8, font_weight='bold', font_color='black')

        # 6. Draw Edge Labels
        # Note: Edge labels are now drawn individually in the loop above to correctly position them on curved edges.

        
        plt.title(f"Transaction Graph (Individual Txs)", fontsize=14)
        plt.axis('off')
        plt.show()

    def _get_transaction_metrics(self, addr1: str, addr2: str) -> Optional[dict]:
        """Extract transaction metrics between two addresses from the graph.

        Checks for edges in both directions (addr1->addr2 and addr2->addr1)
        since transactions can flow either way.
        """
        # Get edges in both directions
        edges_forward = self.graph.get_edge_data(addr1, addr2, default={})
        edges_backward = self.graph.get_edge_data(addr2, addr1, default={})

        # Combine all edge data
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
        """Calculate recency score based on transaction timestamps.
        More recent transactions get higher scores."""
        if not timestamps:
            return 0.5  # Neutral score if no timestamps

        try:
            # Convert to datetime objects if needed
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

            # Calculate average days since transactions
            now = datetime.now()
            days_ago = [(now - d).days for d in dates]
            avg_days = sum(days_ago) / len(days_ago)

            # Score: 1.0 for today, decreasing to 0.0 for transactions > 1 year ago
            score = max(0.0, 1.0 - (avg_days / 365))
            return score
        except Exception:
            return 0.5

    def _calculate_direct_score(self, addr1: Address, addr2: Address) -> Tuple[float, dict]:
        """Calculate direct relationship score based on transactions."""
        metrics = self._get_transaction_metrics(addr1.address, addr2.address)

        if not metrics:
            return 0.0, {}

        # Volume score: log scale to handle extreme values, capped at 1.0
        # Assuming 1000 ETH as max reference for full score
        volume_score = min(math.log10(metrics['total_volume'] + 1) / 3, 1.0)

        # Frequency score: capped at 10 transactions for full score
        freq_score = min(metrics['tx_count'] / 10, 1.0)

        # Recency score: based on how recent transactions are
        recency_score = self._calculate_recency_score(metrics['timestamps'])

        # Weighted combination: volume is most important, then frequency, then recency
        total = (0.5 * volume_score + 0.3 * freq_score + 0.2 * recency_score) * 100

        return total, metrics

    def _calculate_indirect_score(self, addr1: Address, addr2: Address, max_depth: int = 3) -> Tuple[float, List[PathInfo]]:
        """Calculate indirect relationship score via intermediate nodes."""
        paths = []
        total_score = 0.0

        try:
            # Find all simple paths up to max_depth
            for path in nx.all_simple_paths(self.graph, addr1.address, addr2.address, cutoff=max_depth):
                if len(path) <= 2:  # Skip direct path (already counted)
                    continue

                # Calculate path score
                path_score = 1.0
                decay = 0.5 ** (len(path) - 2)  # Decay factor per hop

                # Multiply scores for each edge in the path
                for i in range(len(path) - 1):
                    edge_metrics = self._get_transaction_metrics(path[i], path[i+1])
                    if edge_metrics:
                        edge_score = min(math.log10(edge_metrics['total_volume'] + 1) / 3, 1.0)
                        path_score *= edge_score
                    else:
                        path_score *= 0.1  # Small penalty for edges without data

                path_score *= decay * 100
                total_score += path_score

                paths.append(PathInfo(
                    nodes=[Address(a) for a in path],
                    score=path_score,
                    depth=len(path) - 1
                ))
        except nx.NetworkXNoPath:
            pass

        # Also check reverse direction
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

    def calculate_relationship_scores(self, main_address: Address) -> AddressRelationshipTable:
        """Generate relationship score table for a main address."""
        relationships = {}

        # Get all nodes in the graph
        connected_nodes = set(self.graph.nodes())

        for node_address in connected_nodes:
            if node_address == main_address.address:
                continue

            target = Address(node_address)

            # Calculate direct and indirect scores
            direct_score, direct_metrics = self._calculate_direct_score(main_address, target)
            indirect_score, indirect_paths = self._calculate_indirect_score(main_address, target)

            # Total score is the maximum of both (they represent different relationship types)
            total_score = max(direct_score, indirect_score)

            relationships[node_address] = RelationshipScore(
                source=main_address,
                target=target,
                direct_score=direct_score,
                indirect_score=indirect_score,
                total_score=total_score,
                metrics={
                    **direct_metrics,
                    'indirect_paths': indirect_paths
                }
            )

        return AddressRelationshipTable(
            main_address=main_address,
            relationships=relationships
        )

    def calculate_score(
        self,
        address1: Address,
        address2: Address,
        expansion_depth: int = 1,
        top_n: int = 5
    ) -> CorrelationResult:
        """
        Calculate correlation score between two addresses with optional graph expansion.

        Args:
            address1: First main address
            address2: Second main address
            expansion_depth: Number of expansion iterations (1 = no expansion)
            top_n: Number of top correlated nodes to expand per iteration
        """
        # 1. Build Graph with expansion
        self.build_graph(address1, address2, expansion_depth=expansion_depth, top_n=top_n)

        # 2. Calculate relationship scores
        table = self.calculate_relationship_scores(address1)
        relationship = table.get_relationship(address2)

        # 3. Analyze Graph
        num_nodes = self.graph.number_of_nodes()
        num_edges = self.graph.number_of_edges()
        has_path = nx.has_path(self.graph, address1.address, address2.address) or nx.has_path(self.graph, address2.address, address1.address)

        # 4. Return Result with actual score
        score = relationship.total_score if relationship else 0.0

        return CorrelationResult(
            source=address1,
            target=address2,
            score=score,
            path=[address1, address2] if relationship else [],
            details={
                "nodes": num_nodes,
                "edges": num_edges,
                "notes": f"Graph built with expansion_depth={expansion_depth}, top_n={top_n}",
                "has_path": has_path,
                "direct_score": relationship.direct_score if relationship else 0.0,
                "indirect_score": relationship.indirect_score if relationship else 0.0,
                "tx_count": relationship.metrics.get('tx_count', 0) if relationship else 0,
                "total_volume": relationship.metrics.get('total_volume', 0) if relationship else 0,
                "expansion_depth": expansion_depth,
                "top_n": top_n,
            }
        )

    def visualize_interactive(
        self,
        address1: Address,
        address2: Address,
        tables: Optional[List[AddressRelationshipTable]] = None,
        auto_open: bool = True
    ) -> str:
        """Crée une visualisation HTML interactive du graphe.

        Args:
            address1: Première adresse principale
            address2: Deuxième adresse principale
            tables: Tables de relation pour enrichir les scores (optionnel)
            auto_open: Si True, ouvre le fichier dans le navigateur

        Returns:
            Chemin du fichier HTML généré
        """
        if self.graph.number_of_nodes() == 0:
            self.build_graph(address1, address2)

        visualizer = InteractiveGraphVisualizer()
        if tables:
            visualizer.set_relationship_tables(tables)

        return visualizer.visualize(
            graph=self.graph,
            main_addresses=[address1, address2],
            title=f"Ethereum Correlation: {address1.address[:10]}... vs {address2.address[:10]}...",
            auto_open=auto_open
        )
