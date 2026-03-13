# Plan d'Implémentation des Correctifs

**Suite à l'Audit du Système de Scoring**
**Date** : 11 Mars 2026
**Durée estimée** : 3-4 jours de développement
**Priorité** : P0 (Critique) - P3 (Faible)

---

## 🎯 Vue d'Ensemble

```
Phase 1 (Jour 1) : Correctifs Critiques (Bugs)
Phase 2 (Jour 2) : Recalibration Mathématique
Phase 3 (Jour 3) : Améliorations Structurelles
Phase 4 (Jour 4) : Tests et Validation
```

---

## 📋 PHASE 1 : Correctifs Critiques (P0)

### 🔴 P0-001 : Correction du Double Calcul du Total Score

**Problème** : `RelationshipScore.__post_init__` recalcule le total avec une formule incorrecte.

**Fichier** : `src/domain/models.py`

**Implementation** :

```python
# AVANT (BUG)
@dataclass
class RelationshipScore:
    def __post_init__(self):
        interaction = 0.05 * self.direct_score * self.indirect_score
        total = self.direct_score + self.indirect_score + interaction  # ❌ Mauvais
        object.__setattr__(self, 'total_score', min(total * 100, 100.0))

# APRÈS (CORRECT)
@dataclass
class RelationshipScore:
    def __post_init__(self):
        # Utiliser les poids dynamiques comme dans TemporalScorer
        tx_count = self.metrics.get('tx_count', 0)
        if tx_count < 3:
            w_dir, w_ind = 0.4, 0.55
        else:
            w_dir, w_ind = 0.7, 0.25

        interaction = 0.05 * self.direct_score * self.indirect_score
        total = w_dir * self.direct_score + w_ind * self.indirect_score + interaction
        object.__setattr__(self, 'total_score', min(total * 100, 100.0))
```

**Tests** :
```python
def test_total_score_with_weights():
    # tx_count < 3
    rel = RelationshipScore(..., direct_score=0.5, indirect_score=0.3, metrics={'tx_count': 2})
    expected = (0.4 * 0.5 + 0.55 * 0.3 + 0.05 * 0.5 * 0.3) * 100
    assert abs(rel.total_score - expected) < 0.01

    # tx_count >= 3
    rel = RelationshipScore(..., direct_score=0.5, indirect_score=0.3, metrics={'tx_count': 5})
    expected = (0.7 * 0.5 + 0.25 * 0.3 + 0.05 * 0.5 * 0.3) * 100
    assert abs(rel.total_score - expected) < 0.01
```

**Temps estimé** : 30 minutes

---

### 🔴 P0-002 : Correction de la Normalisation Sigmoïde

**Problème** : Score indirect de 0.18 même sans aucun chemin trouvé.

**Fichier** : `src/services/scoring/temporal_scorer.py`

**Implementation** :

```python
def _compute_indirect_score(self, main_address: str, target: str) -> float:
    # ... code existant ...

    # Si aucun chemin trouvé, retourner 0 explicitement
    if total_contribution == 0.0:
        return 0.0

    # Normalisation sigmoïde uniquement si des chemins existent
    kappa = self.config.kappa_sigmoid
    tau_med = self.config.tau_median_ref
    normalized = 1.0 / (1.0 + math.exp(-kappa * (total_contribution - tau_med)))
    return min(normalized, 1.0)
```

**Tests** :
```python
def test_indirect_score_zero_when_no_path():
    g = nx.MultiDiGraph()
    g.add_edge('A', 'B', weight=10.0)  # Lien direct uniquement
    scorer = TemporalScorer(g)
    score = scorer.score('A', 'B')
    assert score.indirect == 0.0  # Pas de chemin indirect possible
```

**Temps estimé** : 15 minutes

---

### 🔴 P0-003 : Invalidation du Cache de Référence

**Problème** : Le cache des volumes de référence devient obsolète quand le graphe change.

**Fichier** : `src/services/scoring/temporal_scorer.py`

**Implementation** :

