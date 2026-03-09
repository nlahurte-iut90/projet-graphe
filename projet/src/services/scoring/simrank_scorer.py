"""Scorer basé sur l'algorithme SimRank pour la similarité structurelle."""

from typing import Dict, Any, Set, Optional
import networkx as nx
import numpy as np

from src.services.scoring.base import SimilarityStrategy, NodeScore


class SimRankScorer(SimilarityStrategy):
    """
    Scorer basé sur SimRank - mesure de similarité structurelle.

    Principe: Deux nœuds sont similaires s'ils sont référencés par des nœuds similaires.
    Formule: s(a, b) = (decay / |I(a)|*|I(b)|) * sum(s(i, j) for i in I(a), j in I(b))

    où I(a) sont les prédécesseurs (in-neighbors) de a.
    """

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        decay: float = 0.8,
        iterations: int = 5,
        convergence_threshold: float = 0.001,
        use_neighborhood_optimization: bool = True
    ):
        super().__init__(graph)
        self.decay = decay
        self.iterations = iterations
        self.convergence_threshold = convergence_threshold
        self.use_neighborhood_optimization = use_neighborhood_optimization

        # Cache des prédécesseurs et voisins
        self._in_neighbors: Dict[str, list] = {}
        self._simrank_cache: Dict[tuple, float] = {}

        # Précalcul des prédécesseurs
        self._precompute_neighbors()

    def get_name(self) -> str:
        return "SimRankScorer"

    def get_description(self) -> str:
        return f"Scorer SimRank (decay={self.decay}, iter={self.iterations}) - similarité structurelle"

    def _precompute_neighbors(self):
        """Précalcule les prédécesseurs pour tous les nœuds."""
        for node in self.graph.nodes():
            self._in_neighbors[node] = list(self.graph.predecessors(node))

    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule le score SimRank entre main_address et node.

        Utilise une approximation itérative avec early stopping si convergence.
        """
        if main_address == node:
            return NodeScore(
                total=100.0,
                activity=100.0,
                proximity=100.0,
                recency=0.0,
                metrics={'simrank': 1.0, 'iterations': 0}
            )

        if main_address not in self.graph or node not in self.graph:
            return NodeScore(
                total=0.0,
                activity=0.0,
                proximity=0.0,
                recency=0.0,
                metrics={'simrank': 0.0, 'error': 'Node not in graph'}
            )

        # Vérifier le cache
        cache_key = (main_address, node)
        if cache_key in self._simrank_cache:
            simrank = self._simrank_cache[cache_key]
        else:
            # Calcul SimRank
            if self.use_neighborhood_optimization:
                simrank = self._compute_simrank_optimized(main_address, node)
            else:
                simrank = self._compute_simrank_full(main_address, node)

            self._simrank_cache[cache_key] = simrank
            self._simrank_cache[(node, main_address)] = simrank  # Symétrique

        # Convertir en score 0-100
        simrank_score = simrank * 100

        return NodeScore(
            total=round(simrank_score, 2),
            activity=round(simrank_score * 0.9, 2),  # SimRank capture principalement l'activité
            proximity=round(simrank_score, 2),       # et la proximité structurelle
            recency=round(simrank_score * 0.2, 2),   # Faible capture du temporel
            metrics={
                'simrank': simrank,
                'decay': self.decay,
                'in_degree_main': len(self._in_neighbors.get(main_address, [])),
                'in_degree_node': len(self._in_neighbors.get(node, []))
            }
        )

    def _compute_simrank_full(self, a: str, b: str) -> float:
        """
        Version complète de SimRank sur tout le graphe.

        Complexité: O(k * n^2) où k = iterations, n = nombre de nœuds
        """
        nodes = list(self.graph.nodes())

        # Initialisation: sim(u, u) = 1, sim(u, v) = 0
        sim = {
            (u, v): 1.0 if u == v else 0.0
            for u in nodes for v in nodes
        }

        for iteration in range(self.iterations):
            new_sim = {}
            max_diff = 0.0

            for u in nodes:
                for v in nodes:
                    if u == v:
                        new_sim[(u, v)] = 1.0
                        continue

                    in_u = self._in_neighbors[u]
                    in_v = self._in_neighbors[v]

                    if not in_u or not in_v:
                        new_sim[(u, v)] = 0.0
                        continue

                    # Moyenne des similarités des paires de prédécesseurs
                    s = sum(sim.get((i, j), 0) for i in in_u for j in in_v)
                    new_sim[(u, v)] = self.decay * s / (len(in_u) * len(in_v))

                    # Calcul de la différence pour convergence
                    diff = abs(new_sim[(u, v)] - sim.get((u, v), 0))
                    max_diff = max(max_diff, diff)

            sim = new_sim

            # Early stopping si convergence
            if max_diff < self.convergence_threshold:
                break

        return sim.get((a, b), 0.0)

    def _compute_simrank_optimized(self, a: str, b: str) -> float:
        """
        Version optimisée calculant SimRank uniquement sur le voisinage.

        Réduit la complexité en se concentrant sur les nœuds pertinents.
        """
        # Collecter les nœuds dans le k-hop neighborhood
        relevant_nodes = self._get_k_hop_neighborhood(a, b, hops=2)

        if not relevant_nodes:
            return 0.0

        # SimRank restreint au sous-graphe pertinent
        sim = {
            (u, v): 1.0 if u == v else 0.0
            for u in relevant_nodes for v in relevant_nodes
        }

        for _ in range(self.iterations):
            new_sim = {}

            for u in relevant_nodes:
                for v in relevant_nodes:
                    if u == v:
                        new_sim[(u, v)] = 1.0
                        continue

                    in_u = [n for n in self._in_neighbors[u] if n in relevant_nodes]
                    in_v = [n for n in self._in_neighbors[v] if n in relevant_nodes]

                    if not in_u or not in_v:
                        new_sim[(u, v)] = 0.0
                        continue

                    s = sum(sim.get((i, j), 0) for i in in_u for j in in_v)
                    new_sim[(u, v)] = self.decay * s / (len(in_u) * len(in_v))

            sim = new_sim

        return sim.get((a, b), 0.0)

    def _get_k_hop_neighborhood(self, a: str, b: str, hops: int = 2) -> Set[str]:
        """
        Retourne l'union des k-hop neighborhoods de a et b.

        Inclut les prédécesseurs et successeurs pour capturer
        la structure de similarité.
        """
        nodes = {a, b}

        def expand(current_nodes: Set[str], remaining_hops: int) -> Set[str]:
            if remaining_hops <= 0:
                return current_nodes

            new_nodes = set(current_nodes)
            for node in current_nodes:
                # Prédécesseurs (pour SimRank)
                new_nodes.update(self._in_neighbors.get(node, []))
                # Successeurs (pour complétude)
                new_nodes.update(self.graph.successors(node))

            return expand(new_nodes, remaining_hops - 1)

        return expand(nodes, hops)

    def compute_similarity_matrix(self) -> np.ndarray:
        """
        Calcule la matrice de similarité SimRank complète.

        Returns:
            Matrice n x n où n = nombre de nœuds
        """
        nodes = list(self.graph.nodes())
        n = len(nodes)
        node_idx = {node: i for i, node in enumerate(nodes)}

        # Initialisation
        sim = np.eye(n)

        for _ in range(self.iterations):
            new_sim = np.zeros((n, n))

            for i, u in enumerate(nodes):
                for j, v in enumerate(nodes):
                    if i == j:
                        new_sim[i, j] = 1.0
                        continue

                    in_u = self._in_neighbors[u]
                    in_v = self._in_neighbors[v]

                    if not in_u or not in_v:
                        continue

                    # Somme des similarités des prédécesseurs
                    s = sum(
                        sim[node_idx.get(i_node, 0), node_idx.get(j_node, 0)]
                        for i_node in in_u for j_node in in_v
                        if i_node in node_idx and j_node in node_idx
                    )
                    new_sim[i, j] = self.decay * s / (len(in_u) * len(in_v))

            sim = new_sim

        return sim, nodes

    def get_top_similar(self, node: str, top_n: int = 5) -> list:
        """
        Retourne les nœuds les plus similaires à node selon SimRank.

        Returns:
            Liste de (node_id, simrank_score) triée par score décroissant
        """
        similarities = []

        for other in self.graph.nodes():
            if other != node:
                score = self._compute_simrank_optimized(node, other)
                similarities.append((other, score))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_n]
