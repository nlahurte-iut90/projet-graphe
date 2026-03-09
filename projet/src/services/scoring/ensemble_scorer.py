"""Scorer ensemble combinant plusieurs stratégies avec poids adaptatifs."""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Type
import math
import numpy as np
import networkx as nx

from src.services.scoring.base import SimilarityStrategy, NodeScore
from src.services.scoring.simple_node_scorer import SimpleNodeScorer
from src.services.scoring.simrank_scorer import SimRankScorer
from src.services.scoring.ppr_scorer import PPRScorer
from src.services.scoring.multipath_scorer import MultipathScorer
from src.services.scoring.reliable_route_scorer import ReliableRouteScorer


@dataclass
class AdaptiveWeights:
    """Poids adaptatifs selon le contexte."""
    activity: float = 0.35
    proximity: float = 0.25
    structural: float = 0.25
    temporal: float = 0.15

    def normalize(self):
        """Normalise les poids pour sommer à 1."""
        total = self.activity + self.proximity + self.structural + self.temporal
        if total > 0:
            self.activity /= total
            self.proximity /= total
            self.structural /= total
            self.temporal /= total


class EnsembleScorer(SimilarityStrategy):
    """
    Scorer ensemble combinant plusieurs stratégies avec poids adaptatifs.

    Combine:
    - SimpleNodeScorer: métriques de base (activité, proximité, récence)
    - SimRankScorer: similarité structurelle
    - PPRScorer: Personalized PageRank
    - MultipathScorer: robustesse des connexions
    - ReliableRouteScorer: routes fiables avec cohérence temporelle

    Les poids sont adaptatifs selon les caractéristiques de la relation.
    """

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        enabled_scorers: Optional[List[str]] = None,
        use_adaptive_weights: bool = True,
        use_sigmoid: bool = True
    ):
        super().__init__(graph)
        self.use_adaptive_weights = use_adaptive_weights
        self.use_sigmoid = use_sigmoid

        # Scorers disponibles
        all_scorers = {
            'simple': SimpleNodeScorer(graph),
            'simrank': SimRankScorer(graph),
            'ppr': PPRScorer(graph),
            'multipath': MultipathScorer(graph),
            'reliable': ReliableRouteScorer(graph)
        }

        # Sélectionner les scorers à utiliser
        if enabled_scorers:
            self.scorers = {
                k: v for k, v in all_scorers.items()
                if k in enabled_scorers
            }
        else:
            self.scorers = all_scorers

    def get_name(self) -> str:
        return "EnsembleScorer"

    def get_description(self) -> str:
        scorers = ", ".join(self.scorers.keys())
        return f"Combinaison adaptative de: {scorers}"

    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule le score combiné avec poids adaptatifs.
        """
        if main_address == node:
            return NodeScore(
                total=100.0,
                activity=100.0,
                proximity=100.0,
                recency=100.0,
                metrics={'self': True}
            )

        if main_address not in self.graph or node not in self.graph:
            return NodeScore(
                total=0.0,
                activity=0.0,
                proximity=0.0,
                recency=0.0,
                metrics={'error': 'Node not in graph'}
            )

        # Collecter les scores de chaque méthode
        scores: Dict[str, NodeScore] = {}
        for name, scorer in self.scorers.items():
            try:
                scores[name] = scorer.score(main_address, node)
            except Exception as e:
                # En cas d'erreur, utiliser un score nul
                scores[name] = NodeScore(
                    total=0.0,
                    activity=0.0,
                    proximity=0.0,
                    recency=0.0,
                    metrics={'error': str(e)}
                )

        # Calculer poids adaptatifs
        if self.use_adaptive_weights:
            weights = self._compute_adaptive_weights(main_address, node, scores)
        else:
            weights = AdaptiveWeights()
            weights.normalize()

        # Combinaison pondérée
        combined = self._combine_scores(scores, weights)

        return NodeScore(
            total=round(combined['total'], 2),
            activity=round(combined['activity'], 2),
            proximity=round(combined['proximity'], 2),
            recency=round(combined['recency'], 2),
            metrics={
                'individual_scores': {k: round(v.total, 2) for k, v in scores.items()},
                'weights': {
                    'activity': round(weights.activity, 3),
                    'proximity': round(weights.proximity, 3),
                    'structural': round(weights.structural, 3),
                    'temporal': round(weights.temporal, 3)
                },
                'combination_method': 'adaptive_sigmoid' if self.use_sigmoid else 'adaptive_linear'
            }
        )

    def _compute_adaptive_weights(
        self,
        main: str,
        node: str,
        scores: Dict[str, NodeScore]
    ) -> AdaptiveWeights:
        """
        Ajuste les poids selon les caractéristiques de la relation.
        """
        weights = AdaptiveWeights(
            activity=0.35,
            proximity=0.25,
            structural=0.25,
            temporal=0.15
        )

        # Récupérer les scores individuels
        simple_total = scores.get('simple', NodeScore(0, 0, 0, 0, {})).total
        simrank_total = scores.get('simrank', NodeScore(0, 0, 0, 0, {})).total
        multipath_total = scores.get('multipath', NodeScore(0, 0, 0, 0, {})).total
        reliable_recency = scores.get('reliable', NodeScore(0, 0, 0, 0, {})).recency

        # Règle 1: Si forte similarité structurelle mais faible activité directe
        if simrank_total > 60 and simple_total < 30:
            weights.structural += 0.15
            weights.activity -= 0.15

        # Règle 2: Si multiples chemins disponibles (robustesse)
        if multipath_total > 50:
            weights.structural += 0.10
            weights.proximity -= 0.10

        # Règle 3: Si forte cohérence temporelle
        if reliable_recency > 70:
            weights.temporal += 0.10
            weights.activity -= 0.10

        # Règle 4: Si forte activité directe, privilégier l'activité
        if simple_total > 70:
            weights.activity += 0.10
            weights.structural -= 0.10

        # Normaliser
        weights.normalize()
        return weights

    def _combine_scores(
        self,
        scores: Dict[str, NodeScore],
        weights: AdaptiveWeights
    ) -> Dict[str, float]:
        """
        Combine les scores avec possibilité de non-linéarité (sigmoid).
        """
        # Agréger chaque dimension selon les catégories
        activity_scores = []
        proximity_scores = []
        temporal_scores = []

        # Catégorisation des scorers
        for name, score in scores.items():
            if name == 'simple':
                activity_scores.append((score.activity, 0.6))
                proximity_scores.append((score.proximity, 0.6))
                temporal_scores.append((score.recency, 0.4))
            elif name in ['simrank', 'ppr']:
                activity_scores.append((score.activity, 0.4))
                proximity_scores.append((score.proximity, 0.4))
            elif name == 'multipath':
                activity_scores.append((score.activity, 0.5))
                proximity_scores.append((score.proximity, 0.5))
            elif name == 'reliable':
                activity_scores.append((score.activity, 0.3))
                proximity_scores.append((score.proximity, 0.3))
                temporal_scores.append((score.recency, 0.6))

        # Calculer les moyennes pondérées
        def weighted_average(scores_with_weights: List[tuple]) -> float:
            if not scores_with_weights:
                return 0.0
            total_weight = sum(w for _, w in scores_with_weights)
            if total_weight == 0:
                return 0.0
            return sum(s * w for s, w in scores_with_weights) / total_weight

        activity = weighted_average(activity_scores)
        proximity = weighted_average(proximity_scores)
        recency = weighted_average(temporal_scores)

        # Appliquer non-linéarité si activée
        if self.use_sigmoid:
            def sigmoid(x: float, threshold: float = 50, steepness: float = 0.1) -> float:
                """Fonction sigmoid pour seuillage doux."""
                return 100 / (1 + math.exp(-steepness * (x - threshold)))

            activity = sigmoid(activity)
            proximity = sigmoid(proximity)
            recency = sigmoid(recency)

        # Combinaison finale avec les poids adaptatifs
        total = (
            weights.activity * activity +
            weights.proximity * proximity +
            weights.structural * ((activity + proximity) / 2) +
            weights.temporal * recency
        )

        return {
            'total': min(total, 100.0),
            'activity': activity,
            'proximity': proximity,
            'recency': recency
        }

    def get_scorer_contributions(self, main_address: str, node: str) -> Dict[str, float]:
        """
        Retourne la contribution de chaque scorer au score final.

        Utile pour comprendre quels scorers influencent le résultat.
        """
        scores = {}
        for name, scorer in self.scorers.items():
            try:
                score = scorer.score(main_address, node)
                scores[name] = score.total
            except Exception:
                scores[name] = 0.0

        return scores

    def compare_scorers(self, main_address: str, node: str) -> Dict[str, Any]:
        """
        Compare les scores de tous les scorers pour une paire de nœuds.

        Returns:
            Dict avec les scores détaillés de chaque scorer
        """
        comparison = {
            'main_address': main_address[:10] + '...' if len(main_address) > 10 else main_address,
            'target_node': node[:10] + '...' if len(node) > 10 else node,
            'scorers': {}
        }

        for name, scorer in self.scorers.items():
            try:
                score = scorer.score(main_address, node)
                comparison['scorers'][name] = {
                    'total': round(score.total, 2),
                    'activity': round(score.activity, 2),
                    'proximity': round(score.proximity, 2),
                    'recency': round(score.recency, 2),
                    'metrics': score.metrics
                }
            except Exception as e:
                comparison['scorers'][name] = {'error': str(e)}

        # Score ensemble
        ensemble_score = self.score(main_address, node)
        comparison['ensemble'] = {
            'total': round(ensemble_score.total, 2),
            'activity': round(ensemble_score.activity, 2),
            'proximity': round(ensemble_score.proximity, 2),
            'recency': round(ensemble_score.recency, 2),
            'weights': ensemble_score.metrics.get('weights', {})
        }

        return comparison
