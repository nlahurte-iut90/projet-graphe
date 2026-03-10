from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class TxRecord:
    """Schéma strict d'une transaction Ethereum pour le scoring de corrélation."""
    tx_hash: str
    from_address: str
    to_address: str
    value_eth: float
    block_number: int
    timestamp: int  # Unix timestamp seconds


@dataclass
class ScoringConfig:
    """Configuration pondérée du scoring de corrélation."""
    weights: Dict[str, float] = field(default_factory=lambda: {
        "volume": 0.40,
        "frequency": 0.20,
        "recency": 0.30,
        "bidirectionality": 0.10
    })
    recency_half_life_blocks: int = 6500  # ~30 jours @ 13s/bloc
    min_transaction_threshold: int = 1
    correlation_threshold: float = 0.6

    def __post_init__(self):
        """Valide que les poids somment à 1.0."""
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


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
    """Résultat de corrélation legacy (pour compatibilité)."""
    source: Address
    target: Address
    score: float
    path: List[Address] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class CorrelationScoreResult:
    """
    Résultat détaillé du scoring de corrélation v2.0.0.

    Contient le score final, les composants individuels,
    et les métadonnées pour l'explicabilité.
    """
    final_score: float  # [0.0, 1.0]
    is_correlated: bool  # True si final_score > threshold
    components: Dict[str, float]  # volume, frequency, recency, bidirectionality
    metadata: Dict[str, Any]  # métriques brutes (volumes, counts, handshakes, etc.)


@dataclass
class RelationshipScore:
    """Score de relation entre deux adresses."""
    source: Address
    target: Address
    direct_score: float  # Score basé sur les transactions directes
    total_score: float = 0.0  # Score total
    metrics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calcule le total_score égal au score direct."""
        object.__setattr__(self, 'total_score', self.direct_score)

    def __repr__(self) -> str:
        return (f"Relationship({self.source.address[:8]}... -> {self.target.address[:8]}..., "
                f"score={self.direct_score:.1f})")


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
