# SimpleNodeScorer - Système de Scoring Expérimental

> ⚠️ **EXPERIMENTAL** - Ce module est sur la branche `exp` et n'est pas encore stable.

## Vue d'ensemble

Système de scoring simplifié pour évaluer la relation entre une adresse principale (main address) et les nœuds du graphe de transactions.

## Architecture à 3 Dimensions

```
┌─────────────────────────────────────────┐
│     SCORE DE RELATION (0-100)          │
├─────────────┬─────────────┬─────────────┤
│  ACTIVITÉ   │  PROXIMITÉ  │  RÉCENCE    │
│   (50%)     │   (30%)     │   (20%)     │
└─────────────┴─────────────┴─────────────┘
```

### 1. Activity (50%)

Basé sur les transactions directes entre les deux adresses.

**Formule**:
```
activity_score = 100 * (0.6 * volume_score + 0.3 * freq_score + 0.1 * bidirectional_ratio)
```

| Composante | Calcul | Description |
|------------|--------|-------------|
| `volume_score` | `min(log10(V + 1) / 3, 1.0)` | Volume total échangé, saturé à ~1000 ETH |
| `freq_score` | `min(N / 10, 1.0)` | Nombre de transactions, plafond à 10 |
| `bidirectional_ratio` | `1.0` si in+out, `0.5` sinon | Relations bidirectionnelles privilégiées |

### 2. Proximity (30%)

Distance dans le graphe (non orienté).

**Formule**:
```
proximity_score = max(0, 100 - (distance - 1) * 35)
```

| Distance | Score |
|----------|-------|
| 1 (voisin direct) | 100 |
| 2 (1 intermédiaire) | 65 |
| 3 (2 intermédiaires) | 30 |
| ≥ 4 | 0 |

### 3. Recency (20%)

Fraîcheur de la dernière transaction.

**Formule**:
```
recency_score = 100 * exp(-days / 30)
```

Demi-vie de 30 jours:
- 0 jour → 100
- 30 jours → 50
- 90 jours → ~5

## Utilisation

```python
from src.services.scoring import SimpleNodeScorer
import networkx as nx

# Créer le graphe
graph = nx.MultiDiGraph()
# ... ajouter des transactions ...

# Initialiser le scorer
scorer = SimpleNodeScorer(graph)

# Calculer le score
score = scorer.score(
    main_address="0xabc...",
    node="0xdef..."
)

print(score.total)      # Score total (0-100)
print(score.activity)   # Composante activité
print(score.proximity)  # Composante proximité
print(score.recency)    # Composante récence

# Interprétation
print(scorer.get_interpretation(score))  # "Relation forte", etc.
```

## Interprétation des Scores

| Score | Signification | Action suggérée |
|-------|---------------|-----------------|
| 80-100 | **Relation forte** | Voisin direct, actif, récent |
| 50-79 | **Relation modérée** | Voisin direct faible OU indirect proche |
| 20-49 | **Relation faible** | Indirect ou ancien |
| 1-19 | **Trace** | Lien très indirect |
| 0 | **Aucun lien** | Non connecté |

## Intégration avec CorrelationService

Le `CorrelationService` utilise automatiquement `SimpleNodeScorer` pour:

1. **Score direct** entre main address et nœuds
2. **Propagation** des scores à travers le graphe (utilisé pour les chemins indirects)

Les détails du scoring sont disponibles dans `RelationshipScore.metrics['score_breakdown']`.

## Affichage

Le `RelationshipTableFormatter` affiche les composantes du scoring avec:
- `Act` = Activity (vert si ≥ 50)
- `Prox` = Proximity (bleu si ≥ 50)
- `Rec` = Recency (jaune si ≥ 50)

## Avantages vs Ancien Système

| Aspect | Ancien | Nouveau (SimpleNodeScorer) |
|--------|--------|---------------------------|
| Complexité | Multiple formules ad-hoc | 3 dimensions claires |
| Interprétabilité | Difficile | Facile (activité/proximité/récence) |
| Performance | Cache limité | Cache d'arêtes intégré |
| Debug | Score opaque | Breakdown détaillé |
| Proximité | Non considérée | 30% du score |

## TODO / Améliorations Futures

- [ ] Calibration automatique des poids (0.5/0.3/0.2)
- [ ] Normalisation par rapport au réseau global
- [ ] Détection de patterns temporels avancés
- [ ] Scoring adaptatif selon le type d'adresse (EOA vs Contract)
