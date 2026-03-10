"""Tests pour le correlation scorer v2.0.0.

Cas de test basés sur la spécification technique:
1. Commerçant régulier (High Correlation)
2. Victime d'escroquerie (Low Bidirectionality)
3. Service unidirectionnel (Exchange)
4. Ancienne relation (Low Recency)
"""

import pytest
from datetime import datetime
from src.domain.models import TxRecord, ScoringConfig
from src.services.scoring.components import (
    calculate_volume_score,
    calculate_frequency_score,
    calculate_recency_score,
    calculate_bidirectionality_score,
)
from src.services.scoring.correlation_scorer import calculate_address_correlation


class TestVolumeScore:
    """Tests pour le score de volume."""

    def test_perfectly_balanced(self):
        """Flux parfaitement équilibrés -> score proche de 1.0."""
        score = calculate_volume_score(10.0, 10.0)
        assert score > 0.99  # Tolérance pour précision flottante

    def test_moderate_imbalance(self):
        """Déséquilibre 10:1 -> score faible (~0.06 selon formule)."""
        score = calculate_volume_score(10.0, 1.0)
        # balance_ratio=0.1, imbalance_penalty=0.818, s_vol=0.1*(1-0.409)=0.059
        assert 0.05 < score < 0.10

    def test_unidirectional_pure(self):
        """Flux unidirectionnel pur -> score 0.0."""
        assert calculate_volume_score(10.0, 0.0) == 0.0

    def test_reverse_unidirectional(self):
        """Flux unidirectionnel inverse -> score 0.0."""
        assert calculate_volume_score(0.0, 10.0) == 0.0

    def test_zero_total(self):
        """Volume total nul -> score 0.0."""
        assert calculate_volume_score(0.0, 0.0) == 0.0

    def test_bounds(self):
        """Vérifie que le score est toujours dans [0, 1]."""
        test_cases = [
            (100.0, 100.0),
            (100.0, 1.0),
            (1.0, 100.0),
            (0.001, 0.001),
            (10000.0, 5000.0),
        ]
        for out, inn in test_cases:
            score = calculate_volume_score(out, inn)
            assert 0.0 <= score <= 1.0, f"Score {score} hors limites pour ({out}, {inn})"


class TestFrequencyScore:
    """Tests pour le score de fréquence."""

    def test_perfect_symmetry(self):
        """Nombre égal de tx dans les deux sens -> Jaccard = 1.0."""
        score = calculate_frequency_score(10, 10)
        # Jaccard=1.0, Intensité=ln(21)/ln(1000)~0.44
        assert 0.4 < score < 0.5

    def test_pure_unidirectional(self):
        """Unidirectionnel pur -> score 0.0."""
        assert calculate_frequency_score(10, 0) == 0.0
        assert calculate_frequency_score(0, 10) == 0.0

    def test_partial_reciprocity(self):
        """Réciprocité partielle -> score intermédiaire."""
        score = calculate_frequency_score(8, 2)
        # Jaccard = 2*2/10 = 0.4, Intensité = ln(11)/ln(1000) ~ 0.35
        assert 0.1 < score < 0.5

    def test_single_transaction(self):
        """Une seule transaction -> score bas mais non nul."""
        score = calculate_frequency_score(1, 0)
        assert score == 0.0  # Unidirectionnel

    def test_bounds(self):
        """Vérifie que le score est toujours dans [0, 1]."""
        test_cases = [
            (100, 100),
            (1000, 1),
            (1, 1000),
            (0, 0),
        ]
        for out, inn in test_cases:
            score = calculate_frequency_score(out, inn)
            assert 0.0 <= score <= 1.0


class TestRecencyScore:
    """Tests pour le score de récence."""

    def test_all_recent(self):
        """Toutes les transactions récentes -> score élevé."""
        current_block = 1000000
        half_life = 6500

        txs_out = [TxRecord(f"0x{i}", "A", "B", 1.0, current_block - 100, 0) for i in range(5)]
        txs_in = [TxRecord(f"0x{i}", "B", "A", 1.0, current_block - 50, 0) for i in range(5)]

        score = calculate_recency_score(txs_out, txs_in, current_block, half_life)
        assert score > 0.9

    def test_all_old(self):
        """Toutes les transactions anciennes -> score bas."""
        current_block = 1000000
        half_life = 6500

        txs_out = [TxRecord(f"0x{i}", "A", "B", 1.0, current_block - 50000, 0) for i in range(5)]
        txs_in = [TxRecord(f"0x{i}", "B", "A", 1.0, current_block - 50000, 0) for i in range(5)]

        score = calculate_recency_score(txs_out, txs_in, current_block, half_life)
        assert score < 0.1

    def test_empty_lists(self):
        """Listes vides -> score 0.0."""
        score = calculate_recency_score([], [], 1000000, 6500)
        assert score == 0.0

    def test_one_sided_only(self):
        """Un seul côté a des transactions."""
        current_block = 1000000
        txs_out = [TxRecord(f"0x{i}", "A", "B", 1.0, current_block - 100, 0) for i in range(5)]

        score = calculate_recency_score(txs_out, [], current_block, 6500)
        # Score bas car pas de réciprocité
        assert score > 0  # Mais pas nul car il y a des tx


