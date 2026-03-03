from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


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
class RelationshipScore:
    """Score de relation entre deux adresses."""
    source: Address
    target: Address
    direct_score: float  # Score basé sur les transactions directes
    indirect_score: float  # Score basé sur les chemins indirects
    total_score: float  # Score total (max des deux)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (f"Relationship({self.source.address[:8]}... -> {self.target.address[:8]}..., "
                f"direct={self.direct_score:.1f}, indirect={self.indirect_score:.1f}, "
                f"total={self.total_score:.1f})")


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
