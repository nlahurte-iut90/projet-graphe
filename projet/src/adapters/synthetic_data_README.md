# Données Synthétiques pour le Graphe de Corrélation

Ce module fournit des jeux de données synthétiques pour tester et valider toutes les fonctionnalités du graphe de corrélation Ethereum sans dépendre de l'API Dune.

## Utilisation Rapide

### 1. Utiliser un scénario prédéfini

```python
from src.adapters.synthetic_data import SyntheticDuneAdapter
from src.services.correlation import CorrelationService

# Utiliser un dataset prédéfini
adapter = SyntheticDuneAdapter(dataset_name="strong_direct")
service = CorrelationService(adapter)

# Les adresses sont déjà dans le dataset
result = service.analyze_correlation(
    adapter.current_dataset.address1,
    adapter.current_dataset.address2
)

print(f"Score: {result.score}")
```

### 2. Lister les scénarios disponibles

```python
adapter = SyntheticDuneAdapter()
print(adapter.list_available_datasets())
```

**Scénarios disponibles:**

| Nom | Description | Cas de test |
|-----|-------------|-------------|
| `strong_direct` | 20 transactions réciproques fortes | Score direct élevé |
| `weak_direct` | 1 petite transaction | Score direct faible |
| `indirect_paths` | 3 intermédiaires communs | Chemins A→X→B |
| `propagation_chain` | Chaîne de 4 nœuds | Propagation multi-hop |
| `dense_network` | 10 nœuds, connexions aléatoires | Réseau complexe |
| `no_connection` | Aucune transaction entre A et B | Scores à zéro |
| `recency_test` | Anciennes vs récentes transactions | Test composante recency |
| `volume_test` | Petit vs gros volumes | Test composante volume |
| `expansion_test` | Réseau à 2 niveaux | Test expansion graphe |

### 3. Créer un scénario personnalisé

```python
from src.adapters.synthetic_data import create_custom_dataset

dataset = create_custom_dataset(
    scenario="direct",           # 'direct', 'indirect', 'chain', 'random'
    num_transactions=20,
    value_range=(0.1, 10.0),     # ETH
    reciprocal=True,             # Transactions dans les deux sens
    seed=42                      # Reproductibilité
)

print(f"Adresses: {dataset.address1}, {dataset.address2}")
print(f"Transactions: {len(dataset.transactions_df)}")
```

### 4. Générateur avancé

```python
from src.adapters.synthetic_data import SyntheticDataGenerator

gen = SyntheticDataGenerator(seed=123)

# Générer tous les datasets
datasets = gen.generate_all_datasets()

# Ou créer manuellement
dataset = gen.generate_strong_direct_connection()
```

## Structure des Données

Chaque dataset contient:

```python
@dataclass
class SyntheticDataset:
    name: str                    # Identifiant du scénario
    description: str             # Description lisible
    address1: str               # Première adresse principale
    address2: str               # Deuxième adresse principale
    transactions_df: pd.DataFrame # Données de transaction
    expected_direct_score: float   # Score direct attendu
    expected_indirect_paths: int   # Nombre de chemins indirects attendus
    expected_propagation_depth: int # Profondeur de propagation attendue
```

## Tests Automatisés

Exécuter tous les tests:

```bash
cd /home/lgz/Documents/code/projet-graphe/projet
uv run python tests/test_synthetic_data.py
```

Options:

```bash
# Tester un scénario spécifique
uv run python tests/test_synthetic_data.py --test=dataset --dataset=strong_direct

# Tester uniquement l'expansion
uv run python tests/test_synthetic_data.py --test=expansion

# Tester la visualisation
uv run python tests/test_synthetic_data.py --test=viz

# Tester les scénarios personnalisés
uv run python tests/test_synthetic_data.py --test=custom
```

## Intégration avec l'application principale

Pour utiliser les données synthétiques dans `main.py`, remplacez simplement l'adaptateur:

```python
# Avant (avec Dune)
from src.adapters.dune import DuneAdapter
adapter = DuneAdapter()

# Après (avec données synthétiques)
from src.adapters.synthetic_data import SyntheticDuneAdapter
adapter = SyntheticDuneAdapter(dataset_name="dense_network")
```

Le reste du code fonctionne identiquement!

## Cas de Test Couverts

### 1. Scoring
- ✅ Score direct (nombre/volume de transactions)
- ✅ Score indirect (chemins via intermédiaires)
- ✅ Score propagé (multi-hop avec déclin)
- ✅ Composante récence (transactions récentes boostées)
- ✅ Composante volume (gros montants valorisés)

### 2. Graphe
- ✅ Construction du graphe
- ✅ Expansion avec profondeur variable
- ✅ Détection de chemins
- ✅ Réseaux denses et clairsemés

### 3. Visualisation
- ✅ Coloration par score
- ✅ Filtrage par profondeur
- ✅ Tooltips avec métriques
- ✅ Légende et interactions

### 4. Export
- ✅ Export JSON/CSV
- ✅ Tables de relation
- ✅ Métriques détaillées

## Exemple Complet

```python
from src.adapters.synthetic_data import SyntheticDuneAdapter
from src.services.correlation import CorrelationService
from src.presentation.table_formatter import RelationshipTableFormatter
from rich.console import Console

console = Console()

# 1. Charger un scénario
adapter = SyntheticDuneAdapter("propagation_chain")
service = CorrelationService(adapter)

# 2. Analyser
result = service.analyze_correlation(
    adapter.current_dataset.address1,
    adapter.current_dataset.address2,
    expansion_depth=3
)

# 3. Afficher les résultats
console.print(f"Score: {result.score:.1f}")
console.print(f"Nœuds: {result.details['nodes']}")
console.print(f"Arêtes: {result.details['edges']}")

# 4. Visualiser
service.visualize_interactive(
    adapter.current_dataset.address1,
    adapter.current_dataset.address2,
    expansion_depth=3
)
```

## Débogage

Pour inspecter les données brutes:

```python
adapter = SyntheticDuneAdapter("indirect_paths")
df = adapter.current_dataset.transactions_df

print(df.head())
print(df[['from', 'to', 'value_eth']].to_string())
```