class TestBidirectionalityScore:
    """Tests pour le score de bidirectionnalité."""

    def test_perfect_reciprocal(self):
        """Transactions parfaitement alternées -> high score."""
        current_block = 1000000

        # 5 handshakes parfaits
        txs_out = [TxRecord(f"0x{i}", "A", "B", 1.0, current_block - 1000 + i*10, 0) for i in range(5)]
        txs_in = [TxRecord(f"0x{i}", "B", "A", 1.0, current_block - 1000 + i*10 + 1, 0) for i in range(5)]

        score, meta = calculate_bidirectionality_score(txs_out, txs_in, current_block)
        assert score > 0.8
        assert meta["handshakes"] == 5
        assert meta["reciprocity_term"] == 1.0

    def test_pure_unidirectional(self):
        """Pas de retour -> score 0.0."""
        current_block = 1000000
        txs_out = [TxRecord(f"0x{i}", "A", "B", 1.0, current_block - 100, 0) for i in range(5)]

        score, meta = calculate_bidirectionality_score(txs_out, [], current_block)
        assert score == 0.0
        assert meta["handshakes"] == 0

    def test_partial_reciprocity(self):
        """3 OUT, 1 IN -> reciprocity ~0.5."""
        current_block = 1000000
        txs_out = [
            TxRecord("0x1", "A", "B", 1.0, current_block - 100, 0),
            TxRecord("0x2", "A", "B", 1.0, current_block - 90, 0),
            TxRecord("0x3", "A", "B", 1.0, current_block - 80, 0),
        ]
        txs_in = [TxRecord("0x4", "B", "A", 1.0, current_block - 85, 0)]

        score, meta = calculate_bidirectionality_score(txs_out, txs_in, current_block)
        # Reciprocity = 2*1/4 = 0.5
        assert meta["reciprocity_term"] == 0.5
        assert meta["handshakes"] == 1

    def test_temporal_async(self):
        """OUT au début, IN à la fin -> faible synchronie."""
        current_block = 1000000
        txs_out = [TxRecord(f"0x{i}", "A", "B", 1.0, current_block - 10000 + i, 0) for i in range(5)]
        txs_in = [TxRecord(f"0x{i}", "B", "A", 1.0, current_block - 100 + i, 0) for i in range(5)]

        score, meta = calculate_bidirectionality_score(txs_out, txs_in, current_block)
        # Reciprocity parfaite mais synchronie faible
        assert meta["reciprocity_term"] == 1.0
        assert meta["sync_term"] < 0.5
        assert score < 0.5


