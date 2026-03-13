# Audit Critique du Système de Scoring de Corrélation

## Résumé Exécutif

Le système de scoring implémente une approche sophistiquée basée sur 4 dimensions (intensité, récence, synchronie, équilibre) combinée avec un algorithme de Katz temporel. **Score global : 6.5/10** - Bonne base théorique mais plusieurs failles critiques à corriger.

---

## 1. Architecture et Design

### 1.1 Forces

| Aspect | Évaluation | Commentaire |
|--------|-----------|-------------|
| **Modularité** | ✅ Bonne | Séparation claire entre score direct/indirect |
| **Configurabilité** | ✅ Bonne | `TemporalScorerConfig` permet l'ajustement fin |
| **Extensibilité** | ✅ Bonne | Pattern Strategy pour différents scorers |
| **Normalisation** | ⚠️ Partielle | Gestion des cas limites (micro-volumes) ajoutée récemment |

### 1.2 Faiblesses Structurelles

```python
# PROBLÈME : Double calcul du total_score
# Dans TemporalScorer._compute_total_score() :
total = w_dir * s_direct + w_ind * indirect_score + interaction  # [0-1]
return min(total * 100, 100.0)  # Conversion en [0-100]

# Dans RelationshipScore.__post_init__() :
total = direct_score + indirect_score + interaction  # [0-1]
object.__setattr__(self, 'total_score', min(total * 100, 100.0))  # [0-100]
```

**INCohérence majeure** : `RelationshipScore` recalcule le total avec une formule différente (sans pondération dynamique) alors que `TemporalScorer` a déjà calculé le bon score.

---

## 2. Analyse Mathématique des Composantes

### 2.1 Score d'Intensité (Poids : 50%)

**Formule actuelle :**
```
S_intensite = min(ln(1 + V_total) / ln(1 + V_ref), 1.0) × (1 - exp(-N_total/τ))
```

#### Problèmes Identifiés

**A. Compression Logarithmique Trop Aggressive**

```python
# Exemple concret :
v_ref = 100 ETH  # Percentile 95 des volumes

# Cas 1 : Petite transaction
v_total = 0.1 ETH
volume_factor = ln(1.1) / ln(101) = 0.095 / 4.615 = 0.0206 (2%)

# Cas 2 : Transaction moyenne
v_total = 10 ETH
volume_factor = ln(11) / ln(101) = 2.398 / 4.615 = 0.519 (52%)

# Cas 3 : Grosse transaction
v_total = 100 ETH
volume_factor = 1.0 (100%)
```

**Verdict** : La différence entre 0.1 ETH et 10 ETH est écrasée (0.02 vs 0.52). Un facteur 100 en volume ne se traduit que par un facteur 25 en score.

**B. Dépendance Circulaire du v_ref**

```python
def _get_reference_volume(self, main_address: str) -> float:
    # Prend le percentile 95 des volumes de l'adresse principale
    v_ref = sorted_volumes[int(len(volumes) * 0.90)]
```

**Problème** : Le score dépend de l'activité globale de l'adresse principale. Une adresse très active "pénalise" toutes ses relations.

**Exemple critique :**
- Adresse A (whale) : max volume = 1000 ETH → v_ref = 900 ETH
  - Relation avec B (100 ETH) : intensité = ln(101)/ln(901) = 0.50

- Adresse C (petit portefeuille) : max volume = 10 ETH → v_ref = 9 ETH
  - Relation avec D (5 ETH) : intensité = ln(6)/ln(10) = 0.78

**Verdict** : B (100 ETH) a un score plus faible que D (5 ETH) ! Le scoring n'est pas absolu mais relatif à l'adresse principale.

**C. Saturation Fréquentielle (τ = 5.0)**

```
freq_factor = 1 - exp(-n/5)
```

| Nombre de Tx | Score Fréquence | Rendement marginal |
|--------------|-----------------|-------------------|
| 1 | 0.181 (18%) | - |
| 2 | 0.329 (33%) | +15 points |
| 5 | 0.632 (63%) | +30 points |
| 10 | 0.865 (87%) | +23 points |
| 20 | 0.982 (98%) | +12 points |