```python
class TemporalScorer(SimilarityStrategy):
    def __init__(self, graph: nx.MultiDiGraph, config: Optional[TemporalScorerConfig] = None):
        super().__init__(graph)
        self.config = config or TemporalScorerConfig()
        self._ref_stats_cache: Dict[str, Dict] = {}
        self._current_block: Optional[int] = None
        self._graph_snapshot = self._compute_graph_hash()  # NOUVEAU

    def _compute_graph_hash(self) -> str:
        """Calcule un hash simple du graphe pour détecter les changements."""
        edges_str = str(sorted(self.graph.edges(data=True), key=lambda x: (x[0], x[1])))
        return str(hash(edges_str))

    def _is_cache_valid(self) -> bool:
        """Vérifie si le cache correspond au graphe actuel."""
        current_hash = self._compute_graph_hash()
        return current_hash == self._graph_snapshot

    def score(self, main_address: str, node: str) -> NodeScore:
        # Invalider le cache si le graphe a changé
        if not self._is_cache_valid():
            self._ref_stats_cache.clear()
            self._current_block = None
            self._graph_snapshot = self._compute_graph_hash()

        # ... reste de la méthode ...
```

**Temps estimé** : 45 minutes

---

## 📋 PHASE 2 : Recalibration Mathématique (P1)

### 🟠 P1-001 : Rééquilibrage des Poids des Composantes

**Problème** : Équilibre (10%) sous-valorisé par rapport à son importance.

**Fichier** : `src/services/scoring/temporal_scorer.py`

**Implementation** :

```python
class TemporalScorer(SimilarityStrategy):
    # ANCIENS POIDS
    # W_INTENSITE = 0.50
    # W_RECENCE = 0.25
    # W_SYNC = 0.15
    # W_EQUILIBRE = 0.10

    # NOUVEAUX POIDS (rééquilibrés)
    W_INTENSITE = 0.40      # -10% : Laisser place à l'équilibre
    W_EQUILIBRE = 0.25      # +15% : Valoriser la bidirectionnalité
    W_RECENCE = 0.20        # -5% : Moins dominant
    W_SYNC = 0.15           # Inchangé

    # Vérification : 0.40 + 0.25 + 0.20 + 0.15 = 1.0 ✓
```

**Impact** : Les relations bidirectionnelles (échanges économiques) seront mieux valorisées.

**Temps estimé** : 10 minutes

---

### 🟠 P1-002 : Recalibration de la Saturation Fréquentielle

**Problème** : Saturation trop rapide (τ = 5.0).

**Fichier** : `src/services/scoring/temporal_scorer.py`

**Implementation** :

```python
@dataclass
class TemporalScorerConfig:
    # ANCIEN
    # tau: float = 5.0

    # NOUVEAU (saturation plus lente)
    tau: float = 15.0  # Permet de distinguer 1, 5, 10, 50 transactions
```

**Table comparative** :

| N Tx | τ=5.0 (ancien) | τ=15.0 (nouveau) | Différence |
|------|----------------|------------------|------------|
| 1 | 18% | 6% | -12 pts |
| 5 | 63% | 28% | -35 pts |
| 10 | 87% | 49% | -38 pts |
| 20 | 98% | 74% | -24 pts |
| 50 | 100% | 96% | -4 pts |

**Temps estimé** : 5 minutes

---

### 🟠 P1-003 : Normalisation du Volume Absolu

**Problème** : Le v_ref dépend de l'adresse principale (biais relatif).

**Fichier** : `src/services/scoring/temporal_scorer.py`

**Implementation** :

