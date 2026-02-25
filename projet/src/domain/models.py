from dataclasses import dataclass, field
from typing import List, Optional
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
