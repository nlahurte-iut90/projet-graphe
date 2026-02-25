import networkx as nx
import matplotlib.pyplot as plt
from src.domain.models import Address, CorrelationResult
from src.adapters.dune import DuneAdapter
import pandas as pd

class CorrelationService:
    def __init__(self, dune_adapter: DuneAdapter):
        self.dune_adapter = dune_adapter
        self.graph = nx.MultiDiGraph()

    def build_graph(self, address1: Address, address2: Address):
        """
        Fetch data and build the graph around the two addresses.
        """
        # 1. Init main nodes
        self.graph.add_node(address1.address, type='main', label='Address 1')
        self.graph.add_node(address2.address, type='main', label='Address 2')

        # 2. Fetch data (limit per address handled in adapter query)
        # We assume address is a string in Address object
        df = self.dune_adapter.get_transactions(address1.address, address2.address, limit=5)
        
        if df.empty:
            print("No transactions found.")
            return

        # 3. Iterate and build graph
        for _, row in df.iterrows():
            sender = str(row['from']).strip().lower()
            receiver = str(row['to']).strip().lower()

            if not sender or not receiver:
                continue

            tx_hash = row.get('hash', 'unknown')
            value = float(row['value_eth'])
            timestamp = row.get('block_time', 'unknown')
            
            # Avoid self-transactions if deemed irrelevant (or keep them)
            # The user said "code doesn't support" it. 
            # If sender == receiver, we add a self-loop.
            
            # To prevent double addition (if transaction is between addr1 and addr2),
            # we track processed hashes or handle logic carefully.
            # But simpler: Just add the edge based on raw data.
            # We must ensure we don't add it twice because of the "Case A / Case B" if blocks.
            
            added = False
            
            # Interaction involving Address 1
            if sender == address1.address or receiver == address1.address:
                # Ensure nodes exist
                self.graph.add_node(sender)
                self.graph.add_node(receiver)
                self.graph.add_edge(sender, receiver, weight=value, hash=tx_hash, time=timestamp)
                added = True
            
            # Interaction involving Address 2 (only if not already added by Address 1 block)
            if not added and (sender == address2.address or receiver == address2.address):
                self.graph.add_node(sender)
                self.graph.add_node(receiver)
                self.graph.add_edge(sender, receiver, weight=value, hash=tx_hash, time=timestamp)


    def visualize_graph(self, address1: Address, address2: Address):
        """
        Visualize the graph using Matplotlib.
        addr1 is fixed on the left, addr2 on the right.
        """
        if self.graph.number_of_nodes() == 0:
            print("Graph is empty, nothing to visualize.")
            return

        plt.figure(figsize=(14, 9))
        
        # Use the MultiDiGraph directly
        viz_graph = self.graph

        # 1. Compute Layout - Custom Split Cluster
        import math
        
        pos = {}
        
        # Centers
        p1 = (-2.0, 0.0)
        p2 = (2.0, 0.0)
        pos[address1.address] = p1
        pos[address2.address] = p2
        
        # Identify neighbors
        # We need to know who is connected to whom in the simplified graph
        # But we can check edge existence in the main graph or viz_graph
        neighbors1 = set(viz_graph.successors(address1.address)) | set(viz_graph.predecessors(address1.address))
        neighbors2 = set(viz_graph.successors(address2.address)) | set(viz_graph.predecessors(address2.address))
        
        # Exclude the main nodes themselves from neighbor sets if present
        neighbors1.discard(address1.address)
        neighbors1.discard(address2.address)
        neighbors2.discard(address1.address)
        neighbors2.discard(address2.address)
        
        common = neighbors1.intersection(neighbors2)
        unique1 = neighbors1 - common
        unique2 = neighbors2 - common
        
        # Helper to arrange nodes in a circle
        def arrange_circle(nodes, center, radius, start_angle=0, end_angle=2*math.pi):
            sorted_nodes = sorted(list(nodes)) # Sort for deterministic layout
            count = len(sorted_nodes)
            if count == 0: return
            step = (end_angle - start_angle) / count
            for i, node in enumerate(sorted_nodes):
                angle = start_angle + i * step
                x = center[0] + radius * math.cos(angle)
                y = center[1] + radius * math.sin(angle)
                pos[node] = (x, y)

        # Arrange Left Cluster (Addr1) - Fan out to the left
        # Angles from pi/2 to 3pi/2 (90 to 270 degrees) to face away from center
        arrange_circle(unique1, p1, radius=1.0, start_angle=math.pi/2, end_angle=2.5*math.pi)
        
        # Arrange Right Cluster (Addr2) - Fan out to the right
        # Angles from -pi/2 to pi/2 (-90 to 90 degrees)
        arrange_circle(unique2, p2, radius=1.0, start_angle=-math.pi/2, end_angle=1.5*math.pi)
        
        # Arrange Common Nodes - In the middle
        if common:
            # Spread vertically at x=0
            sorted_common = sorted(list(common))
            h_step = 4.0 / (len(sorted_common) + 1)
            start_y = -2.0
            for i, node in enumerate(sorted_common):
                pos[node] = (0, start_y + (i + 1) * h_step)
        
        # Handle any outliers (connected to neighbors but not main nodes directly? 
        # In this dataset, unlikely, but fallback to prevent crash)
        remaining = set(viz_graph.nodes()) - set(pos.keys())
        if remaining:
             # Just place them arbitrarily or use spring for them
             sub_pos = nx.spring_layout(viz_graph.subgraph(remaining), center=(0,0))
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

    def calculate_score(self, address1: Address, address2: Address) -> CorrelationResult:
        # 1. Build Graph
        self.build_graph(address1, address2)
        
        # 2. Analyze Graph
        num_nodes = self.graph.number_of_nodes()
        num_edges = self.graph.number_of_edges()
        has_path = nx.has_path(self.graph, address1.address, address2.address) or nx.has_path(self.graph, address2.address, address1.address)

        # 3. Return Result
        return CorrelationResult(
            source=address1,
            target=address2,
            score=0.0, # Placeholder
            details={
                "nodes": num_nodes,
                "edges": num_edges,
                "notes": "Graph built successfully",
                "has_path": has_path
            } 
        )