**Verdict** : La saturation est trop rapide. Au-delà de 10 transactions, le nombre n'a presque plus d'impact.

### 2.2 Score de Récence (Poids : 25%)

**Formule :**
```
weight_tx = value × exp(-λ_rec × age_blocks)
S_recence = sum(weights) / sum(values)
```

#### Problèmes

**A. Approximation des Blocs**

```python
def _approximate_block_number(self, timestamp) -> int:
    seconds_since_genesis = ts.timestamp() - 1438269970
    blocks = int(seconds_since_genesis / 12)  # 12s par bloc
```

**Problème** : Ethereum n'a pas toujours eu des blocs de 12 secondes. Avant la fusion (sept 2022), c'était ~13-15s.

**Erreur cumulée** : ~15% d'erreur sur les vieilles transactions.

**B. Dépendance au Volume**

Le score de récence est pondéré par le volume. Une transaction récente de 0.1 ETH a moins d'impact qu'une transaction vieille de 1 ETH.

**Exemple :**
- Tx 1 (il y a 1 jour) : 0.1 ETH → poids = 0.1 × 0.98 = 0.098
- Tx 2 (il y a 30 jours) : 10 ETH → poids = 10 × 0.61 = 6.1

**Verdict** : Le volume domine la récence. Une grosse transaction ancienne "bat" une petite transaction récente.

### 2.3 Score de Synchronie (Poids : 15%)

**Formule :**
```
S_sync = (1/N_tot) × Σ 1_{∃ tx_in : |block_out - block_in| ≤ δ}
```

#### Problèmes

**A. Fenêtre Temporelle Fixe (δ = 100 blocs)**

100 blocs ≈ 20 minutes. C'est raisonnable pour les arbitrages mais trop court pour :
- Déplacements de fonds entre cold/hot wallets
- Payements récurrents (factures, salaires)
- Délais de confirmation (gas price élevé)

**B. Détection Unidirectionnelle**

La synchronie ne compte que les tx_out qui ont une correspondance tx_in. Si A envoie à B et B renvoie 1 heure plus tard, ce n'est pas détecté comme synchronisé.

**Verdict** : La mesure est trop stricte. Beaucoup de patterns légitimes ne sont pas capturés.

### 2.4 Score d'Équilibre (Poids : 10%)

**Formule :**
```
S_equilibre = 0.5 × min(V_out, V_in) / V_total
```

#### Problèmes

**A. Poids Faible (10%)**

L'équilibre est le meilleur indicateur de relation économique (pas juste transfert unidirectionnel), mais il ne pèse que 10%.

**B. Linéarité**

```
V_out = 100, V_in = 100 → S_equilibre = 0.5 × 100/200 = 0.25
V_out = 100, V_in = 1   → S_equilibre = 0.5 × 1/101 = 0.005
V_out = 100, V_in = 0   → S_equilibre = 0
```

Le score passe de 0.25 à 0 quand le ratio passe de 1:1 à 1:0.

**Verdict** : Le bonus est trop faible pour vraiment valoriser la bidirectionnalité.

---

## 3. Score Indirect (Katz Temporel)

### 3.1 Algorithme

```
ψ(p) = Π s_local(e_j) × exp(-μ × Σ time_gap) × (min(V_first, V_last)/max(V_first, V_last))^ρ × 1/√deg(n_1)
```

### 3.2 Failles Critiques

**A. Normalisation Sigmoïde Mal Calibrée**

```python
# Paramètres actuels :
kappa = 6.0
tau_med = 0.15

# Exemple :
S_indirect_brut = 0.0  # Aucun chemin trouvé
S_indirect_norm = 1 / (1 + exp(-6 × (0 - 0.15))) = 0.18
```

**Verdict** : Même sans aucun chemin indirect, le score est de 0.18 (18%). C'est une "prime à l'existence" non justifiée.

**B. k_max = 2 (Profondeur Max)**

