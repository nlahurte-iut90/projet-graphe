"""Tests de validation des correctifs du scoring.

Ce module valide les corrections des bugs critiques (P0) et
les recalibrations (P1) du système de scoring temporel.
"""

import pytest
import networkx as nx
from datetime import datetime, timedelta

from src.services.scoring.temporal_scorer import TemporalScorer, TemporalScorerConfig
from src.domain.models import RelationshipScore, Address


class TestCriticalFixes:
    """Tests pour les bugs critiques (P0)."""

    def test_indirect_score_is_zero_when_no_path(self):
        """P0-002 : Score indirect doit être 0 sans chemin indirect."""
        g = nx.MultiDiGraph()
        g.add_edge('A', 'B', weight=10.0, time='2024-03-01T10:00:00Z')

        scorer = TemporalScorer(g)
        score = scorer.score('A', 'B')

        assert score.indirect == 0.0, \
            f"Indirect score should be 0, got {score.indirect}"

    def test_total_score_uses_correct_weights(self):
        """P0-001 : Le total_score doit utiliser les poids dynamiques."""
        g = nx.MultiDiGraph()
        g.add_edge('A', 'B', weight=50.0, time='2024-03-01T10:00:00Z')
        g.add_edge('B', 'A', weight=30.0, time='2024-03-01T10:05:00Z')

        scorer = TemporalScorer(g)
        node_score = scorer.score('A', 'B')

        # Créer un RelationshipScore et vérifier le calcul
        addr = Address('0xabc')
        rel = RelationshipScore(
            source=addr,
            target=addr,
            direct_score=node_score.direct,
            indirect_score=node_score.indirect,
            metrics={'tx_count': 2}
        )

        # tx_count=2 (< 3) donc w_dir=0.4, w_ind=0.55
        expected = (0.4 * node_score.direct +
                   0.55 * node_score.indirect +
                   0.05 * node_score.direct * node_score.indirect) * 100

        assert abs(rel.total_score - expected) < 0.1, \
            f"Expected {expected}, got {rel.total_score}"

    def test_cache_invalidated_when_graph_changes(self):
        """P0-003 : Le cache doit être invalidé quand le graphe change."""
        g = nx.MultiDiGraph()
        g.add_edge('A', 'B', weight=10.0, time='2024-03-01T10:00:00Z')

        scorer = TemporalScorer(g)

        # Premier scoring (remplit le cache)
        score1 = scorer.score('A', 'B')
        v_ref_1 = scorer._get_reference_volume('A')

        # Modification du graphe
        g.add_edge('A', 'C', weight=1000.0, time='2024-03-01T11:00:00Z')

        # Second scoring (cache devrait être invalidé)
        score2 = scorer.score('A', 'B')
        v_ref_2 = scorer._get_reference_volume('A')

        # Le volume de référence doit avoir changé
        assert v_ref_1 != v_ref_2, \
            f"Cache not invalidated: v_ref stayed at {v_ref_1}"