```python
@dataclass
class TemporalScorerConfig:
    # Option de normalisation
    volume_normalization_mode: str = "absolute"  # "absolute" ou "relative"

    # Pour la normalisation absolue, référentiel fixe
    absolute_v_ref: float = 100.0  # 100 ETH comme référence globale

def _get_reference_volume(self, main_address: str) -> float:
    if self.config.volume_normalization_mode == "absolute":
        return self.config.absolute_v_ref

    # Mode relatif (ancien comportement)
    # ... code existant ...

def _calc_intensite(self, v_total: float, n_total: int, v_ref: float) -> float:
    # Ajouter une échelle logarithmique améliorée
    if v_total <= 0 or v_ref <= 0:
        return 0.0

    # Normalisation logarithmique avec protection pour micro-volumes
    if v_total < 0.01:  # < 0.01 ETH
        # Échelle linéaire pour les micro-volumes
        volume_factor = min(v_total / 0.01 * 0.1, 0.1)
    else:
        # Échelle logarithmique standard
        volume_factor = min(
            math.log(v_total) / math.log(v_ref),  # ln(v) au lieu de ln(1+v)
            1.0
        )

    freq_factor = 1.0 - math.exp(-n_total / self.config.tau)
    return volume_factor * freq_factor
```

**Temps estimé** : 1 heure

---

### 🟠 P1-004 : Amélioration de la Synchronie Temporelle

**Problème** : Fenêtre fixe de 100 blocs (~20 min) trop stricte.

**Fichier** : `src/services/scoring/temporal_scorer.py`

**Implementation** :

```python
def _calc_synchronie(self, tx_out: List[Dict], tx_in: List[Dict]) -> float:
    if not tx_out or not tx_in:
        return 0.0

    # Convertir en blocs avec timestamps réels
    out_txs = []
    for tx in tx_out:
        block = self._approximate_block_number(tx.get("time"))
        if block is not None:
            out_txs.append((block, tx.get("weight", 0)))

    in_txs = []
    for tx in tx_in:
        block = self._approximate_block_number(tx.get("time"))
        if block is not None:
            in_txs.append((block, tx.get("weight", 0)))

    if not out_txs or not in_txs:
        return 0.0

    # Fenêtre dynamique basée sur le volume
    # Gros volumes = fenêtre plus grande (déplacements de fonds)
    # Petits volumes = fenêtre plus petite (arbitrages)
    avg_volume = sum(tx[1] for tx in out_txs + in_txs) / (len(out_txs) + len(in_txs))

    if avg_volume > 100:  # > 100 ETH
        delta = 500  # ~1h40 (déplacement de fonds)
    elif avg_volume > 10:  # > 10 ETH
        delta = 200  # ~40 min
    else:
        delta = 100  # ~20 min (arbitrage rapide)

    # Calcul pondéré par le volume
    sync_score = 0.0
    total_weight = 0.0

    for out_block, out_weight in out_txs:
        best_match = 0.0
        for in_block, in_weight in in_txs:
            gap = abs(out_block - in_block)
            if gap <= delta:
                # Score dégressif avec la distance temporelle
                match_score = (1 - gap / delta) * min(out_weight, in_weight)
                best_match = max(best_match, match_score)

        sync_score += best_match
        total_weight += out_weight

    return sync_score / total_weight if total_weight > 0 else 0.0
```

**Temps estimé** : 1.5 heures

---

## 📋 PHASE 3 : Améliorations Structurelles (P2)

### 🟡 P2-001 : Détection des Patterns de Transaction

**Nouveau fichier** : `src/services/scoring/pattern_detector.py`

**Implementation** :

