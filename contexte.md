# Ethereum Address Correlation Analyzer

## Vue d'ensemble

Cet outil analyse les corrélations entre adresses Ethereum en utilisant la théorie des graphes. Il construit un graphe de transactions entre adresses et calcule des scores de relation pour identifier les liens directs et indirects.

**Objectif principal** : Déterminer si deux adresses Ethereum sont liées (directement ou indirectement) et quantifier la force de cette relation via un algorithme de scoring multi-dimensionnel.

## Architecture

Le projet suit le pattern **Clean Architecture** avec séparation des couches :

```
src/
├── domain/              # Modèles métier (entities)
│   └── models.py        # Address, Transaction, RelationshipScore...
├── services/            # Logique métier (use cases)
│   ├── correlation.py          # CorrelationService (orchestration)
│   ├── interactive_viz.py      # Visualisation HTML interactive
│   └── scoring/
│       └── simple_node_scorer.py   # Algorithme de scoring
├── adapters/            # Interfaces externes
│   ├── dune.py          # DuneAdapter (données réelles)
│   └── synthetic_data.py # Données synthétiques pour tests
├── infrastructure/      # Infrastructure technique
│   └── cache.py         # CacheManager (pickle)
├── presentation/        # Couche présentation
│   ├── table_formatter.py  # Affichage tableaux Rich
│   └── exporter.py         # Export JSON/CSV
├── config.py           # Configuration
└── main.py             # Point d'entrée CLI
```

### Design Patterns utilisés

- **Dependency Injection** : `CorrelationService` reçoit `DuneAdapter` via constructeur
- **Repository Pattern** : `DuneAdapter` abstrait l'accès aux données
- **Value Objects** : `Address` est une dataclass frozen avec normalisation lowercase

## Fonctionnement

### Flux de données

1. **Configuration** : L'utilisateur saisit 2 adresses Ethereum et les paramètres d'expansion
2. **Construction du graphe** :
   - Récupération des transactions depuis Dune Analytics (ou données synthétiques)
   - Utilisation du cache local (pickle) pour éviter les appels API redondants
   - Construction d'un `networkx.MultiDiGraph` (graphe orienté multi-arêtes)
3. **Expansion itérative** :
   - Niveau 0 : Transactions des adresses principales
   - Niveaux 1+ : Expansion vers les nœuds les plus corrélés (top N par niveau)
   - Recalcul des scores à chaque niveau (les chemins indirects évoluent !)
4. **Scoring** : Calcul des scores de relation pour toutes les paires
5. **Visualisation** : Génération des graphiques (matplotlib + HTML interactif)
6. **Export** : Sauvegarde des résultats en JSON/CSV

### Algorithme d'expansion

```
Level 0: Récupère transactions des 2 adresses principales
         → Calcule scores initiaux
         → Identifie les nœuds découverts

Level 1: Sélectionne top N nœuds avec meilleurs scores
         → Récupère leurs transactions
         → Ajoute au graphe
         → Recalcule tous les scores

Level 2+: Répète le processus avec les nouveaux nœuds découverts
```

## Composants clés

### CorrelationService (`services/correlation.py`)

Orchestre l'analyse complète :

- `build_graph_with_expansion()` : Construction itérative du graphe
- `calculate_relationship_scores()` : Calcule les scores pour chaque relation
- `visualize_graph()` / `visualize_interactive()` : Génère les visualisations

### SimpleNodeScorer (`services/scoring/simple_node_scorer.py`)

Algorithme de scoring à 3 dimensions (voir section Scoring ci-dessous).

### DuneAdapter (`adapters/dune.py`)

Interface avec l'API Dune Analytics :

- Requêtes SQL sur `ethereum.transactions`
- Retry avec exponential backoff (rate limiting)
- Caching automatique via `CacheManager`

### SyntheticDataGenerator (`adapters/synthetic_data.py`)

Générateur de données de test avec 9 scénarios :

1. **strong_direct** : Forte connexion directe (20 transactions)
2. **weak_direct** : Connexion directe faible (1 transaction)
3. **indirect_paths** : Chemins indirects via intermédiaires
4. **propagation_chain** : Chaîne multi-hop (A→X→Y→B)
5. **dense_network** : Réseau dense aléatoire
6. **no_connection** : Aucune connexion
7. **recency_test** : Test de la composante recency
8. **volume_test** : Test de la composante volume
9. **expansion_test** : Test de l'expansion multi-niveaux

## Scoring

### Système à 3 dimensions

Le score total est une combinaison pondérée de 3 métriques :

