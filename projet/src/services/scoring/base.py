"""Base abstraite pour les stratégies de scoring de similarité."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import networkx as nx


@dataclass
class NodeScore:
    """Résultat du scoring d'un nœud avec dimensions temporelles.

    Structure alignée avec TemporalScorer:
    - total: Score total [0-100]
    - direct: Score direct SD [0-1]
    - indirect: Score indirect SI [0-1]
    - intensite: S_intensite [0-1]
    - recence: S_recence [0-1]
    - synchronie: S_sync [0-1]
    - equilibre: S_equilibre [0-1]
    - interaction: Terme d'interaction [0-1]
    - confidence: 'high' | 'medium' | 'low'
    - metrics: Métriques détaillées

    Champs legacy pour compatibilité autres scorers:
    - activity: Score d'activité [0-100]
    - proximity: Score de proximité [0-100]
    - recency: Score de récence [0-100]
    """
    total: float
    direct: float = 0.0
    indirect: float = 0.0
    intensite: float = 0.0
    recence: float = 0.0
    synchronie: float = 0.0
    equilibre: float = 0.0
    interaction: float = 0.0
    confidence: str = "low"
    metrics: Dict[str, Any] = field(default_factory=dict)
    # Champs legacy pour compatibilité
    activity: float = 0.0
    proximity: float = 0.0
    recency: float = 0.0

    def __repr__(self) -> str:
        return (f"NodeScore(total={self.total:.1f}, "
                f"direct={self.direct:.2f}, "
                f"indirect={self.indirect:.2f}, "
                f"confidence={self.confidence})")


class SimilarityStrategy(ABC):
    """
    Interface abstraite pour les stratégies de scoring de similarité entre nœuds.

    Toutes les implémentations doivent fournir une méthode `score` qui calcule
    la similarité entre une adresse principale et un nœud cible.
    """

    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph

    @abstractmethod
    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule le score de similarité entre main_address et node.

        Args:
            main_address: Adresse principale de référence
            node: Nœud cible à évaluer

        Returns:
            NodeScore avec les dimensions et métriques
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Retourne le nom de la stratégie."""
        pass

    @abstractmethod
    def get_description(self) -> str:
        """Retourne une description de la stratégie."""
        pass

    def _get_all_edges(self, u: str, v: str) -> List[Dict]:
        """Récupère toutes les arêtes entre u et v (dans les deux sens)."""
        edges = []

        # u -> v
        forward = self.graph.get_edge_data(u, v, default={})
        for key, data in forward.items():
            edge_data = dict(data)
            edge_data['from'] = u
            edge_data['to'] = v
            edges.append(edge_data)

        # v -> u
        backward = self.graph.get_edge_data(v, u, default={})
        for key, data in backward.items():
            edge_data = dict(data)
            edge_data['from'] = v
            edge_data['to'] = u
            edges.append(edge_data)

        return edges

    def _get_edge_data(self, u: str, v: str) -> Dict[str, Any]:
        """
        Agrège les données de toutes les arêtes entre u et v.

        Returns:
            Dict avec 'tx_count', 'total_volume', 'timestamps', etc.
        """
        edges = self._get_all_edges(u, v)

        if not edges:
            return {
                'tx_count': 0,
                'total_volume': 0.0,
                'timestamps': [],
                'weights': []
            }

        timestamps = []
        for e in edges:
            ts = e.get('time')
            if ts and ts != 'unknown':
                timestamps.append(ts)

        return {
            'tx_count': len(edges),
            'total_volume': sum(e.get('weight', 0) for e in edges),
            'timestamps': timestamps,
            'weights': [e.get('weight', 0) for e in edges],
            'has_bidirectional': any(e['from'] == v for e in edges) and any(e['from'] == u for e in edges)
        }