```python
"""Détection de patterns de transactions pour améliorer le scoring."""

from typing import List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

class TransactionPattern(Enum):
    ROUND_TRIP = "round_trip"           # A -> B -> A (même montant)
    CHAIN = "chain"                      # A -> B -> C
    SPLIT = "split"                      # A -> B, A -> C (même temps)
    MERGE = "merge"                      # A -> C, B -> C (même temps)
    RECURRING = "recurring"              # Transactions régulières

@dataclass
class PatternMatch:
    pattern: TransactionPattern
    confidence: float
    description: str
    transactions: List[str]  # tx_hashes

class PatternDetector:
    """Détecte les patterns de transactions entre deux adresses."""

    def detect_patterns(self, tx_out: List[Dict], tx_in: List[Dict]) -> List[PatternMatch]:
        patterns = []

        # Détection Round-Trip
        round_trip = self._detect_round_trip(tx_out, tx_in)
        if round_trip:
            patterns.append(round_trip)

        # Détection Transactions Récurrentes
        recurring = self._detect_recurring(tx_out + tx_in)
        if recurring:
            patterns.append(recurring)

        return patterns

    def _detect_round_trip(self, tx_out: List[Dict], tx_in: List[Dict]) -> Optional[PatternMatch]:
        """
        Détecte un pattern round-trip (A envoie à B, B renvoie le même montant).
        Indicateur fort de même entité.
        """
        for out_tx in tx_out:
            out_value = out_tx.get("weight", 0)
            out_time = self._parse_time(out_tx.get("time"))

            for in_tx in tx_in:
                in_value = in_tx.get("weight", 0)
                in_time = self._parse_time(in_tx.get("time"))

                # Même montant (±5%) et retour dans les 7 jours
                if abs(in_value - out_value) / out_value < 0.05:
                    time_diff = (in_time - out_time).days if in_time and out_time else 999
                    if 0 < time_diff <= 7:
                        return PatternMatch(
                            pattern=TransactionPattern.ROUND_TRIP,
                            confidence=0.9,
                            description=f"Round-trip: {out_value:.2f} ETH retourné en {time_diff} jours",
                            transactions=[out_tx.get("hash"), in_tx.get("hash")]
                        )
        return None

    def _detect_recurring(self, transactions: List[Dict]) -> Optional[PatternMatch]:
        """
        Détecte des transactions récurrentes (même montant, intervalle régulier).
        Indicateur de paiement récurrent (salaire, facture).
        """
        if len(transactions) < 3:
            return None

        # Grouper par montant similaire
        amount_groups = {}
        for tx in transactions:
            amount = tx.get("weight", 0)
            # Arrondir pour grouper les montants similaires
            key = round(amount, 2)
            if key not in amount_groups:
                amount_groups[key] = []
            amount_groups[key].append(tx)

        # Chercher des groupes avec ≥3 transactions
        for amount, txs in amount_groups.items():
            if len(txs) >= 3:
                return PatternMatch(
                    pattern=TransactionPattern.RECURRING,
                    confidence=min(0.5 + len(txs) * 0.1, 0.9),
                    description=f"Paiement récurrent: {amount:.2f} ETH ({len(txs)} fois)",
                    transactions=[tx.get("hash") for tx in txs]
                )

        return None
```

**Intégration dans TemporalScorer** :

```python
def _compute_direct_score(self, main_address: str, node: str) -> Dict[str, float]:
    # ... code existant ...

    # Détection de patterns
    from src.services.scoring.pattern_detector import PatternDetector
    detector = PatternDetector()
    patterns = detector.detect_patterns(tx_out, tx_in)

    # Bonus pour les patterns détectés
    pattern_bonus = 0.0
    for pattern in patterns:
        if pattern.pattern == TransactionPattern.ROUND_TRIP:
            pattern_bonus += 0.1 * pattern.confidence  # +10% max
        elif pattern.pattern == TransactionPattern.RECURRING:
            pattern_bonus += 0.05 * pattern.confidence  # +5% max

    s_direct = (
        self.W_INTENSITE * s_intensite +
        self.W_RECENCE * s_recence +
        self.W_SYNC * s_sync +
        self.W_EQUILIBRE * s_equilibre +
        pattern_bonus  # NOUVEAU
    )

    return {
        # ... champs existants ...
        'patterns': [p.pattern.value for p in patterns],  # NOUVEAU
        'pattern_bonus': pattern_bonus,  # NOUVEAU
    }
```

**Temps estimé** : 3 heures

---

### 🟡 P2-002 : Scoring de Confiance Amélioré

**Problème** : La confiance est binaire (low/medium/high) basée sur des seuils simples.

**Nouvelle approche** : Score de confiance continu basé sur plusieurs facteurs.

**Fichier** : `src/services/scoring/temporal_scorer.py`