class TestCalibration:
    """Tests pour la recalibration (P1)."""

    def test_new_weights_balance_emphasized(self):
        """P1-001 : L'équilibre a maintenant plus de poids (25%)."""
        g = nx.MultiDiGraph()

        # Relation bidirectionnelle équilibrée
        g.add_edge('A', 'B', weight=50.0, time='2024-03-01T10:00:00Z')
        g.add_edge('B', 'A', weight=50.0, time='2024-03-01T10:05:00Z')

        scorer = TemporalScorer(g)
        score = scorer.score('A', 'B')

        # Avec les nouveaux poids, l'équilibre devrait être élevé
        assert score.equilibre > 0.2, \
            f"Balance score should be significant, got {score.equilibre}"

    def test_tau_saturation_slower(self):
        """P1-002 : tau=15 permet de mieux distinguer les fréquences."""
        g1 = nx.MultiDiGraph()
        g5 = nx.MultiDiGraph()
        g10 = nx.MultiDiGraph()

        base_time = '2024-03-01T10:00:00Z'

        # 1 transaction
        g1.add_edge('A', 'B1', weight=10.0, time=base_time)

        # 5 transactions (même timestamp pour isoler l'effet de la fréquence)
        for i in range(5):
            g5.add_edge('A', 'B5', weight=10.0, time=base_time)

        # 10 transactions (même timestamp pour isoler l'effet de la fréquence)
        for i in range(10):
            g10.add_edge('A', 'B10', weight=10.0, time=base_time)

        config = TemporalScorerConfig(tau=15.0)
        scorer1 = TemporalScorer(g1, config)
        scorer5 = TemporalScorer(g5, config)
        scorer10 = TemporalScorer(g10, config)

        score1 = scorer1.score('A', 'B1')
        score5 = scorer5.score('A', 'B5')
        score10 = scorer10.score('A', 'B10')

        # Les scores d'intensité doivent augmenter avec le nombre de transactions
        # (le facteur de fréquence joue plus avec tau=15)
        assert score1.intensite < score5.intensite < score10.intensite, \
            f"Intensity should increase with tx count: {score1.intensite}, {score5.intensite}, {score10.intensite}"

    def test_absolute_volume_normalization(self):
        """P1-003 : Mode absolu utilise une référence fixe."""
        g = nx.MultiDiGraph()
        g.add_edge('A', 'B', weight=10.0, time='2024-03-01T10:00:00Z')

        config = TemporalScorerConfig(
            volume_normalization_mode='absolute',
            absolute_v_ref=100.0
        )
        scorer = TemporalScorer(g, config)
        score = scorer.score('A', 'B')

        # Le volume de référence doit être fixe à 100
        v_ref = scorer._get_reference_volume('A')
        assert v_ref == 100.0, \
            f"Absolute v_ref should be 100.0, got {v_ref}"

    def test_micro_transactions_distinguishable(self):
        """P1-003 : 0.01 ETH et 0.1 ETH doivent être distinguables."""
        g1 = nx.MultiDiGraph()
        g2 = nx.MultiDiGraph()

        base_time = '2024-03-01T10:00:00Z'

        # Cas 1 : 0.01 ETH - relation unique
        g1.add_edge('A', 'B1', weight=0.01, time=base_time)

        # Cas 2 : 0.1 ETH - relation unique
        g2.add_edge('A', 'B2', weight=0.1, time=base_time)

        # Utiliser une référence très basse pour maximiser la sensibilité aux micro-volumes
        scorer1 = TemporalScorer(g1, TemporalScorerConfig(
            volume_normalization_mode='absolute',
            absolute_v_ref=1.0  # Référence à 1 ETH pour distinguer les micro-volumes
        ))
        scorer2 = TemporalScorer(g2, TemporalScorerConfig(
            volume_normalization_mode='absolute',
            absolute_v_ref=1.0
        ))

        score1 = scorer1.score('A', 'B1')
        score2 = scorer2.score('A', 'B2')

        # Le score d'intensité doit être proportionnel au volume
        # 0.1 ETH doit avoir un score ~10x supérieur à 0.01 ETH
        ratio = score2.intensite / max(score1.intensite, 0.0001)
        assert ratio > 5, \
            f"Intensity ratio too small: {ratio:.2f} (scores: {score1.intensite:.4f} vs {score2.intensite:.4f})"

    def test_unidirectional_not_overly_penalized(self):
        """P1-001 : Relation unidirectionnelle forte doit avoir un score décent."""
        g = nx.MultiDiGraph()

        base_time = '2024-03-01T10:00:00Z'

        # 10 transactions de 10 ETH (salaire unidirectionnel, même jour)
        for i in range(10):
            g.add_edge('A', 'B', weight=10.0, time=base_time)

        scorer = TemporalScorer(g)
        score = scorer.score('A', 'B')

        # Une relation unidirectionnelle forte doit avoir un bon score d'intensité
        # L'équilibre est 0 (pas de retour), mais l'intensité doit être élevée
        assert score.intensite > 0.3, \
            f"Unidirectional intensity too low: {score.intensite}"
        assert score.total > 20, \
            f"Unidirectional relationship undervalued: {score.total}"

    def test_recency_over_volume(self):
        """P1-004 : Récence prime sur le volume."""
        now = datetime.now()

        g = nx.MultiDiGraph()

        # Tx récente de 0.1 ETH (hier)
        g.add_edge('A', 'B1', weight=0.1,
                  time=(now - timedelta(days=1)).isoformat())

        # Tx vieille de 10 ETH (il y a 1 an)
        g.add_edge('A', 'B2', weight=10.0,
                  time=(now - timedelta(days=365)).isoformat())

        scorer = TemporalScorer(g)
        score1 = scorer.score('A', 'B1')
        score2 = scorer.score('A', 'B2')

        # La récence de B1 doit être meilleure malgré le volume faible
        assert score1.recence > score2.recence, \
            f"Recency should dominate: B1={score1.recence}, B2={score2.recence}"

    def test_synchronie_dynamic_window(self):
        """P1-004 : Fenêtre de synchronie dynamique selon le volume."""
        g_small = nx.MultiDiGraph()
        g_large = nx.MultiDiGraph()

        # Petit volume: fenêtre de 100 blocs
        g_small.add_edge('A', 'B', weight=1.0, time='2024-03-01T10:00:00Z')
        g_small.add_edge('B', 'A', weight=1.0, time='2024-03-01T10:15:00Z')  # 15 min plus tard

        # Gros volume: fenêtre de 500 blocs
        g_large.add_edge('A', 'B', weight=200.0, time='2024-03-01T10:00:00Z')
        g_large.add_edge('B', 'A', weight=200.0, time='2024-03-01T10:15:00Z')  # 15 min plus tard

        scorer_small = TemporalScorer(g_small)
        scorer_large = TemporalScorer(g_large)

        score_small = scorer_small.score('A', 'B')
        score_large = scorer_large.score('A', 'B')

        # Les gros volumes ont une meilleure synchronie grâce à la fenêtre plus large
        assert score_large.synchronie >= score_small.synchronie, \
            f"Large volume should have better sync: small={score_small.synchronie}, large={score_large.synchronie}"


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_self_score_is_perfect(self):
        """Le score d'une adresse avec elle-même doit être parfait."""
        g = nx.MultiDiGraph()
        g.add_node('A')

        scorer = TemporalScorer(g)
        score = scorer.score('A', 'A')

        assert score.total == 100.0
        assert score.direct == 1.0
        assert score.confidence == "high"

    def test_no_edges_zero_score(self):
        """Sans transactions, le score doit être nul."""
        g = nx.MultiDiGraph()
        g.add_node('A')
        g.add_node('B')

        scorer = TemporalScorer(g)
        score = scorer.score('A', 'B')

        assert score.direct == 0.0
        assert score.total == 0.0

    def test_case_insensitive_addresses(self):
        """Les adresses Ethereum sont insensibles à la casse."""
        g = nx.MultiDiGraph()
        g.add_edge('0xAbCdEf', '0xFeDcBa', weight=10.0, time='2024-03-01T10:00:00Z')

        scorer = TemporalScorer(g)
        score1 = scorer.score('0xabcdef', '0xfedcba')
        score2 = scorer.score('0xABCDEF', '0xFEDCBA')

        assert score1.total == score2.total
