from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime


@dataclass
class SimilarityMetrics:
    """Métriques détaillées de similarité pour l'analyse avancée."""

    # Métriques structurelles
    simrank: float = 0.0
    ppr_cosine: float = 0.0
    vertex_connectivity: int = 0
    edge_connectivity: int = 0
    effective_resistance: float = float('inf')
    betweenness_restricted: float = 0.0

    # Métriques de chemins multiples
    num_disjoint_paths: int = 0
    path_entropy: float = 0.0
    weighted_path_sum: float = 0.0
    num_simple_paths: int = 0

    # Métriques temporelles
    temporal_coherence: float = 0.0
    activity_correlation: float = 0.0
    last_interaction_days: float = float('inf')

    # Métriques de routes fiables
    reliable_paths_count: int = 0
    max_path_reliability: float = 0.0
    avg_path_reliability: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            'structural': {
                'simrank': self.simrank,
                'ppr_cosine': self.ppr_cosine,
                'vertex_connectivity': self.vertex_connectivity,
                'edge_connectivity': self.edge_connectivity,
                'effective_resistance': self.effective_resistance,
                'betweenness_restricted': self.betweenness_restricted,
            },
            'multipath': {
                'num_disjoint_paths': self.num_disjoint_paths,
                'path_entropy': self.path_entropy,
                'weighted_path_sum': self.weighted_path_sum,
                'num_simple_paths': self.num_simple_paths,
            },
            'temporal': {
                'temporal_coherence': self.temporal_coherence,
                'activity_correlation': self.activity_correlation,
                'last_interaction_days': self.last_interaction_days,
            },
            'reliable_routes': {
                'reliable_paths_count': self.reliable_paths_count,
                'max_path_reliability': self.max_path_reliability,
                'avg_path_reliability': self.avg_path_reliability,
            }
        }


@dataclass(frozen=True)
class Address:
    address: str

    def __post_init__(self):
        # Basic validation or normalization could go here
        object.__setattr__(self, 'address', self.address.lower())


@dataclass
class Transaction:
    tx_hash: str
    sender: Address
    receiver: Address
    value: float
    timestamp: datetime
    token_symbol: str = "ETH"


@dataclass
class CorrelationResult:
    source: Address
    target: Address
    score: float
    path: List[Address] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class PathInfo:
    """Information sur un chemin indirect entre deux adresses."""
    nodes: List[Address]
    score: float
    depth: int

    def __repr__(self) -> str:
        path_str = " -> ".join([a.address[:8] + "..." for a in self.nodes])
        return f"Path({path_str}, score={self.score:.2f})"


@dataclass
class PropagatedPathInfo:
    """Information sur un chemin de propagation de score."""
    source: Address           # Adresse principale (départ)
    intermediate: List[Address]  # Nœuds intermédiaires
    target: Address           # Nœud final
    propagated_score: float   # Score propagé final
    path_scores: List[Tuple[str, float]]  # [(adresse, score_local), ...]
    decay_factor: float       # Facteur de déclin appliqué

    def __repr__(self) -> str:
        path = [self.source.address[:8] + "..."] + [a.address[:8] + "..." for a in self.intermediate] + [self.target.address[:8] + "..."]
        path_str = " -> ".join(path)
        return f"PropagatedPath({path_str}, score={self.propagated_score:.2f})"


@dataclass
class RelationshipScore:
    """Score de relation entre deux adresses avec métriques avancées."""
    source: Address
    target: Address
    direct_score: float  # Score basé sur les transactions directes
    indirect_score: float  # Score basé sur les chemins indirects
    propagated_score: float = 0.0  # Score par propagation multi-hop
    total_score: float = 0.0  # Score total (max des trois)
    metrics: Dict[str, Any] = field(default_factory=dict)

    # NOUVEAU: Scores avancés
    structural_similarity: float = 0.0      # SimRank/PPR-based
    multipath_score: float = 0.0            # Connectivité et robustesse
    temporal_dynamics: float = 0.0          # Patterns temporels
    adaptive_total: float = 0.0             # Score avec poids adaptatifs

    # NOUVEAU: Métriques détaillées
    similarity_metrics: SimilarityMetrics = field(default_factory=SimilarityMetrics)

    def __post_init__(self):
        """Calcule le total_score comme le max des trois scores."""
        object.__setattr__(
            self,
            'total_score',
            max(self.direct_score, self.indirect_score, self.propagated_score)
        )

    def __repr__(self) -> str:
        return (f"Relationship({self.source.address[:8]}... -> {self.target.address[:8]}..., "
                f"direct={self.direct_score:.1f}, indirect={self.indirect_score:.1f}, "
                f"propagated={self.propagated_score:.1f}, total={self.total_score:.1f})")

    def get_advanced_scores(self) -> Dict[str, float]:
        """Retourne tous les scores avancés."""
        return {
            'structural_similarity': self.structural_similarity,
            'multipath_score': self.multipath_score,
            'temporal_dynamics': self.temporal_dynamics,
            'adaptive_total': self.adaptive_total,
        }


@dataclass
class AddressRelationshipTable:
    """Tableau des relations d'une adresse principale avec toutes les autres adresses du graphe."""
    main_address: Address
    relationships: Dict[str, RelationshipScore] = field(default_factory=dict)

    def get_relationship(self, address: Address) -> Optional[RelationshipScore]:
        """Récupère le score de relation avec une adresse spécifique."""
        return self.relationships.get(address.address)

    def get_top_relationships(self, n: int = 10) -> List[RelationshipScore]:
        """Récupère les n relations avec les meilleurs scores."""
        sorted_rels = sorted(
            self.relationships.values(),
            key=lambda r: r.total_score,
            reverse=True
        )
        return sorted_rels[:n]

    def __repr__(self) -> str:
        return f"AddressRelationshipTable({self.main_address.address[:8]}..., {len(self.relationships)} relationships)"