Avec `expansion_depth=2`, le graphe a rarement des chemins de longueur 2 qui respectent la causalité temporelle.

**Exemple :**
```
A --tx1--> B --tx2--> C
```

Pour que C soit atteint depuis A :
- tx1 doit être avant tx2 (causalité) ✓
- Mais si tx1 et tx2 sont dans le même fetch, ils ont des timestamps proches
- Le gap temporel est faible, donc la pénalité est faible

**Verdict** : Dans la pratique, très peu de nœuds ont des scores indirects > 0.

**C. Pénalité Hub (Adamic-Adar)**

```python
if depth == 0:
    hub_penalty = 1.0 / math.sqrt(max(degree, 1))
```

Un nœud avec degré 100 (CEX, DEX) a une pénalité de 0.1. C'est sévère mais justifié.

**Problème** : La pénalité ne s'applique qu'au premier saut. Les hubs intermédiaires ne sont pas pénalisés.

---

## 4. Problèmes Systémiques

### 4.1 Double Calcul du Total Score

```python
# TemporalScorer calcule :
total_score = w_dir * s_direct + w_ind * s_indirect + interaction  # [0-100]

# RelationshipScore recalcule :
total_score = (direct_score + indirect_score + interaction) * 100  # [0-100]
```

**Impact** : Le total affiché dans les tableaux est faux (formule simple sans pondération).

### 4.2 Cache Non-Invalide

```python
self._ref_stats_cache: Dict[str, Dict] = {}
```

Le cache des volumes de référence n'est jamais invalidé. Si le graphe change (expansion), le cache devient obsolète.

### 4.3 Sensibilité aux Paramètres

Changement de paramètres entre deux versions :

| Paramètre | Avant | Après | Impact |
|-----------|-------|-------|--------|
| tau | 20.0 | 5.0 | +5x sensibilité fréquence |
| v_percentile_ref | 95 | 90 | Référence plus basse |
| k_max | 3 | 2 | Moins de chemins indirects |
| kappa_sigmoid | 2.0 | 6.0 | Normalisation plus raide |

**Verdict** : Le système est instable. Les scores changent radicalement avec les ajustements.

---

## 5. Cas Limites et Échecs

### 5.1 Cas 1 : Micro-Transactions (< 0.01 ETH)

```python
v_total = 0.001 ETH  # ~2€
v_ref = 1.0 ETH

# Avec échelle linéaire (v_ref < 1.0)
volume_factor = 0.001 / 1.0 = 0.001

# Score d'intensité
intensite = 0.001 × 0.181 = 0.00018 (0.018%)
```

**Verdict** : Les micro-transactions sont pratiquement ignorées.

### 5.2 Cas 2 : Transactions Uniques

```python
n_total = 1
tau = 5.0
freq_factor = 1 - exp(-1/5) = 0.181
```

Une transaction unique perd 82% de son potentiel de score à cause de la saturation.

### 5.3 Cas 3 : Relations Purement Unidirectionnelles

```
A --> B (100 ETH, 10 transactions)
A <-- B (0 ETH, 0 transactions)
```

```python
S_equilibre = 0  # Pas de bidirectionnalité
S_direct = 0.5 × I + 0.25 × R + 0.15 × S + 0 = 0.5I + 0.25R + 0.15S
```

**Verdict** : Une relation forte mais unidirectionnelle (ex: paiement de salaire) est sous-évaluée.

### 5.4 Cas 4 : Adresses avec Une Seule Relation

Si l'adresse principale n'a qu'une seule relation dans le graphe :
```python
volumes = [100.0]  # Une seule transaction
v_ref = max(volumes) * 0.1 = 10.0  # min_v_ref

# Volume factor pour cette unique transaction
v_total = 100.0
volume_factor = min(100/10, 1.0) = 1.0
```

**Verdict** : La relation unique obtient un score maximal en intensité, même si c'est un transfert unique.

---

## 6. Comparaison avec l'État de l'Art

