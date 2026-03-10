"""Configuration et constantes pour le scoring de corrélation."""

from src.domain.models import ScoringConfig

# Constantes Ethereum
ETH_BLOCK_TIME = 13  # secondes par bloc en moyenne
ETH_GENESIS_TIMESTAMP = 1438269975  # Unix timestamp du genesis block (30 juillet 2015)

# Configuration par défaut selon spec v2.0.0
DEFAULT_CONFIG = ScoringConfig(
    weights={
        "volume": 0.40,
        "frequency": 0.20,
        "recency": 0.30,
        "bidirectionality": 0.10
    },
    recency_half_life_blocks=6500,  # ~30 jours
    min_transaction_threshold=1,
    correlation_threshold=0.6
)


def timestamp_to_block(timestamp: int) -> int:
    """
    Convertit un timestamp Unix en numéro de bloc approximatif.

    Args:
        timestamp: Unix timestamp en secondes

    Returns:
        Numéro de bloc estimé
    """
    if timestamp < ETH_GENESIS_TIMESTAMP:
        return 0
    return int((timestamp - ETH_GENESIS_TIMESTAMP) / ETH_BLOCK_TIME)


def get_current_block() -> int:
    """
    Obtient le numéro de bloc actuel approximatif basé sur l'heure actuelle.

    Returns:
        Numéro de bloc estimé pour maintenant
    """
    from datetime import datetime
    current_timestamp = int(datetime.now().timestamp())
    return timestamp_to_block(current_timestamp)