| Dimension | Poids | Description | Formule |
|-----------|-------|-------------|---------|
| **Activity** | 50% | Volume, fréquence, bidirectionnalité | `100 × (0.6×vol_score + 0.3×freq + 0.1×bidir)` |
| **Proximity** | 30% | Distance dans le graphe | `max(0, 100 - (dist-1)×35)` |
| **Recency** | 20% | Fraîcheur des transactions | `100 × exp(-days/30)` |

**Formule finale** : `Total = 0.5×Activity + 0.3×Proximity + 0.2×Recency`

> Règle spéciale : Si Proximity = 0 (pas de chemin), le score total est 0.

### Types de scores

- **Direct** : Basé sur les transactions directes entre deux adresses
- **Indirect** : Basé sur les chemins A→X→B (paths analysis)
- **Propagated** : Score qui se propage à travers le graphe (DFS multi-hop)
- **Total** : `max(direct, indirect, propagated)`

### Interprétation des scores

| Score | Interprétation |
|-------|----------------|
| 80-100 | Relation forte |
| 50-79 | Relation modérée |
| 20-49 | Relation faible |
| 0-19 | Trace |
| 0 | Aucun lien |

## Visualisation

### 1. Matplotlib (statique)

- Layout personnalisé : Addr1 à gauche, Addr2 à droite
- Nœuds positionnés selon leur proximité aux adresses principales
- Arcs courbes pour montrer les transactions multiples
- Labels des montants sur les arcs

### 2. HTML Interactif (Pyvis)

Fichier généré dans `output/YYYYMMDD_HHMMSS/` :

- **Graphe manipulable** : zoom, déplacement, physique forceAtlas2
- **Tooltips** : Infos détaillées au survol
- **Coloration par score** : Clic sur un nœud principal colore les connexions selon leur score
- **Filtre de profondeur** : Affiche seulement les nœuds à N hops
- **Légende intégrée** : Codes couleur des scores

Contrôles interactifs :
- Cliquez un nœud principal → colore ses connexions
- Cliquez le fond → reset
- Sélecteur "Depth" → filtre par nombre de sauts

## Tests

### Données synthétiques

Utiliser `SyntheticDuneAdapter` pour tester sans appel API :

```python
from src.adapters.synthetic_data import SyntheticDuneAdapter

# Adapter avec scénario spécifique
adapter = SyntheticDuneAdapter(dataset_name="indirect_paths")

# Ou changer de scénario dynamiquement
adapter.switch_dataset("propagation_chain")
```

### Scénarios de test

Les 9 datasets couvrent :
- Connexions directes (fortes/faibles)
- Chemins indirects (1-3 intermédiaires)
- Chaînes de propagation (2-4 hops)
- Réseaux denses
- Absence de connexion
- Tests de composantes (recency, volume)

## Utilisation

### Prérequis

```bash
# Dune API Key dans projet/.env
DUNE_API_KEY=xxx
```

### Exécution

```bash
cd /home/lgz/Documents/code/projet-graphe/projet
uv run python -m src.main
```

### Configuration interactive

Le CLI guide l'utilisateur pour :

1. **Adresses** : Entrée manuelle ou défaut (vitalik.eth)
2. **Paramètres d'expansion** :
   - Profondeur (1 = base uniquement, 2 = 1 expansion, etc.)
   - Top N nœuds par niveau
   - Limite transactions (base vs expansion)
3. **Options de sortie** :
   - Graphique matplotlib
   - HTML interactif
   - Export JSON/CSV

### Paramètres recommandés

| Usage               | Depth | Top N | Base Tx | Expansion Tx |
|---------------------|-------|-------|---------|--------------|
| Test rapide         |   1   |   3   |     5   |      3       |
| Analyse standard    |   2   |   3   |    10   |      5       |
| Analyse approfondie |   3   |   5   |    20   |     10       |

## Points d'attention

### Limitations connues

1. **Rate limiting** : Dune API a des limites → retry avec backoff implémenté
2. **Cache** : Les résultats sont mis en cache en pickle (⚠️ sécurité si partage)
3. **SQL Injection** : Les requêtes utilisent f-string (adresses validées en amont)
4. **Graph depth** : Profondeur limitée à 3-4 pour éviter l'explosion combinatoire

### Sécurité

- Clé API dans `.env` (gitignored)
- Validation des adresses Ethereum (42 caractères, hex)
- Cache local non crypté (ne pas partager les fichiers `.pkl`)

### Performance

- Temps d'exécution dépend de :
  - Nombre de niveaux d'expansion
  - Rate limiting Dune API
  - Taille du graphe final
- Optimisation : cache local des requêtes SQL

---

*Dernière mise à jour : Mars 2026*