| Approche | Avantage | Inconvénient | Notre Score |
|----------|----------|--------------|-------------|
| **Notre système** | Multi-dimensionnel, temporel | Complexe, mal calibré | 6.5/10 |
| **Volume simple** | Intuitif, rapide | Ignore la temporalité | 4/10 |
| **Jaccard Index** | Normalisé | Ignore les poids | 5/10 |
| **SimRank** | Capture la structure | Coûteux, peu interprétable | 6/10 |
| **Embeddings (GraphSAGE)** | Capture les patterns complexes | Boîte noire, besoin de données d'entraînement | 7/10 |

---

## 7. Recommandations

### 7.1 Corrections Immédiates (Priorité Haute)

1. **Corriger le double calcul du total_score**
   ```python
   # Dans RelationshipScore.__post_init__, utiliser le total déjà calculé
   # ou supprimer le recalcul
   ```

2. **Fixer la normalisation sigmoïde**
   ```python
   if total_contribution == 0:
       return 0.0  # Pas de prime à l'existence
   ```

3. **Invalider le cache quand le graphe change**
   ```python
   def __init__(self, graph, config=None):
       # ...
       self._original_graph_id = id(graph)

   def score(self, ...):
       if id(self.graph) != self._original_graph_id:
           self._ref_stats_cache.clear()
   ```

### 7.2 Améliorations à Moyen Terme

4. **Découpler le v_ref de l'adresse principale**
   - Utiliser un référentiel global (médiane du réseau Ethereum)
   - Ou permettre la comparaison absolue vs relative

5. **Ajuster les poids des composantes**
   ```
   Proposition : I(40%), R(20%), S(15%), Eq(25%)
   ```
   La bidirectionnalité (équilibre) mérite plus de poids.

6. **Améliorer la synchronie**
   - Fenêtre dynamique selon le contexte (CEX vs DEX vs wallet)
   - Détection de patterns (round-trip, chaînage)

7. **Ajouter une composante de délai moyen**
   ```
   S_delai = exp(-avg_response_time / 30_days)
   ```
   Mesure le temps de réponse entre transaction entrante et sortante.

### 7.3 Refonte Majeure (Long Terme)

8. **Machine Learning pour la calibration**
   - Collecter des données étiquetées (même entité vs différente)
   - Entraîner un modèle de classification
   - Utiliser le scoring actuel comme features

9. **Contexte des transactions**
   - Détection de contrats (DEX, CEX, bridges)
   - Analyse de la nature des tokens (ETH, stablecoins, shitcoins)
   - Heuristiques de comportement (bot vs humain)

---

## 8. Tests de Validation Proposés

Pour valider les corrections, implémenter ces tests :

```python
def test_micro_transactions_distinguables():
    """0.01 ETH vs 0.1 ETH doivent avoir des scores différents (> 20% d'écart)."""
    pass

def test_unidirectional_not_penalized():
    """Une relation unidirectionnelle forte (salaire) doit avoir score > 50."""
    pass

def test_indirect_zero_when_no_path():
    """Score indirect doit être 0 quand aucun chemin n'existe."""
    pass

def test_consistency_across_main_addresses():
    """Même relation évaluée depuis A ou B doit donner des scores similaires."""
    pass

def test_recency_over_volume():
    """Une tx récente de 0.1 ETH doit avoir meilleur score récence qu'une tx vieille de 10 ETH."""
    pass
```

---

## 9. Conclusion

Le système de scoring est **théoriquement solide** mais **pratiquement biaisé** :

- ✅ Bonne couverture des dimensions (volume, temps, synchronie, équilibre)
- ✅ Approche temporelle sophistiquée (Katz)
- ❌ Calibration mathématique approximative
- ❌ Biais de normalisation (relatif à l'adresse principale)
- ❌ Instabilité aux changements de paramètres
- ❌ Bugs de synchronisation (double calcul)

**Score final : 6.5/10**

**Verdict** : Utilisable en l'état pour des analyses exploratoires, mais nécessite une recalibration approfondie avant toute utilisation en production pour de la détection d'entités.

---

*Audit réalisé le 11 Mars 2026*
*Auditeur : Claude Code*
*Version auditée : TemporalScorer v2.1*