```python
def _compute_confidence_score(self, tx_count: int, v_total: float,
                              s_recence: float, patterns: List[str]) -> Tuple[str, float]:
    """
    Calcule un score de confiance détaillé.

    Returns:
        (niveau, score_continu) : niveau ∈ {'low', 'medium', 'high'}
    """
    # Facteurs de confiance
    f_volume = min(v_total / 10.0, 1.0)  # 10 ETH = confiance max sur volume
    f_count = min(tx_count / 10.0, 1.0)   # 10 tx = confiance max sur fréquence
    f_recency = s_recence  # Récence déjà normalisée [0-1]
    f_pattern = 0.2 if patterns else 0.0  # Bonus si patterns détectés

    # Score pondéré
    confidence_score = (
        0.3 * f_volume +
        0.2 * f_count +
        0.3 * f_recency +
        0.2 * (1.0 if tx_count >= 3 else tx_count / 3.0) +  # Consistance
        f_pattern
    )

    confidence_score = min(confidence_score, 1.0)

    # Mapping en niveau
    if confidence_score >= 0.7:
        level = "high"
    elif confidence_score >= 0.4:
        level = "medium"
    else:
        level = "low"

    return level, round(confidence_score, 2)
```

**Temps estimé** : 45 minutes

---

## 📋 PHASE 4 : Tests et Validation (P3)

### 🟢 P3-001 : Suite de Tests de Non-Regression

**Fichier** : `tests/test_scoring_fixes.py`

```python
"""Tests de validation des correctifs du scoring."""

import pytest
import networkx as nx
from src.services.scoring.temporal_scorer import TemporalScorer, TemporalScorerConfig
from src.domain.models import RelationshipScore, Address


class TestCriticalFixes:
    """Tests pour les bugs critiques (P0)."""

    def test_indirect_score_is_zero_when_no_path(self):
        """P0-002 : Score indirect doit être 0 sans chemin."""
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


class TestCalibration:
    """Tests pour la recalibration (P1)."""

    def test_micro_transactions_distinguishable(self):
        """P1-003 : 0.01 ETH et 0.1 ETH doivent être distinguables."""
        g = nx.MultiDiGraph()

        # Cas 1 : 0.01 ETH
        g.add_edge('A', 'B1', weight=0.01, time='2024-03-01T10:00:00Z')

        # Cas 2 : 0.1 ETH
        g.add_edge('A', 'B2', weight=0.1, time='2024-03-01T10:00:00Z')

        scorer = TemporalScorer(g, TemporalScorerConfig(
            volume_normalization_mode='absolute',
            absolute_v_ref=100.0
        ))

        score1 = scorer.score('A', 'B1')
        score2 = scorer.score('A', 'B2')

        # Écart d'au moins 20% entre les scores
        diff = abs(score1.direct - score2.direct)
        assert diff > 0.05, \
            f"Scores too close: {score1.direct:.4f} vs {score2.direct:.4f} (diff={diff:.4f})"

    def test_unidirectional_not_overly_penalized(self):
        """P1-001 : Relation unidirectionnelle forte doit avoir score > 50."""
        g = nx.MultiDiGraph()

        # 10 transactions de 10 ETH (salaire unidirectionnel)
        for i in range(10):
            g.add_edge('A', 'B', weight=10.0,
                      time=f'2024-03-{i+1:02d}T10:00:00Z')

        scorer = TemporalScorer(g)
        score = scorer.score('A', 'B')

        # Avec les nouveaux poids (W_EQUILIBRE=0.25), une relation
        # unidirectionnelle forte doit quand même avoir un bon score
        assert score.total > 40, \
            f"Unidirectional relationship undervalued: {score.total}"

    def test_recency_over_volume(self):
        """P1-004 : Récence prime sur le volume."""
        from datetime import datetime, timedelta

        g = nx.MultiDiGraph()
        now = datetime.now()

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


class TestCacheInvalidation:
    """Tests pour l'invalidation du cache (P0-003)."""

    def test_cache_invalidated_when_graph_changes(self):
        """Le cache doit être invalidé quand le graphe change."""
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
```

**Temps estimé** : 2 heures

---

### 🟢 P3-002 : Validation sur Données Réelles

**Script de validation** : `scripts/validate_scoring.py`

