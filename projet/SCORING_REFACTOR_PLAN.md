# Plan de Refactoring du Workflow de Scoring

## Vue d'ensemble

Le workflow de scoring utilise désormais un **scorer unifié** (`TemporalScorer`) qui remplace les deux méthodes précédentes (InitialScorer et SimpleNodeScorer).

---

## Workflow Actuel (TemporalScorer)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WORKFLOW DE SCORING UNIFIÉ (TemporalScorer)              │
└─────────────────────────────────────────────────────────────────────────────┘

ÉTAPE 1: RÉCUPÉRATION DES ADRESSES DE BASE
═══════════════════════════════════════════
• Récupérer les transactions des adresses principales (address1, address2)
• Construire le graphe initial (nœuds de niveau 0)
• Identifier les "base nodes" = voisins directs des adresses principales

                              ┌─────────┐
                              │ Main A  │
                              └────┬────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           │                       │                       │
           ▼                       ▼                       ▼
    ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
    │  Base Node 1│         │  Base Node 2│         │  Base Node 3│  ... = Nœuds de base
    └─────────────┘         └─────────────┘         └─────────────┘


ÉTAPE 2: SCORING AVEC TEMPORALSCORER
════════════════════════════════════
Méthode: TemporalScorer.score(main_address, node)

Pour tous les nœuds (base + expansion), calcule:

1. SCORE DIRECT (SD) = 50%×Intensité + 25%×Récence + 15%×Synchronie + 10%×Équilibre
   ├── Intensité: Volume et fréquence des transactions (logarithmique)
   ├── Récence: Fraîcheur des transactions (décroissance exponentielle)
   ├── Synchronie: Corrélation temporelle entrées/sorties
   └── Équilibre: Bonus pour bidirectionnalité

2. SCORE INDIRECT (SI) = Katz temporel avec conservation de volume
   ├── Beam search limitée (profondeur max k=3)
   ├── Causalité temporelle respectée (pas de remontée dans le temps)
   ├── Pénalité de volume (conservation progressive: ratio^ρ)
   └── Early stopping sur les hubs (degré > 100)

3. SCORE TOTAL = w_dir×SD + w_ind×SI + 0.05×SD×SI
   └── Pondération dynamique: w_dir=0.7 si N_tx≥3, sinon w_dir=0.4


ÉTAPE 3: EXPANSION
══════════════════
• Sélectionner les top_n nœuds avec les meilleurs scores
• Récupérer les transactions de ces nœuds sélectionnés
• Ajouter ces transactions au graphe (nœuds de niveau 1+)
• Recalculer les scores avec TemporalScorer (graphe enrichi)

    ┌─────────────┐
    │  Base Node  │ (sélectionné car score élevé)
    └──────┬──────┘
           │
    ┌──────┼──────┐
    ▼      ▼      ▼
┌─────┐ ┌─────┐ ┌─────┐
│New 1│ │New 2│ │New 3│  ... = Nouveaux nœuds découverts
└─────┘ └─────┘ └─────┘


---

## Architecture du TemporalScorer

### Paramètres Configurables (TemporalScorerConfig)

```python
@dataclass
class TemporalScorerConfig:
    lambda_rec: float = 0.01          # Décroissance récence (par bloc)
    lambda_chain: float = 0.001       # Décroissance temporelle chaîne
    theta: float = 0.4                # Atténuation profondeur Katz
    rho: float = 1.5                  # Sévérité conservation volume
    delta_t_blocks: int = 50          # Fenêtre synchronie (blocs)
    max_degree_explore: int = 100     # Early stopping hubs
    k_max: int = 3                    # Profondeur max recherche
    v_percentile_ref: float = 95.0    # Percentile pour normalisation volume
    tau: float = 3.0                  # Facteur saturation nombre de transactions
    max_paths: int = 1000             # Limite de chemins pour indirect
```

### Structure NodeScore (mise à jour)

```python
@dataclass
class NodeScore:
    total: float           # Score total [0-100]
    direct: float          # Score direct SD [0-1]
    indirect: float        # Score indirect SI [0-1]
    intensite: float       # S_intensite [0-1]
    recence: float         # S_recence [0-1]
    synchronie: float      # S_sync [0-1]
    equilibre: float       # S_equilibre [0-1]
    interaction: float     # Terme d'interaction [0-1]
    confidence: str        # 'high' | 'medium' | 'low'
    metrics: Dict[str, Any]  # Métriques détaillées
```

