"""Scorer principal de corrélation entre deux adresses Ethereum.

Implémente l'algorithme composite à 4 dimensions selon spec v2.0.0:
- Volume (40%): Équilibre directionnel des flux
- Fréquence (20%): Indice de Jaccard avec intensité logarithmique
- Récence (30%): Décroissance exponentielle pondérée par valeur
- Bidirectionnalité (10%): Détection de handshakes synchronisés
"""

from typing import List, Optional
from datetime import datetime

from src.domain.models import TxRecord, ScoringConfig, CorrelationScoreResult
from src.services.scoring.components import (
    calculate_volume_score,
    calculate_frequency_score,
    calculate_recency_score,
    calculate_bidirectionality_score,
)
from src.services.scoring.config import timestamp_to_block


def calculate_address_correlation(
    primary_address: str,
    neighbor_address: str,
    transaction_set: List[TxRecord],
    current_block_height: Optional[int] = None,
    config: Optional[ScoringConfig] = None
) -> CorrelationScoreResult:
    """
    Calcule un score de corrélation [0.0, 1.0] entre deux adresses Ethereum.

    Approche: Graphe orienté pondéré temporel avec agrégation linéaire pondérée.

    Args:
        primary_address: Adresse principale (0x...)
        neighbor_address: Adresse voisine (0x...)
        transaction_set: Liste des transactions brutes (filtrées par la fonction)
        current_block_height: Hauteur de bloc actuelle (auto-détectée si None)
        config: Configuration de scoring (default si None)

    Returns:
        CorrelationResult avec score final, composants et métadonnées

    Examples:
        >>> txs = [
        ...     TxRecord("0x1", "0xA", "0xB", 1.0, 1000000, 1640000000),
        ...     TxRecord("0x2", "0xB", "0xA", 1.0, 1000001, 1640000013),
        ... ]
        >>> result = calculate_address_correlation("0xA", "0xB", txs)
        >>> result.final_score
        0.95
    """
    from src.services.scoring.config import DEFAULT_CONFIG, get_current_block

    if config is None:
        config = DEFAULT_CONFIG

    # Déterminer le bloc actuel si non fourni
    if current_block_height is None:
        current_block_height = get_current_block()

    # Étape 0: Validation et filtrage
    # Filtrer pour ne garder que les transactions entre les deux adresses
    # ET avec value_eth > 0 (ignorer les transferts de tokens purs)
    filtered = [
        tx for tx in transaction_set
        if tx.value_eth > 0 and (
            (tx.from_address == primary_address and tx.to_address == neighbor_address) or
            (tx.from_address == neighbor_address and tx.to_address == primary_address)
        )
    ]

    # Vérifier le seuil minimum
    if len(filtered) < config.min_transaction_threshold:
        return _zero_result(config)

    # Séparer OUT (primary -> neighbor) et IN (neighbor -> primary)
    OUT = [tx for tx in filtered if tx.from_address == primary_address]
    IN = [tx for tx in filtered if tx.from_address == neighbor_address]

    # Calculer métriques brutes
    vol_out = sum(tx.value_eth for tx in OUT)
    vol_in = sum(tx.value_eth for tx in IN)
    n_out = len(OUT)
    n_in = len(IN)

    # Étape 1: Score de Volume
    s_vol = calculate_volume_score(vol_out, vol_in)

    # Étape 2: Score de Fréquence
    s_freq = calculate_frequency_score(n_out, n_in)

    # Étape 3: Score de Récence
    s_rec = calculate_recency_score(
        OUT, IN,
        current_block_height,
        config.recency_half_life_blocks
    )

    # Étape 4: Score de Bidirectionnalité
    s_bidir, bidir_meta = calculate_bidirectionality_score(
        OUT, IN,
        current_block_height
    )

    # Étape 5: Agrégation Composite
    weights = config.weights
    final = (
        s_vol * weights.get("volume", 0.40) +
        s_freq * weights.get("frequency", 0.20) +
        s_rec * weights.get("recency", 0.30) +
        s_bidir * weights.get("bidirectionality", 0.10)
    )

    # Calculer span temporel
    all_blocks = [tx.block_number for tx in filtered]
    temporal_span = max(all_blocks) - min(all_blocks) if len(all_blocks) > 1 else 0

    return CorrelationScoreResult(
        final_score=round(final, 4),
        is_correlated=final > config.correlation_threshold,
        components={
            "volume_score": round(s_vol, 4),
            "frequency_score": round(s_freq, 4),
            "recency_score": round(s_rec, 4),
            "bidirectionality_score": round(s_bidir, 4)
        },
        metadata={
            "total_volume_out": round(vol_out, 4),
            "total_volume_in": round(vol_in, 4),
            "tx_count_out": n_out,
            "tx_count_in": n_in,
            "temporal_span_blocks": temporal_span,
            "handshake_cycles": bidir_meta["handshakes"],
            "reciprocity_term": bidir_meta.get("reciprocity_term", 0.0),
            "sync_term": bidir_meta.get("sync_term", 0.0),
            "time_gap_blocks": bidir_meta.get("time_gap_blocks")
        }
    )


