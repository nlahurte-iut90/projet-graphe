"""Composants de scoring pour le calcul de corrélation entre adresses."""

import math
from typing import List, Tuple, Dict, Any
from src.domain.models import TxRecord


def calculate_volume_score(vol_out: float, vol_in: float, epsilon: float = 1e-9) -> float:
    """
    Calcule le score de volume basé sur l'équilibre directionnel.

    Concept: Mesurer l'équilibre des flux financiers. Un partenaire commercial
    a des flux équilibrés; un service (mixeur, exchange) a des flux déséquilibrés.

    Formula: balance_ratio * (1 - imbalance_penalty * 0.5)
    - balance_ratio = min(out,in) / max(out,in)
    - imbalance_penalty = |out-in| / (out+in)

    Args:
        vol_out: Volume total envoyé (ETH)
        vol_in: Volume total reçu (ETH)
        epsilon: Petite valeur pour éviter division par zéro

    Returns:
        Score de volume dans [0.0, 1.0]

    Examples:
        >>> calculate_volume_score(10.0, 10.0)  # Parfaitement équilibré
        1.0
        >>> calculate_volume_score(10.0, 1.0)   # Déséquilibre 10:1
        ~0.19
        >>> calculate_volume_score(10.0, 0.0)   # Unidirectionnel
        0.0
    """
    total_vol = vol_out + vol_in
    if total_vol == 0:
        return 0.0

    # Ratio d'équilibre (1.0 = parfaitement égal)
    balance_ratio = min(vol_out, vol_in) / (max(vol_out, vol_in) + epsilon)

    # Pénalité de déséquilibre absolu
    imbalance_penalty = abs(vol_out - vol_in) / (total_vol + epsilon)

    # Formule composée
    s_vol = balance_ratio * (1 - imbalance_penalty * 0.5)

    return max(0.0, min(1.0, s_vol))


def calculate_frequency_score(n_out: int, n_in: int) -> float:
    """
    Calcule le score de fréquence avec indice de Jaccard et intensité logarithmique.

    Concept: Indice de chevauchement directionnel pondéré par l'intensité totale
    (logarithmique pour éviter les bots).

    Formula: jaccard_directional * intensity_factor
    - jaccard = 2*min(n_out,n_in) / (n_out+n_in)
    - intensity = ln(1+n_total) / ln(1000), cap à 1.0

    Args:
        n_out: Nombre de transactions sortantes
        n_in: Nombre de transactions entrantes

    Returns:
        Score de fréquence dans [0.0, 1.0]
    """
    total_tx = n_out + n_in
    if total_tx == 0:
        return 0.0

    # Indice de Jaccard directionnel (1.0 si n_out == n_in)
    jaccard = (2.0 * min(n_out, n_in)) / total_tx

    # Facteur d'intensité logarithmique (diminishing returns)
    # Normalisé à 1000 transactions
    intensity_factor = min(math.log1p(total_tx) / math.log(1000), 1.0)

    return jaccard * intensity_factor


def calculate_recency_score(
    transactions_out: List[TxRecord],
    transactions_in: List[TxRecord],
    current_block: int,
    half_life_blocks: int
) -> float:
    """
    Calcule le score de récence avec décroissance exponentielle pondérée par valeur.

    Concept: Les transactions récentes comptent plus que les anciennes.
    Décroissance exponentielle avec demi-vie configurable.

    Formula pour chaque flux: sum(exp(-λ*age) * value) / sum(value)
    où λ = ln(2) / half_life

    Args:
        transactions_out: Liste des transactions sortantes
        transactions_in: Liste des transactions entrantes
        current_block: Hauteur de bloc actuelle
        half_life_blocks: Demi-vie en blocs pour la décroissance

    Returns:
        Score de récence dans [0.0, 1.0]
    """
    lambda_decay = math.log(2) / half_life_blocks

    def weighted_temporal_score(txs: List[TxRecord]) -> float:
        """Calcule le score temporel pondéré pour une liste de transactions."""
        if not txs:
            return 0.0

        numerator = 0.0
        denominator = 0.0

        for tx in txs:
            age = max(0, current_block - tx.block_number)
            weight = math.exp(-lambda_decay * age) * tx.value_eth
            numerator += weight
            denominator += tx.value_eth

        return numerator / denominator if denominator > 0 else 0.0

    score_out = weighted_temporal_score(transactions_out)
    score_in = weighted_temporal_score(transactions_in)

    # Moyenne pondérée par volume pour ne pas favoriser le petit côté
    total_vol = sum(t.value_eth for t in transactions_out + transactions_in)
    if total_vol == 0:
        return (score_out + score_in) / 2

    vol_out = sum(t.value_eth for t in transactions_out)
    vol_in = sum(t.value_eth for t in transactions_in)

    return (score_out * vol_out + score_in * vol_in) / total_vol


def calculate_bidirectionality_score(
    transactions_out: List[TxRecord],
    transactions_in: List[TxRecord],
    current_block: int
) -> Tuple[float, Dict[str, Any]]:
    """
    Calcule le score de bidirectionnalité avec détection de handshakes.

    Concept: Détection de cycles complets (handshakes) synchronisés temporellement.
    Normalisé [0,1] avec facteur 2 de correction.

    Components:
    - Reciprocity: (2 * handshakes) / (n_out + n_in)
    - Temporal sync: 1 - |avg_out - avg_in| / delta_max
    - Final: reciprocity * sync (logique AND)

    Args:
        transactions_out: Liste des transactions sortantes
        transactions_in: Liste des transactions entrantes
        current_block: Hauteur de bloc actuelle (pour contexte)

    Returns:
        Tuple de (score, metadata) où metadata contient les détails du calcul
    """
    n_out = len(transactions_out)
    n_in = len(transactions_in)

    if n_out == 0 or n_in == 0:
        return 0.0, {"handshakes": 0, "reciprocity_term": 0.0, "sync_term": 0.0, "time_gap_blocks": None}

    # Trier par block_number pour matching temporel
    out_sorted = sorted(transactions_out, key=lambda x: x.block_number)
    in_sorted = sorted(transactions_in, key=lambda x: x.block_number)

    # Détection des handshakes (appariement glouton 1-to-1)
    handshakes = 0
    used_in_indices = set()

    for out_tx in out_sorted:
        for idx, in_tx in enumerate(in_sorted):
            if idx not in used_in_indices and in_tx.block_number >= out_tx.block_number:
                handshakes += 1
                used_in_indices.add(idx)
                break

    # Terme de réciprocité (normalisé [0,1] avec facteur 2)
    reciprocity = min(1.0, (2.0 * handshakes) / (n_out + n_in))

    # Terme de synchronie temporelle
    avg_out = sum(t.block_number for t in transactions_out) / n_out
    avg_in = sum(t.block_number for t in transactions_in) / n_in
    time_gap = abs(avg_out - avg_in)

    # Fenêtre de normalisation
    all_blocks = [t.block_number for t in transactions_out + transactions_in]
    span = max(all_blocks) - min(all_blocks)
    delta_max = max(span, 1000)  # Éviter division par petit nombre

    sync_score = max(0.0, min(1.0, 1.0 - (time_gap / delta_max)))

    # Agrégation multiplicative (logique AND)
    score = reciprocity * sync_score

    metadata = {
        "handshakes": handshakes,
        "reciprocity_term": round(reciprocity, 4),
        "sync_term": round(sync_score, 4),
        "time_gap_blocks": round(time_gap, 2)
    }

    return score, metadata
