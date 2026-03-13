"""Scorer basé sur Personalized PageRank (PPR) pour la similarité."""

from typing import Dict, Any, Optional
import networkx as nx
import numpy as np

from src.services.scoring.base import SimilarityStrategy, NodeScore


class PPRScorer(SimilarityStrategy):
    """
    Scorer basé sur Personalized PageRank (PPR).

    Le PPR mesure l'importance des nœuds depuis la perspective d'une
    source spécifique. La similarité entre deux nœuds est calculée
    par la similarité cosinus de leurs vecteurs PPR.

    Paramètres:
        alpha: Taux de téléportation (1 - probabilité de continuer la random walk)
               Valeur typique: 0.15 (15% de chance de retour à la source)
    """

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        alpha: float = 0.15,
        max_iterations: int = 100,
        convergence_threshold: float = 1e-6
    ):
        super().__init__(graph)
        self.alpha = alpha
        self.max_iterations = max_iterations
        self.convergence_threshold = convergence_threshold

        # Cache des vecteurs PPR
        self._ppr_cache: Dict[str, Dict[str, float]] = {}

        # Précalcul de la structure de transition
        self._transition_weights: Dict[str, Dict[str, float]] = {}
        self._precompute_transitions()

    def get_name(self) -> str:
        return "PPRScorer"

    def get_description(self) -> str:
        return f"Personalized PageRank (alpha={self.alpha}) - similarité par marche aléatoire"

    def _precompute_transitions(self):
        """Précalcule les poids de transition entre nœuds."""
        for node in self.graph.nodes():
            successors = list(self.graph.successors(node))

            if not successors:
                self._transition_weights[node] = {}
                continue

            # Agréger les poids pour les multi-arêtes
            weights = {}
            for succ in successors:
                edge_data = self.graph.get_edge_data(node, succ, default={})
                total_weight = sum(
                    data.get('weight', 1.0) for data in edge_data.values()
                )
                weights[succ] = total_weight

            # Normaliser
            total = sum(weights.values())
            self._transition_weights[node] = {
                succ: w / total for succ, w in weights.items()
            }

    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule la similarité par cosinus des vecteurs PPR.
        """
        if main_address == node:
            return NodeScore(
                total=100.0,
                activity=100.0,
                proximity=100.0,
                recency=0.0,
                metrics={'ppr_cosine': 1.0, 'ppr_main': 1.0, 'ppr_node': 1.0}
            )

        if main_address not in self.graph or node not in self.graph:
            return NodeScore(
                total=0.0,
                activity=0.0,
                proximity=0.0,
                recency=0.0,
                metrics={'ppr_cosine': 0.0, 'error': 'Node not in graph'}
            )

        # Calculer les vecteurs PPR
        ppr_main = self.get_ppr_vector(main_address)
        ppr_node = self.get_ppr_vector(node)

        # Similarité cosinus
        cosine_sim = self._cosine_similarity(ppr_main, ppr_node)

        # Convertir en score 0-100 (cosine est dans [-1, 1])
        ppr_score = (cosine_sim + 1) / 2 * 100

        # Scores PPR spécifiques
        score_main_to_node = ppr_main.get(node, 0.0) * 100
        score_node_to_main = ppr_node.get(main_address, 0.0) * 100

        return NodeScore(
            total=round(ppr_score, 2),
            activity=round(ppr_score * 0.8, 2),   # PPR capture l'activité
            proximity=round((score_main_to_node + score_node_to_main) / 2, 2),
            recency=round(ppr_score * 0.3, 2),    # Faible capture du temporel
            metrics={
                'ppr_cosine': cosine_sim,
                'ppr_main_to_node': score_main_to_node / 100,
                'ppr_node_to_main': score_node_to_main / 100,
                'alpha': self.alpha
            }
        )

    def get_ppr_vector(self, source: str) -> Dict[str, float]:
        """
        Calcule le vecteur PPR depuis une source avec caching.

        Utilise la méthode des puissances (power iteration) pour
        résoudre: p = alpha * e_s + (1 - alpha) * W^T * p

        où e_s est le vecteur de personnalisation (1 à la source).
        """
        if source in self._ppr_cache:
            return self._ppr_cache[source]

        nodes = list(self.graph.nodes())
        n = len(nodes)
        node_idx = {node: i for i, node in enumerate(nodes)}

        if source not in node_idx:
            return {node: 0.0 for node in nodes}

        # Vecteur de personnalisation (téléportation vers la source)
        personalization = np.zeros(n)
        personalization[node_idx[source]] = 1.0

        # Power iteration
        p = personalization.copy()

        for iteration in range(self.max_iterations):
            # p_new = alpha * personalization + (1 - alpha) * W^T * p
            p_new = self.alpha * personalization + (1 - self.alpha) * self._transition_step(p, node_idx)

            # Vérifier la convergence
            diff = np.linalg.norm(p_new - p)
            p = p_new

            if diff < self.convergence_threshold:
                break

        # Convertir en dictionnaire
        result = {nodes[i]: float(p[i]) for i in range(n)}

        # Normaliser pour que la somme = 1
        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}

        self._ppr_cache[source] = result
        return result

    def _transition_step(self, p: np.ndarray, node_idx: Dict[str, int]) -> np.ndarray:
        """
        Effectue une étape de transition: p' = W^T * p

        Args:
            p: Vecteur de probabilité actuel
            node_idx: Mapping node -> index

        Returns:
            Nouveau vecteur de probabilité après transition
        """
        p_new = np.zeros_like(p)

        for node in self.graph.nodes():
            if node not in node_idx:
                continue

            idx = node_idx[node]
            prob = p[idx]

            if prob == 0:
                continue

            # Distribuer la probabilité aux successeurs
            transitions = self._transition_weights.get(node, {})
            for succ, weight in transitions.items():
                if succ in node_idx:
                    p_new[node_idx[succ]] += prob * weight

        return p_new

    def _cosine_similarity(self, vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
        """
        Calcule la similarité cosinus entre deux vecteurs représentés comme dicts.
        """
        # Obtenir toutes les clés
        all_keys = set(vec_a.keys()) | set(vec_b.keys())

        # Calculer le produit scalaire et les normes
        dot_product = 0.0
        norm_a = 0.0
        norm_b = 0.0

        for key in all_keys:
            a_val = vec_a.get(key, 0.0)
            b_val = vec_b.get(key, 0.0)

            dot_product += a_val * b_val
            norm_a += a_val ** 2
            norm_b += b_val ** 2

        norm_a = np.sqrt(norm_a)
        norm_b = np.sqrt(norm_b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def get_top_recommendations(self, source: str, top_n: int = 5) -> list:
        """
        Retourne les nœuds les plus "proches" selon PPR depuis la source.

        Returns:
            Liste de (node_id, ppr_score) triée par score décroissant
        """
        ppr_vector = self.get_ppr_vector(source)

        # Exclure la source elle-même
        recommendations = [
            (node, score)
            for node, score in ppr_vector.items()
            if node != source
        ]

        recommendations.sort(key=lambda x: x[1], reverse=True)
        return recommendations[:top_n]

    def compute_ppr_matrix(self) -> np.ndarray:
        """
        Calcule la matrice PPR complète pour tous les nœuds.

        Returns:
            Matrice n x n où M[i,j] = PPR(i -> j)
        """
        nodes = list(self.graph.nodes())
        n = len(nodes)

        matrix = np.zeros((n, n))

        for i, source in enumerate(nodes):
            ppr_vector = self.get_ppr_vector(source)
            for j, target in enumerate(nodes):
                matrix[i, j] = ppr_vector.get(target, 0.0)

        return matrix, nodes