def _zero_result(config: Optional[ScoringConfig] = None) -> CorrelationScoreResult:
    """Retourne un résultat nul quand pas assez de transactions."""
    from src.services.scoring.config import DEFAULT_CONFIG
    cfg = config or DEFAULT_CONFIG

    return CorrelationScoreResult(
        final_score=0.0,
        is_correlated=False,
        components={
            "volume_score": 0.0,
            "frequency_score": 0.0,
            "recency_score": 0.0,
            "bidirectionality_score": 0.0
        },
        metadata={
            "total_volume_out": 0.0,
            "total_volume_in": 0.0,
            "tx_count_out": 0,
            "tx_count_in": 0,
            "temporal_span_blocks": 0,
            "handshake_cycles": 0,
            "reciprocity_term": 0.0,
            "sync_term": 0.0,
            "time_gap_blocks": None
        }
    )


def calculate_correlation_from_edges(
    primary_address: str,
    neighbor_address: str,
    edges: List[dict],
    config: Optional[ScoringConfig] = None
) -> CorrelationScoreResult:
    """
    Calcule la corrélation depuis des edges du graphe NetworkX.

    Convertit automatiquement les edges en TxRecord et appelle
    calculate_address_correlation.

    Args:
        primary_address: Adresse principale
        neighbor_address: Adresse voisine
        edges: Liste de dictionnaires avec clés 'from', 'to', 'weight', 'time', 'hash'
        config: Configuration de scoring

    Returns:
        CorrelationResult
    """
    transactions = []

    for edge in edges:
        # Extraire les champs avec valeurs par défaut
        tx_hash = edge.get('hash', '0x0')
        from_addr = edge.get('from', '')
        to_addr = edge.get('to', '')
        value_eth = edge.get('weight', 0.0)

        # Convertir timestamp en block_number approximatif
        time_val = edge.get('time')
        if time_val:
            if isinstance(time_val, str):
                # Parser ISO format
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(time_val.replace('Z', '+00:00'))
                    timestamp = int(dt.timestamp())
                except (ValueError, TypeError):
                    timestamp = int(datetime.now().timestamp())
            elif isinstance(time_val, datetime):
                timestamp = int(time_val.timestamp())
            else:
                timestamp = int(time_val)
        else:
            timestamp = int(datetime.now().timestamp())

        block_num = timestamp_to_block(timestamp)

        transactions.append(TxRecord(
            tx_hash=tx_hash,
            from_address=from_addr,
            to_address=to_addr,
            value_eth=value_eth,
            block_number=block_num,
            timestamp=timestamp
        ))

    return calculate_address_correlation(
        primary_address,
        neighbor_address,
        transactions,
        config=config
    )
