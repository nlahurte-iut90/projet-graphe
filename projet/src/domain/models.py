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
class RelationshipScore:
    """Score de relation entre deux adresses avec scoring temporel."""
    source: Address
    target: Address
    direct_score: float       # Score direct SD [0-1]
    indirect_score: float = 0.0  # Score indirect SI [0-1]
    total_score: float = 0.0  # Score total combiné [0-100]
    confidence: str = "low"    # 'high' | 'medium' | 'low'
    metrics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calcule le total_score comme combinaison pondérée direct + indirect.

        Utilise les poids dynamiques selon le nombre de transactions:
        - N < 3: w_dir=0.4, w_ind=0.55 (privilégier indirect)
        - N >= 3: w_dir=0.7, w_ind=0.25 (privilégier direct)
        """
        tx_count = self.metrics.get('tx_count', 0)

        # Poids dynamiques selon richesse des données
        if tx_count < 3:
            w_dir, w_ind = 0.4, 0.55
        else:
            w_dir, w_ind = 0.7, 0.25

        # Formule avec terme d'interaction
        interaction = 0.05 * self.direct_score * self.indirect_score
        total = w_dir * self.direct_score + w_ind * self.indirect_score + interaction

        object.__setattr__(self, 'total_score', min(total * 100, 100.0))

    def __repr__(self) -> str:
        return (f"Relationship({self.source.address[:8]}... -> {self.target.address[:8]}..., "
                f"direct={self.direct_score:.2f}, indirect={self.indirect_score:.2f}, "
                f"total={self.total_score:.1f}, confidence={self.confidence})")


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