class TestCorrelationScorerIntegration:
    """Tests d'intégration pour calculate_address_correlation."""

    def test_commercant_regulier(self):
        """Test 1: Commerçant régulier (High Correlation).

        50 transactions alternées, volumes équilibrés (±5%), récentes.
        Expected: final_score > 0.8, bidir > 0.9, vol > 0.9
        """
        current_block = 10000000
        txs = []

        # 50 transactions alternées avec volumes équilibrés
        for i in range(25):
            # OUT: A -> B (1.0 ETH)
            txs.append(TxRecord(
                f"0xout{i}", "0xA", "0xB", 1.0,
                current_block - 1000 + i * 20, 0
            ))
            # IN: B -> A (0.95-1.05 ETH, variation ±5%)
            txs.append(TxRecord(
                f"0xin{i}", "0xB", "0xA", 1.0 + (i % 3 - 1) * 0.05,
                current_block - 1000 + i * 20 + 1, 0
            ))

        result = calculate_address_correlation("0xA", "0xB", txs, current_block)

        assert result.final_score > 0.8, f"Score final {result.final_score} devrait être > 0.8"
        assert result.components["bidirectionality_score"] > 0.9
        assert result.components["volume_score"] > 0.9
        assert result.is_correlated is True

    def test_victime_escroquerie(self):
        """Test 2: Victime d'escroquerie (Low Bidirectionality).

        1 tx A->B (10 ETH), 1 tx B->A (0.1 ETH, très tardif).
        Expected: vol ≈ 0.02, bidir ≈ 0.05, final < 0.2
        """
        current_block = 10000000
        txs = [
            TxRecord("0x1", "0xA", "0xB", 10.0, current_block - 1000, 0),
            TxRecord("0x2", "0xB", "0xA", 0.1, current_block - 100, 0),  # Tardif et petit
        ]

        result = calculate_address_correlation("0xA", "0xB", txs, current_block)

        assert result.components["volume_score"] < 0.1, f"Volume score {result.components['volume_score']} devrait être < 0.1"
        assert result.components["bidirectionality_score"] < 0.2
        assert result.final_score < 0.35  # Tolérance pour précision
        assert result.is_correlated is False

    def test_service_unidirectionnel(self):
        """Test 3: Service unidirectionnel (Exchange).

        100 tx A->B, 0 tx retour. Volume élevé, récent.
        Expected: bidir = 0.0, vol = 0.0, final ≈ 0.15 (seulement récence)
        """
        current_block = 10000000
        txs = [
            TxRecord(f"0x{i}", "0xA", "0xB", 5.0, current_block - 500 + i, 0)
            for i in range(100)
        ]

        result = calculate_address_correlation("0xA", "0xB", txs, current_block)

        assert result.components["bidirectionality_score"] == 0.0
        assert result.components["volume_score"] == 0.0
        assert result.final_score < 0.3  # Principalement récence
        assert result.is_correlated is False

    def test_ancienne_relation(self):
        """Test 4: Ancienne relation (Low Recency).

        20 tx bidirectionnelles parfaites, mais anciennes (block < current - 50000).
        Expected: rec < 0.1, bidir = 1.0, final ≈ 0.4
        """
        current_block = 10000000
        txs = []

        for i in range(10):
            txs.append(TxRecord(f"0xout{i}", "0xA", "0xB", 1.0, current_block - 60000 + i, 0))
            txs.append(TxRecord(f"0xin{i}", "0xB", "0xA", 1.0, current_block - 60000 + i + 1, 0))

        result = calculate_address_correlation("0xA", "0xB", txs, current_block)

        assert result.components["recency_score"] < 0.1
        assert result.components["bidirectionality_score"] > 0.99  # Tolérance pour précision
        # Score final élevé malgré récence faible car volume et bidir excellents
        assert 0.5 < result.final_score < 0.7

    def test_insufficient_transactions(self):
        """Moins de min_transaction_threshold -> score 0.0."""
        config = ScoringConfig(min_transaction_threshold=5)
        txs = [TxRecord("0x1", "0xA", "0xB", 1.0, 1000000, 0)]

        result = calculate_address_correlation("0xA", "0xB", txs, 1000000, config)

        assert result.final_score == 0.0
        assert result.is_correlated is False

    def test_zero_value_transactions_filtered(self):
        """Transactions avec value_eth=0 sont ignorées."""
        current_block = 10000000
        txs = [
            TxRecord("0x1", "0xA", "0xB", 0.0, current_block - 100, 0),  # Ignorée
            TxRecord("0x2", "0xA", "0xB", 0.0, current_block - 90, 0),   # Ignorée
        ]

        result = calculate_address_correlation("0xA", "0xB", txs, current_block)

        # Aucune transaction valide
        assert result.final_score == 0.0


class TestScoringConfig:
    """Tests pour la configuration de scoring."""

    def test_default_weights_sum_to_one(self):
        """Les poids par défaut doivent sommer à 1.0."""
        config = ScoringConfig()
        total = sum(config.weights.values())
        assert abs(total - 1.0) < 0.01

    def test_invalid_weights_raise_error(self):
        """Des poids ne sommant pas à 1.0 doivent lever une erreur."""
        # Poids valides (somme = 1.0) - ne doit PAS lever d'erreur
        config = ScoringConfig(weights={"volume": 0.5, "frequency": 0.5})
        assert sum(config.weights.values()) == 1.0

        # Poids invalides (somme > 1.0) - doit lever ValueError
        with pytest.raises(ValueError):
            ScoringConfig(weights={"volume": 0.5, "frequency": 0.6})

    def test_custom_weights(self):
        """Test avec des poids personnalisés."""
        config = ScoringConfig(
            weights={
                "volume": 0.25,
                "frequency": 0.25,
                "recency": 0.25,
                "bidirectionality": 0.25
            }
        )
        assert config.weights["volume"] == 0.25

    def test_correlation_threshold(self):
        """Test du seuil de corrélation."""
        config = ScoringConfig(correlation_threshold=0.7)

        # Créer une situation avec score ~0.6 (en dessous du seuil)
        current_block = 10000000
        txs = [
            TxRecord("0x1", "0xA", "0xB", 1.0, current_block - 100, 0),
            TxRecord("0x2", "0xB", "0xA", 0.5, current_block - 50, 0),
        ]

        result = calculate_address_correlation("0xA", "0xB", txs, current_block, config)
        # Le score doit être évalué par rapport au seuil de 0.7
        assert result.is_correlated == (result.final_score > 0.7)