```python
#!/usr/bin/env python3
"""
Script de validation du scoring sur des cas connus.
"""

import json
from src.services.correlation import CorrelationService
from src.adapters.dune import DuneAdapter
from src.domain.models import Address

# Cas de test connus (à remplir avec des données réelles)
TEST_CASES = [
    {
        "name": "Même entité (cold/hot wallet)",
        "addr1": "0x...",  # Cold wallet
        "addr2": "0x...",  # Hot wallet (même propriétaire)
        "expected_score": "> 0.80",
        "expected_classification": "entity_unique"
    },
    {
        "name": "Relation économique (client/fournisseur)",
        "addr1": "0x...",  # Client
        "addr2": "0x...",  # Fournisseur
        "expected_score": "0.60 - 0.85",
        "expected_classification": "economic_partner"
    },
    {
        "name": "Pas de relation (random)",
        "addr1": "0x...",
        "addr2": "0x...",  # Adresse aléatoire
        "expected_score": "< 0.30",
        "expected_classification": "no_correlation"
    },
]

def run_validation():
    """Exécute les cas de test et génère un rapport."""
    results = []

    for case in TEST_CASES:
        print(f"\nTesting: {case['name']}")

        # Build graph and score
        service = CorrelationService(DuneAdapter())
        result = service.calculate_score(
            Address(case['addr1']),
            Address(case['addr2']),
            expansion_depth=2,
            top_n=5
        )

        # Check expectations
        passed = True
        errors = []

        # TODO: Implémenter la logique de validation

        results.append({
            "case": case['name'],
            "score": result.score,
            "passed": passed,
            "errors": errors
        })

    # Générer rapport
    with open('validation_report.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\n" + "="*60)
    print(f"Validation complete: {sum(r['passed'] for r in results)}/{len(results)} passed")

if __name__ == "__main__":
    run_validation()
```

**Temps estimé** : 2 heures (création + exécution)

---

## 📊 Résumé du Planning

| Phase | Tâches | Durée | Priorité |
|-------|--------|-------|----------|
| **Jour 1** | P0-001, P0-002, P0-003 | 1.5h | 🔴 Critique |
| **Jour 2** | P1-001, P1-002, P1-003, P1-004 | 3.5h | 🟠 Haute |
| **Jour 3** | P2-001, P2-002 | 3.75h | 🟡 Moyenne |
| **Jour 4** | P3-001, P3-002 | 4h | 🟢 Basse |
| **Total** | | **~13h** | |

---

## ✅ Checklist de Validation Finale

Avant de merger les changements :

- [ ] Tous les tests existants passent (`pytest tests/`)
- [ ] Nouveaux tests de non-regression passent
- [ ] Documentation mise à jour (docstrings, comments)
- [ ] Validation sur données réelles effectuée
- [ ] Comportement vérifié pour les cas limites :
  - [ ] Micro-transactions (< 0.01 ETH)
  - [ ] Transactions uniques
  - [ ] Relations unidirectionnelles
  - [ ] Adresses avec une seule relation
  - [ ] Graphes avec expansion multiple

---

## 🚀 Notes d'Implémentation

### Ordre des Opérations

1. **Commencer par P0** : Ces bugs affectent tous les scores actuels
2. **P1 en parallèle** : Peuvent être développés sur des branches séparées
3. **P2 après validation de P1** : Dépendent de la stabilité du scoring
4. **P3 en continu** : Tests à ajouter au fur et à mesure

### Points d'Attention

- **Backward compatibility** : Les changements de paramètres (P1) changeront les scores. Documenter les différences attendues.
- **Performance** : La détection de patterns (P2-001) ajoute du calcul. Profiler sur de grands graphes.
- **Cache** : L'invalidation du cache (P0-003) peut impacter les performances. Surveiller les temps de réponse.

### Communication

- Documenter les changements de scores dans le CHANGELOG
- Prévenir les utilisateurs de l'impact sur les analyses historiques
- Fournir un script de migration si nécessaire

---

*Plan créé le 11 Mars 2026*
*Basé sur l'audit du système de scoring*