### Structure RelationshipScore (mise à jour)

```python
@dataclass
class RelationshipScore:
    source: Address
    target: Address
    direct_score: float       # Score direct SD [0-1]
    indirect_score: float = 0.0  # Score indirect SI [0-1]
    total_score: float = 0.0  # Calculé automatiquement
    confidence: str = "low"
    metrics: Dict[str, Any]
```

---

## Formules Mathématiques

### Score Direct

**Intensité:**
```
V_total = V_out + V_in
N_total = N_out + N_in
S_intensite = min(ln(1 + V_total) / ln(1 + V_ref), 1.0) × (1 - exp(-N_total/τ))
```

**Récence:**
```
Pour chaque tx: weight_tx = value × exp(-λ_rec × (current_block - block_number))
S_recence = sum(weights) / sum(values)
```

**Synchronie:**
```
Pour chaque tx sortante, chercher tx entrante dans [block - δ, block + δ]
S_sync = count_sync / total_tx
```

**Équilibre:**
```
Si bidirectionnel: S_equilibre = 0.5 × min(V_out, V_in) / V_total
Sinon: S_equilibre = 0
```

### Score Indirect (Katz Temporel)

```
Pour chaque chemin main → ... → target valide:
    - Vérifier causalité temporelle (temps croissant)
    - Calculer s_edge (score local de chaque arête)
    - time_penalty = exp(-λ_chain × time_gap)
    - hub_penalty = 1/√degree si depth=0 sinon 1
    - path_score = ∏(s_edge × time_penalty × hub_penalty)
    - ratio = min(V_first, V_last) / max(V_first, V_last)
    - conservation = ratio^ρ
    - contribution = θ^depth × path_score × conservation

S_indirect = sum(contributions) [borné à 1.0]
```

### Score Total

```
Si N_tx < 3:
    w_dir, w_ind = 0.4, 0.55  # Peu d'historique → privilégier l'indirect
Sinon:
    w_dir, w_ind = 0.7, 0.25  # Suffisamment d'historique → privilégier le direct

S_total = w_dir×S_direct + w_ind×S_indirect + 0.05×S_direct×S_indirect
```

---

## Fichiers Modifiés

| Fichier | Description |
|---------|-------------|
| `src/services/scoring/temporal_scorer.py` | **NOUVEAU** - Scorer unifié |
| `src/services/scoring/base.py` | Mise à jour de NodeScore |
| `src/services/scoring/__init__.py` | Export TemporalScorer |
| `src/domain/models.py` | Mise à jour de RelationshipScore |
| `src/services/correlation.py` | Utilisation uniquement de TemporalScorer |
| `src/services/interactive_viz.py` | Tooltips avec nouvelles dimensions |

---

## Avantages du Nouveau Système

1. **Unification**: Un seul scorer pour tous les cas d'usage (base + expansion)
2. **Fondement temporel**: Toutes les métriques prennent en compte le temps
3. **Détection indirecte**: Algorithme de Katz pour détecter les relations cachées
4. **Robustesse**: Early stopping sur les hubs, bornes de sécurité
5. **Interpretabilité**: Dimensions claires (intensité, récence, synchronie, équilibre)
6. **Confiance explicite**: Niveau de confiance basé sur le volume et le nombre de transactions

---

## Notes d'Implémentation

### Gestion des Timestamps

Le graphe stocke des timestamps ISO qui sont convertis en numéros de blocs approximatifs:
```python
def _approximate_block_number(timestamp):
    seconds_since_genesis = timestamp - ETH_GENESIS_TIMESTAMP
    return seconds_since_genesis / ETH_BLOCK_TIME  # ~12 sec/bloc
```

### Cache des Stats de Référence

Les volumes de référence (percentile 95) sont mis en cache par adresse principale pour éviter les recalculs.

### Limites de Sécurité

- `max_paths = 1000` : Limite le nombre de chemins explorés
- `max_degree_explore = 100` : Évite d'explorer les hubs (CEX, contrats populaires)
- `k_max = 3` : Profondeur maximale de recherche indirecte
