"""Visualisation interactive des graphes de corrélation Ethereum avec Pyvis."""
import math
import json
import html
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import networkx as nx
from pyvis.network import Network

from src.domain.models import Address, AddressRelationshipTable
from src.infrastructure.price_service import get_price_service


class InteractiveGraphVisualizer:
    """Crée des visualisations interactives HTML du graphe de corrélation."""

    SCORE_COLORS = {
        "high": "#28a745",
        "medium": "#ffc107",
        "low": "#fd7e14",
        "very_low": "#dc3545",
        "none": "#6c757d",
    }

    MAIN_NODE_COLOR = "#ff7f0e"
    DEFAULT_EDGE_COLOR = "#666666"
    HIGHLIGHT_EDGE_COLOR = "#ff7f0e"

    def __init__(self, output_dir: str = "output"):
        self.base_output_dir = Path(output_dir)
        self.base_output_dir.mkdir(exist_ok=True)
        self.output_dir: Optional[Path] = None  # Sera défini à chaque visualize()
        self.tables: Dict[str, AddressRelationshipTable] = {}
        self.price_service = get_price_service()

    def set_relationship_tables(self, tables: List[AddressRelationshipTable]):
        """Configure les tables de relation."""
        for table in tables:
            self.tables[table.main_address.address] = table

    def _get_score_color(self, score: float) -> str:
        """Retourne la couleur selon le score."""
        if score >= 80:
            return self.SCORE_COLORS["high"]
        elif score >= 50:
            return self.SCORE_COLORS["medium"]
        elif score >= 20:
            return self.SCORE_COLORS["low"]
        elif score > 0:
            return self.SCORE_COLORS["very_low"]
        return self.SCORE_COLORS["none"]

    def _build_node_tooltip(
        self,
        node_id: str,
        is_main: bool,
        tx_count: int,
        total_volume: float,
        relationship_scores: Dict[str, float],
        main_addresses: List[Address],
        relationship_details: Optional[Dict[str, Dict]] = None
    ) -> str:
        """Construit le tooltip pour un nœud avec les dimensions temporelles."""
        # Volume en EUR
        volume_eur = self.price_service.eth_to_eur(total_volume)
        if volume_eur is not None:
            if volume_eur >= 1000:
                volume_eur_str = f"{volume_eur:,.0f} €".replace(",", " ")
            else:
                volume_eur_str = f"{volume_eur:.2f} €"
            volume_str = f"{total_volume:.4f} ETH (~{volume_eur_str})"
        else:
            volume_str = f"{total_volume:.4f} ETH"

        lines = [
            f"Address: {node_id}",
            f"Type: {'MAIN' if is_main else 'CONNECTED'}",
            f"Transactions: {tx_count}",
            f"Volume: {volume_str}",
            "",
            "Relationship Scores (Temporal):",
        ]

        for main_addr in main_addresses:
            score = relationship_scores.get(main_addr.address, 0)
            short = f"{main_addr.address[:10]}..."
            lines.append(f"  {short}: {score:.1f}")

        if is_main:
            lines.append("")
            lines.append("Click to color connections")

        return "\n".join(lines)

    def _build_edge_tooltip(self, tx_hash: str, value: float, value_wei: int, timestamp: str) -> str:
        """Construit le tooltip pour une transaction avec conversion EUR."""
        # Conversion EUR
        value_eur = self.price_service.eth_to_eur(value)
        if value_eur is not None:
            if value_eur >= 1000:
                eur_str = f"{value_eur:,.0f} €".replace(",", " ")
            elif value_eur >= 1:
                eur_str = f"{value_eur:.2f} €"
            else:
                eur_str = f"{value_eur:.4f} €"
            value_str = f"{value:.6f} ETH (~{eur_str})"
        else:
            value_str = f"{value:.6f} ETH"

        return f"""Transaction
Hash: {tx_hash}
Value: {value_str}
Wei: {value_wei:,}
Time: {timestamp}"""

    def _build_node_data(self, graph: nx.MultiDiGraph, main_addresses: List[Address]) -> Tuple[List[Dict], Dict]:
        """Extrait les données des nœuds avec calcul correct des distances (profondeur)."""
        nodes = []
        nodes_js_data = {}
        main_addrs = {a.address for a in main_addresses}

        # Pré-calculer toutes les distances depuis chaque nœud principal
        # distances_from_main[main_addr][node_id] = distance en nombre de sauts
        # On utilise le graphe non orienté pour calculer les distances de connexion
        distances_from_main = {}
        undirected_graph = graph.to_undirected()
        for main_addr in main_addresses:
            # Distance 0 pour le nœud principal lui-même
            distances = {main_addr.address: 0}
            # BFS sur le graphe non orienté pour trouver toutes les distances
            # Cela compte le nombre de sauts peu importe la direction des transactions
            for target, dist in nx.single_source_shortest_path_length(undirected_graph, main_addr.address).items():
                distances[target] = dist
            distances_from_main[main_addr.address] = distances

        for node_id in graph.nodes():
            is_main = node_id in main_addrs

            # Métriques
            tx_count = 0
            total_volume = 0.0
            in_edges = list(graph.in_edges(node_id, data=True))
            out_edges = list(graph.out_edges(node_id, data=True))
            for _, _, data in in_edges:
                total_volume += data.get('weight', 0)
                tx_count += 1
            for _, _, data in out_edges:
                total_volume += data.get('weight', 0)
                tx_count += 1

            # Scores et détails - pour chaque nœud, stocker le score de relation avec chaque adresse principale
            relationship_scores = {}
            relationship_details = {}
            for main_addr in main_addresses:
                score = 0.0
                details = {}
                if main_addr.address in self.tables:
                    table = self.tables[main_addr.address]
                    rel = table.get_relationship(Address(node_id))
                    if rel:
                        score = rel.total_score
                        details = {
                            'direct_score': rel.direct_score,
                            'indirect_score': rel.indirect_score,
                            'confidence': rel.confidence,
                            'score_breakdown': rel.metrics.get('score_breakdown', {})
                        }
                relationship_scores[main_addr.address] = score
                relationship_details[main_addr.address] = details

            # Couleur selon le score le plus élevé
            if is_main:
                color = self.MAIN_NODE_COLOR
            else:
                max_score = max(relationship_scores.values()) if relationship_scores else 0
                color = self._get_score_color(max_score)

            # Label
            if is_main:
                idx = list(main_addrs).index(node_id)
                label = f"Addr{idx + 1}"
            else:
                label = f"{node_id[:6]}...{node_id[-4:]}"

            # Tooltip avec dimensions temporelles
            title = self._build_node_tooltip(
                node_id, is_main, tx_count, total_volume,
                relationship_scores, main_addresses, relationship_details
            )

            nodes.append({
                'id': node_id,
                'label': label,
                'title': title,
                'color': {
                    'background': color,
                    'border': '#333' if is_main else '#666',
                    'highlight': {'background': color, 'border': '#000'}
                },
                'size': 35 if is_main else 20,
                'shape': 'box' if is_main else 'dot',
                'font': {'size': 14, 'color': '#ffffff' if is_main else '#333333', 'face': 'monospace'},
                'borderWidth': 3 if is_main else 2,
            })

            # Construire le dictionnaire des distances pour ce nœud
            node_distances = {}
            for main_addr in main_addresses:
                dist_map = distances_from_main.get(main_addr.address, {})
                node_distances[main_addr.address] = dist_map.get(node_id, -1)

            nodes_js_data[node_id] = {
                'is_main': is_main,
                'relationship_scores': relationship_scores,
                'tx_count': tx_count,
                'total_volume': total_volume,
                'color': color,
                'distances': node_distances
            }

        return nodes, nodes_js_data

    def _build_edge_data(self, graph: nx.MultiDiGraph) -> List[Dict]:
        """Extrait les données des arcs."""
        edges = []

        edge_groups = {}
        for u, v, k, data in graph.edges(data=True, keys=True):
            key = (u, v)
            if key not in edge_groups:
                edge_groups[key] = []
            edge_groups[key].append((k, data))

        for (u, v), edge_list in edge_groups.items():
            total = len(edge_list)
            for idx, (key, data) in enumerate(edge_list):
                tx_hash = str(data.get('hash', 'unknown'))
                value = float(data.get('weight', 0))
                value_wei = int(data.get('weight_wei', value * 1e18))
                timestamp = data.get('time', 'unknown')
                if isinstance(timestamp, datetime):
                    timestamp = timestamp.strftime('%Y-%m-%d %H:%M')

                roundness = 0.2 * idx if total > 1 else 0
                width = 2 + min(value / 3, 4)

                title = self._build_edge_tooltip(tx_hash, value, value_wei, str(timestamp))

                edges.append({
                    'from': u,
                    'to': v,
                    'width': width,
                    'title': title,
                    'color': {'color': self.DEFAULT_EDGE_COLOR, 'highlight': self.HIGHLIGHT_EDGE_COLOR},
                    'arrows': {'to': {'enabled': True, 'scaleFactor': 0.7}},
                    'smooth': {'type': 'continuous' if roundness == 0 else 'curvedCW', 'roundness': roundness}
                })

        return edges

    def _calculate_positions(
        self,
        graph: nx.MultiDiGraph,
        main_addresses: List[Address]
    ) -> Dict[str, Tuple[int, int]]:
        """Calcule les positions des nœuds selon leur profondeur (distance aux adresses principales)."""
        positions = {}
        if len(main_addresses) < 1:
            return positions

        screen_half_width = 800
        addr1 = main_addresses[0].address
        addr2 = main_addresses[1].address if len(main_addresses) > 1 else None

        # Positionner les adresses principales aux extrémités
        positions[addr1] = (-screen_half_width, 0)
        if addr2:
            positions[addr2] = (screen_half_width, 0)

        # Calculer les distances depuis chaque adresse principale
        undirected_graph = graph.to_undirected()

        try:
            dist_from_1 = nx.single_source_shortest_path_length(undirected_graph, addr1)
        except:
            dist_from_1 = {addr1: 0}

        dist_from_2 = {}
        if addr2:
            try:
                dist_from_2 = nx.single_source_shortest_path_length(undirected_graph, addr2)
            except:
                dist_from_2 = {addr2: 0}

        # Grouper les nœuds par profondeur minimale
        depth_groups: Dict[int, List[Tuple[str, int, int]]] = {}
        max_depth = 0

        for node in graph.nodes():
            if node == addr1 or node == addr2:
                continue

            d1 = dist_from_1.get(node, float('inf'))
            d2 = dist_from_2.get(node, float('inf')) if addr2 else float('inf')
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
            radius = 400 + (depth - 1) * 250

            # Positionner à gauche (proche de addr1)
            if left_nodes:
                n = len(left_nodes)
                # Arc de 120° à 240° (gauche)
                start_ang = 2 * math.pi / 3
                end_ang = 4 * math.pi / 3
                step = (end_ang - start_ang) / max(n, 1)
                for i, node in enumerate(sorted(left_nodes)):
                    ang = start_ang + i * step + step/2
                    x = -screen_half_width + int(radius * math.cos(ang))
                    y = int(radius * math.sin(ang))
                    positions[node] = (x, y)

            # Positionner à droite (proche de addr2)
            if right_nodes:
                n = len(right_nodes)
                # Arc de -60° à 60° (droite)
                start_ang = -math.pi / 3
                end_ang = math.pi / 3
                step = (end_ang - start_ang) / max(n, 1)
                for i, node in enumerate(sorted(right_nodes)):
                    ang = start_ang + i * step + step/2
                    x = screen_half_width + int(radius * math.cos(ang))
                    y = int(radius * math.sin(ang))
                    positions[node] = (x, y)

            # Positionner au centre (distance égale)
            if center_nodes:
                n = len(center_nodes)
                h_step = 300 / max(n + 1, 1)
                start_y = -150
                for i, node in enumerate(sorted(center_nodes)):
                    positions[node] = (0, int(start_y + (i + 1) * h_step))

        # Fallback pour les nœuds non positionnés
        remaining = set(graph.nodes()) - set(positions.keys())
        if remaining:
            n_rem = len(remaining)
            for i, node in enumerate(sorted(list(remaining))):
                ang = 2 * math.pi * i / max(n_rem, 1)
                positions[node] = (int(800 * math.cos(ang)), int(800 * math.sin(ang)))

        return positions

    def _get_custom_js(self, nodes_js_data: Dict) -> str:
        """Génère le JavaScript pour les interactions avec le système de profondeur corrigé."""
        nodes_json = json.dumps(nodes_js_data)

        return f"""
const nodeDataMap = {nodes_json};

function getNodeData(id) {{
    return nodeDataMap[id] || {{}};
}}

function getScoreColor(score) {{
    if (score >= 80) return '{self.SCORE_COLORS["high"]}';
    if (score >= 50) return '{self.SCORE_COLORS["medium"]}';
    if (score >= 20) return '{self.SCORE_COLORS["low"]}';
    if (score > 0) return '{self.SCORE_COLORS["very_low"]}';
    return '{self.SCORE_COLORS["none"]}';
}}

// Variable globale pour la profondeur sélectionnée
let currentDepth = 'all';

// Variable pour tracker le dernier nœud principal cliqué
let lastSelectedMainNode = null;

/**
 * Vérifie si un nœud est visible à une certaine profondeur depuis un nœud principal.
 * Cette fonction est utilisée pour les nœuds secondaires UNIQUEMENT.
 * @param nodeId - L'ID du nœud à vérifier
 * @param mainNodeId - L'ID du nœud principal de référence
 * @param maxDepth - La profondeur max ('all' ou nombre)
 * @returns true si le nœud doit être visible
 */
function isNodeVisibleAtDepth(nodeId, mainNodeId, maxDepth) {{
    // Mode "all" : tout est visible
    if (maxDepth === 'all') return true;

    const nodeData = getNodeData(nodeId);
    if (!nodeData) return false;

    const maxD = parseInt(maxDepth);
    const distances = nodeData.distances || {{}};

    // Si un nœud principal spécifique est sélectionné
    if (mainNodeId) {{
        const dist = distances[mainNodeId];
        // Distance -1 = pas de chemin, donc caché
        if (dist === undefined || dist < 0) return false;
        // Visible si distance <= maxDepth
        // Note: dist 0 = le nœud principal lui-même, dist 1 = voisins directs, etc.
        return dist <= maxD;
    }}

    // Sinon (mode reset), visible si connecté à AU MOINS un nœud principal dans la limite
    return Object.values(distances).some(d => d >= 0 && d <= maxD);
}}

/**
 * Met à jour les couleurs des nœuds connectés à un nœud principal spécifique.
 * Les nœuds sont colorés selon leur score de relation et filtrés par profondeur.
 * Quand un nœud principal est sélectionné, il devient le centre et les autres nœuds principaux
 * sont traités comme des nœuds normaux (filtrés par profondeur).
 */
function colorConnectedNodes(mainNodeId) {{
    const nodeUpdates = [];
    const edgeUpdates = [];

    // D'abord, déterminer quels nœuds sont visibles selon la profondeur
    const visibleNodes = new Set();
    const allNodes = network.body.data.nodes.get();

    allNodes.forEach(function(node) {{
        const nodeData = getNodeData(node.id);
        if (!nodeData) return;

        // Le nœud principal sélectionné est toujours visible
        if (node.id === mainNodeId) {{
            visibleNodes.add(node.id);
            return;
        }}

        // Pour tous les autres nœuds (y compris les autres nœuds principaux),
        // vérifier s'ils sont dans la profondeur définie
        if (isNodeVisibleAtDepth(node.id, mainNodeId, currentDepth)) {{
            visibleNodes.add(node.id);
        }}
    }});

    // Mettre à jour les nœuds avec les couleurs appropriées
    allNodes.forEach(function(node) {{
        const nodeData = getNodeData(node.id);
        if (!nodeData) return;

        const isVisible = visibleNodes.has(node.id);

        if (!isVisible) {{
            // Nœud hors profondeur - cacher
            nodeUpdates.push({{
                id: node.id,
                hidden: true
            }});
            return;
        }}

        // Nœud visible - déterminer la couleur
        if (node.id === mainNodeId) {{
            // Nœud principal sélectionné - couleur principale
            nodeUpdates.push({{
                id: node.id,
                color: {{ background: '{self.MAIN_NODE_COLOR}', border: '#333' }},
                hidden: false
            }});
        }} else if (nodeData.is_main) {{
            // Autre nœud principal visible (dans la profondeur) - couleur secondaire spéciale
            nodeUpdates.push({{
                id: node.id,
                color: {{ background: '#ffaa44', border: '#333' }},  // Orange plus clair
                hidden: false
            }});
        }} else {{
            // Nœud secondaire - couleur selon le score de relation
            const scores = nodeData.relationship_scores || {{}};
            const score = scores[mainNodeId] || 0;
            const color = score > 0 ? getScoreColor(score) : '{self.SCORE_COLORS["none"]}';
            nodeUpdates.push({{
                id: node.id,
                color: {{ background: color, border: '#333' }},
                hidden: false
            }});
        }}
    }});

    // Mettre à jour les arcs - un arc est visible seulement si les deux extrémités sont visibles
    const allEdges = network.body.data.edges.get();
    allEdges.forEach(function(edge) {{
        const fromVisible = visibleNodes.has(edge.from);
        const toVisible = visibleNodes.has(edge.to);

        edgeUpdates.push({{
            id: edge.id,
            hidden: !(fromVisible && toVisible)
        }});
    }});

    if (nodeUpdates.length > 0) network.body.data.nodes.update(nodeUpdates);
    if (edgeUpdates.length > 0) network.body.data.edges.update(edgeUpdates);
}}

/**
 * Réinitialise les couleurs et affiche tous les nœuds selon la profondeur actuelle.
 * En mode reset : tous les nœuds principaux sont visibles, les secondaires sont filtrés par profondeur.
 */
function resetNodeColors() {{
    const nodeUpdates = [];
    const edgeUpdates = [];

    // D'abord, déterminer quels nœuds sont visibles
    const visibleNodes = new Set();
    const allNodes = network.body.data.nodes.get();

    allNodes.forEach(function(node) {{
        const data = getNodeData(node.id);
        if (!data) return;

        // Tous les nœuds principaux sont toujours visibles en mode reset
        if (data.is_main) {{
            visibleNodes.add(node.id);
            return;
        }}

        // Pour les nœuds secondaires, vérifier la profondeur (depuis n'importe quel main)
        if (isNodeVisibleAtDepth(node.id, null, currentDepth)) {{
            visibleNodes.add(node.id);
        }}
    }});

    // Mettre à jour les nœuds
    allNodes.forEach(function(node) {{
        const data = getNodeData(node.id);
        if (!data) return;

        const isVisible = visibleNodes.has(node.id);

        if (data.is_main) {{
            // Nœuds principaux - toujours visibles avec leur couleur
            nodeUpdates.push({{
                id: node.id,
                color: {{ background: '{self.MAIN_NODE_COLOR}', border: '#333' }},
                hidden: false
            }});
        }} else {{
            // Nœuds secondaires - gris si visible, caché sinon
            nodeUpdates.push({{
                id: node.id,
                color: {{ background: '{self.SCORE_COLORS["none"]}', border: '#666' }},
                hidden: !isVisible
            }});
        }}
    }});

    // Mettre à jour les arcs selon la visibilité des nœuds
    const allEdges = network.body.data.edges.get();
    allEdges.forEach(function(edge) {{
        const fromVisible = visibleNodes.has(edge.from);
        const toVisible = visibleNodes.has(edge.to);

        edgeUpdates.push({{
            id: edge.id,
            hidden: !(fromVisible && toVisible)
        }});
    }});

    network.body.data.nodes.update(nodeUpdates);
    network.body.data.edges.update(edgeUpdates);

    // Forcer le redessin
    network.redraw();
}}

function showToast(msg, type) {{
    const t = document.createElement('div');
    t.style.cssText = 'position:fixed;top:24px;right:24px;padding:14px 24px;font-family:"SF Mono",Monaco,"Cascadia Code",monospace;font-size:11px;font-weight:400;z-index:10000;letter-spacing:0.04em;text-transform:uppercase;' +
        'box-shadow:0 8px 32px rgba(0,0,0,0.08);backdrop-filter:blur(12px);background:rgba(255,255,255,0.96);color:#000;border:1px solid #000;' +
        'transition:all 0.3s cubic-bezier(0.4,0,0.2,1);';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function() {{ t.style.opacity = '0'; t.style.transform = 'translateY(-8px)'; }}, 2200);
    setTimeout(function() {{ t.remove(); }}, 2500);
}}

/**
 * Fonction appelée quand on change la profondeur dans l'input.
 */
function updateDepthFilter() {{
    const input = document.getElementById('depthSelector');
    if (input) {{
        const value = input.value.trim();
        const numValue = parseInt(value, 10);

        // Si vide ou invalide, utiliser 'all', sinon utiliser la valeur numérique
        if (value === '' || isNaN(numValue) || numValue < 1) {{
            currentDepth = 'all';
        }} else {{
            currentDepth = Math.min(numValue, 10); // Max 10
        }}

        // Mettre à jour le label affichant la profondeur actuelle
        const depthLabel = document.getElementById('depthLabel');
        if (depthLabel) {{
            depthLabel.textContent = currentDepth === 'all' ? 'All depths' : currentDepth + ' hop(s)';
        }}

        // Si un nœud principal est sélectionné, rafraîchir l'affichage avec ce nœud
        if (lastSelectedMainNode) {{
            colorConnectedNodes(lastSelectedMainNode);
        }} else {{
            resetNodeColors();
        }}
    }}
}}

// Event handlers
network.on("click", function(params) {{
    if (params.nodes.length > 0) {{
        const nodeId = params.nodes[0];
        const nodeData = getNodeData(nodeId);
        if (nodeData && nodeData.is_main) {{
            // Si on clique sur un nœud principal, colorer selon ce nœud
            if (lastSelectedMainNode !== nodeId) {{
                lastSelectedMainNode = nodeId;
                colorConnectedNodes(nodeId);
                showToast("Colored by: " + nodeId.slice(0, 10) + "...", "success");
            }}
        }}
    }} else if (params.nodes.length === 0 && params.edges.length === 0) {{
        // Reset seulement si on clique sur le fond (pas sur une arête)
        if (lastSelectedMainNode) {{
            lastSelectedMainNode = null;
            resetNodeColors();
            showToast("View reset", "info");
        }}
    }}
}});

network.on("hoverNode", function() {{ document.body.style.cursor = 'pointer'; }});
network.on("blurNode", function() {{ document.body.style.cursor = 'default'; }});

// Fit all nodes after stabilization
network.once("stabilizationIterationsDone", function() {{
    network.fit({{
        animation: {{ duration: 500, easingFunction: 'easeInOutQuad' }}
    }});
}});
"""

    def _generate_legend_html(self, global_score: Optional[float] = None) -> str:
        """Génère la légende HTML avec style monochrome institutionnel."""
        # Score global avec style sobre
        global_score_html = ""
        if global_score is not None:
            global_score_html = f"""
            <div style="margin-bottom:20px;padding:16px 12px;border:1px solid #000;text-align:center;background:#fff;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.12em;font-weight:500;">Correlation Score</div>
                <div style="font-size:32px;font-weight:300;color:#000;margin:8px 0;letter-spacing:-0.02em;font-family:SF Mono,Monaco,monospace;">{global_score:.1f}</div>
            </div>
            """

        depth_selector = """
            <div style="margin-top:16px;padding-top:16px;border-top:1px solid #e0e0e0;">
                <div style="font-size:10px;font-weight:500;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.08em;color:#333;">Depth (hops)</div>
                <input type="number" id="depthSelector" min="1" max="10" value="" placeholder="All" oninput="updateDepthFilter()" style="width:100%;padding:8px 10px;font-size:11px;border:1px solid #000;border-radius:0;background:#fff;font-family:inherit;box-sizing:border-box;">
                <div id="depthInfo" style="margin-top:8px;font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.04em;">
                    <span id="depthLabel">All depths</span>
                </div>
            </div>
        """

        instructions = """
            <div style="margin-top:14px;padding-top:14px;border-top:1px solid #e0e0e0;font-size:9px;color:#444;line-height:1.6;letter-spacing:0.01em;">
                <span style="color:#000;font-weight:500;">Click main node</span> — Filter connections<br>
                <span style="color:#000;font-weight:500;">Click background</span> — Reset view
            </div>
        """

        return f"""<div style="position:absolute;top:20px;left:20px;background:#fafafa;padding:20px;border:1px solid #000;box-shadow:8px 8px 0 rgba(0,0,0,0.08);font-family:SF Mono,Monaco,Cascadia Code,monospace;z-index:1000;max-width:220px;">
            {global_score_html}
            {depth_selector}
            {instructions}
        </div>"""

    def _generate_graph_analysis_html(self, graph_analysis: Dict[str, Any]) -> str:
        """Génère le panneau HTML avec style monochrome institutionnel."""
        connectivity = graph_analysis.get('connectivity', {})
        centrality = graph_analysis.get('centrality', {})
        communities = graph_analysis.get('communities', {})

        html_parts = []

        # Section Connectivité
        if connectivity:
            scc_count = connectivity.get('scc_count', 0)
            largest_scc = connectivity.get('largest_scc_size', 0)
            wcc_count = connectivity.get('wcc_count', 0)
            art_count = connectivity.get('articulation_count', 0)

            art_points = connectivity.get('articulation_points', [])[:2]
            art_html = ""
            if art_points:
                art_list = ", ".join([f"{ap[:6]}.." for ap in art_points])
                art_html = f'<div style="font-size:9px;color:#555;margin-top:6px;letter-spacing:0.02em;">{art_list}</div>'

            html_parts.append(f"""
            <div style="margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid #e0e0e0;">
                <div style="font-size:9px;font-weight:500;color:#000;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.1em;">
                    Connectivité
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:10px;">
                    <div><span style="color:#666;">SCCs</span> <b style="color:#000;">{scc_count}</b></div>
                    <div><span style="color:#666;">WCCs</span> <b style="color:#000;">{wcc_count}</b></div>
                    <div><span style="color:#666;">Max SCC</span> <b style="color:#000;">{largest_scc}</b></div>
                    <div><span style="color:#666;">Pivots</span> <b style="color:#000;">{art_count}</b></div>
                </div>
                {art_html}
            </div>""")

        # Section Centralité
        if centrality:
            top_pr = centrality.get('top_pagerank', [])[:2]
            top_bw = centrality.get('top_betweenness', [])[:2]

            pr_html = ""
            for addr, score in top_pr:
                pr_html += f'<div style="font-size:10px;margin-bottom:2px;"><span style="color:#666;">{addr[:6]}..</span> <b style="color:#000;font-weight:500;">{score:.3f}</b></div>'

            bw_html = ""
            for addr, score in top_bw:
                bw_html += f'<div style="font-size:10px;margin-bottom:2px;"><span style="color:#666;">{addr[:6]}..</span> <b style="color:#000;font-weight:500;">{score:.3f}</b></div>'

            html_parts.append(f"""
            <div style="margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid #e0e0e0;">
                <div style="font-size:9px;font-weight:500;color:#000;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.1em;">
                    Centralité
                </div>
                <div style="margin-bottom:10px;">
                    <div style="font-size:9px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.04em;">PageRank</div>
                    {pr_html}
                </div>
                <div>
                    <div style="font-size:9px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.04em;">Betweenness</div>
                    {bw_html}
                </div>
            </div>""")

        # Section Communautés
        if communities:
            clique_count = communities.get('clique_count', 0)
            max_clique = communities.get('max_clique_size', 0)

            largest_cliques = communities.get('largest_cliques', [])[:1]
            clique_html = ""
            for clique in largest_cliques:
                if len(clique) >= 3:
                    members = ", ".join([f"{addr[:5]}.." for addr in list(clique)[:2]])
                    clique_html += f'<div style="font-size:9px;color:#555;margin-top:4px;">{members}.. ({len(clique)})</div>'

            html_parts.append(f"""
            <div>
                <div style="font-size:9px;font-weight:500;color:#000;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.1em;">
                    Communautés
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:10px;margin-bottom:6px;">
                    <div><span style="color:#666;">Cliques</span> <b style="color:#000;">{clique_count}</b></div>
                    <div><span style="color:#666;">Max</span> <b style="color:#000;">{max_clique}</b></div>
                </div>
                {clique_html}
            </div>""")

        content = "".join(html_parts)

        return f"""
        <div style="position:absolute;top:20px;right:20px;background:#fafafa;padding:20px;border:1px solid #000;box-shadow:8px 8px 0 rgba(0,0,0,0.08);font-family:SF Mono,Monaco,Cascadia Code,monospace;z-index:1000;max-width:220px;max-height:80vh;overflow-y:auto;">
            <div style="font-size:11px;font-weight:500;color:#000;margin-bottom:16px;border-bottom:1px solid #000;padding-bottom:10px;text-transform:uppercase;letter-spacing:0.1em;">
                Analyse
            </div>
            {content}
        </div>
        """

    def create_visualization(
        self,
        graph: nx.MultiDiGraph,
        main_addresses: List[Address],
        title: str = "Ethereum Correlation Graph",
        global_score: Optional[float] = None,
        graph_analysis: Optional[Dict[str, Any]] = None
    ) -> Network:
        """Crée le réseau Pyvis."""

        net = Network(
            height="900px",
            width="100%",
            bgcolor="#ffffff",
            font_color="#000",
            directed=True
        )

        # Options optimisées - tooltips activés
        net.set_options("""{
          "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
              "gravitationalConstant": -100,
              "centralGravity": 0.01,
              "springLength": 200,
              "springConstant": 0.08
            },
            "maxVelocity": 50,
            "minVelocity": 0.1,
            "timestep": 0.35,
            "stabilization": {"enabled": true, "iterations": 1000}
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "hideEdgesOnDrag": true,
            "navigationButtons": true
          }
        }""")

        # Construire données
        nodes_data, nodes_js_data = self._build_node_data(graph, main_addresses)
        edges_data = self._build_edge_data(graph)

        # Ajouter nœuds avec positions calculées
        positions = self._calculate_positions(graph, main_addresses)
        main_addrs = {a.address for a in main_addresses}

        for node in nodes_data:
            pos = positions.get(node['id'], (0, 0))
            is_main = node['id'] in main_addrs

            # Nœuds principaux: fixés aux extrémités
            # Nœuds secondaires: libres de bouger
            net.add_node(
                node['id'],
                label=node['label'],
                title=node['title'],
                color=node['color'],
                size=node['size'],
                shape=node['shape'],
                font=node['font'],
                borderWidth=node['borderWidth'],
                x=pos[0],
                y=pos[1],
                fixed=is_main,  # Fixe seulement les nœuds principaux
                hidden=False    # Explicitement visible par défaut
            )

        # Ajouter arcs
        for edge in edges_data:
            net.add_edge(
                edge['from'],
                edge['to'],
                width=edge['width'],
                title=edge['title'],
                color=edge['color'],
                arrows=edge['arrows'],
                smooth=edge['smooth']
            )

        # Générer HTML
        net.generate_html()

        # Injecter JavaScript
        custom_js = self._get_custom_js(nodes_js_data)
        net.html = net.html.replace('</body>', f'<script>{custom_js}</script></body>')

        # Ajouter légende avec score global si fourni
        legend_html = self._generate_legend_html(global_score)
        net.html = net.html.replace('<div id="mynetwork"', f'{legend_html}<div id="mynetwork"')

        # Ajouter panneau d'analyse de graphe si fourni
        if graph_analysis:
            analysis_html = self._generate_graph_analysis_html(graph_analysis)
            net.html = net.html.replace('<div id="mynetwork"', f'{analysis_html}<div id="mynetwork"')

        return net

    def visualize(
        self,
        graph: nx.MultiDiGraph,
        main_addresses: List[Address],
        title: str = "Ethereum Correlation Graph",
        auto_open: bool = True,
        params: Optional[Dict[str, Any]] = None,
        global_score: Optional[float] = None,
        graph_analysis: Optional[Dict[str, Any]] = None
    ) -> str:
        """Crée et sauvegarde la visualisation dans un sous-dossier timestampé."""
        net = self.create_visualization(graph, main_addresses, title, global_score, graph_analysis)

        # Créer un sous-dossier avec timestamp pour cette exécution
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = self.base_output_dir / timestamp
        self.output_dir.mkdir(exist_ok=True)

        main_short = main_addresses[0].address[:8] if main_addresses else "unknown"
        num_nodes = graph.number_of_nodes()
        num_edges = graph.number_of_edges()
        num_main = len(main_addresses)

        # Construire le suffixe avec les paramètres
        params_suffix = ""
        if params:
            depth = params.get('expansion_depth', '')
            top_n = params.get('top_n', '')
            base_limit = params.get('base_tx_limit', '')
            exp_limit = params.get('expansion_tx_limit', '')
            params_suffix = f"_d{depth}_top{top_n}_b{base_limit}_e{exp_limit}"

        filename = f"interactive_graph_{main_short}_{num_nodes}nodes_{num_edges}edges_{num_main}main{params_suffix}.html"
        output_path = self.output_dir / filename

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(net.html)

        if auto_open:
            import webbrowser
            webbrowser.open(f'file://{output_path.absolute()}')

        return str(output_path)
