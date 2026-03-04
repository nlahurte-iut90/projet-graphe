# AGENTS.md - Contexte du Projet

Ce fichier contient le contexte complet du projet pour les agents IA travaillant sur cette codebase.

---

## 1. Vue d'ensemble du projet

**Nom du projet :** `eth-correlation-graph`  
**Version :** 0.1.0  
**Type :** Application Python d'analyse de corrélation d'adresses Ethereum  
**Description :** Outil d'analyse des corrélations entre adresses Ethereum utilisant la théorie des graphes (NetworkX) et les données de Dune Analytics.

### Objectif principal
L'application permet de :
1. Récupérer les transactions blockchain entre deux adresses Ethereum via l'API Dune Analytics
2. Construire un graphe orienté des transactions (MultiDiGraph avec NetworkX)
3. Calculer un score de corrélation entre les adresses (actuellement placeholder)
4. Visualiser le graphe avec une mise en page personnalisée (matplotlib)

---

## 2. Architecture et structure

### Pattern architectural : Clean Architecture "Lite"
Le projet suit une architecture en couches modulaire :

```
projet/
├── src/
│   ├── domain/           # Couche Domaine - Modèles métier purs
│   │   └── models.py     # Address, Transaction, CorrelationResult
│   ├── services/         # Couche Application - Orchestration
│   │   └── correlation.py  # CorrelationService (construction graphe, scoring, viz)
│   ├── adapters/         # Couche Interface - Services externes
│   │   └── dune.py       # DuneAdapter (fetch données Dune Analytics)
│   ├── infrastructure/   # Couche Infrastructure - Technique
│   │   └── cache.py      # CacheManager (pickle DataFrames)
│   ├── config.py         # Configuration (env vars)
│   └── main.py           # Point d'entrée
├── cache/                # Cache local (fichiers .pkl)
├── data/cache/           # Répertoire de cache alternatif
├── pyproject.toml        # Configuration uv/packaging
└── uv.lock              # Lockfile des dépendances
```

### Diagramme de flux de données

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   main.py   │────▶│ CorrelationService│────▶│   DuneAdapter   │
└─────────────┘     └──────────────────┘     └─────────────────┘
                           │                           │
                           ▼                           ▼
                    ┌──────────────┐          ┌─────────────────┐
                    │ MultiDiGraph │          │   CacheManager  │
                    │  (NetworkX)  │          │    (pickle)     │
                    └──────────────┘          └─────────────────┘
                           │                           │
                           ▼                           ▼
                    ┌──────────────┐          ┌─────────────────┐
                    │  Matplotlib  │          │  DuneClient API │
                    │ Visualization│          │                 │
                    └──────────────┘          └─────────────────┘
```

---

## 3. Technologies et dépendances

### Stack principale
| Technologie | Version | Usage |
|-------------|---------|-------|
| Python | >=3.10 | Langage principal |
| NetworkX | >=3.1 | Graphes et algorithmes de graphe |
| Pandas | >=2.0 | Manipulation de données |
| Matplotlib | >=3.7 | Visualisation des graphes |
| Dune Client | >=1.0 | API Dune Analytics |
| python-dotenv | >=1.0 | Gestion des variables d'environnement |
| SciPy | >=1.11.0 | Calculs scientifiques (dépendance NetworkX) |

### Outils de développement
| Outil | Usage |
|-------|-------|
| uv | Gestionnaire de paquets et environnement virtuel |
| pytest | Tests unitaires |
| black | Formatage du code |

### Gestionnaire de paquets : UV
Le projet utilise `uv` (et non pip/poetry). Toutes les commandes doivent utiliser `uv`.

---

## 4. Guide de développement

### Prérequis
- Python 3.12+ (spécifié dans `.python-version`)
- Clé API Dune Analytics (dans `.env`)

### Configuration de l'environnement
```bash
cd /home/lgz/Documents/code/projet-graphe/projet

# Le .venv existe déjà, sinon :
# uv venv

# Activer l'environnement (optionnel)
source .venv/bin/activate
```

### Fichier .env requis
```bash
# projet/.env
DUNE_API_KEY=votre_cle_api_ici
CACHE_DIR=./data/cache  # Optionnel, défaut: ./cache
```

### Commandes courantes

```bash
# Exécuter l'application
uv run python -m src.main

# Ajouter une dépendance
uv add <package-name>

# Ajouter une dépendance de dev
uv add --dev <package-name>

# Synchroniser les dépendances
uv sync

# Lancer les tests
uv run pytest

# Formatter le code
uv run black src/
```

---

## 5. Structure détaillée du code

### Domain Layer (`src/domain/models.py`)
```python
@dataclass(frozen=True)
class Address:
    address: str  # Normalisé en lowercase via __post_init__

@dataclass
class Transaction:
    tx_hash: str
    sender: Address
    receiver: Address
    value: float
    timestamp: datetime
    token_symbol: str = "ETH"

@dataclass
class CorrelationResult:
    source: Address
    target: Address
    score: float
    path: List[Address]
    details: dict  # Contient nodes, edges, has_path
```

### Service Layer (`src/services/correlation.py`)
**Classe principale :** `CorrelationService`

Méthodes clés :
- `build_graph(address1, address2)` : Construit le MultiDiGraph à partir des transactions
- `calculate_score(address1, address2)` : Calcule le score de corrélation (TODO: implémenter)
- `visualize_graph(address1, address2)` : Génère une visualisation PNG

**Logique de visualisation :**
- Address1 positionnée à gauche (centre: -2.0, 0.0)
- Address2 positionnée à droite (centre: 2.0, 0.0)
- Voisins uniques d'addr1 : arc de cercle à gauche (90° à 270°)
- Voisins uniques d'addr2 : arc de cercle à droite (-90° à 90°)
- Voisins communs : alignés verticalement au centre (x=0)
- Arêtes courbées pour transactions multiples entre même paire

### Adapter Layer (`src/adapters/dune.py`)
**Classe :** `DuneAdapter`

Méthodes :
- `get_transactions(address1, address2, limit=5)` : Récupère les transactions

**Détails de la requête SQL :**
- Récupère les 5 dernières transactions pour chaque adresse (UNION ALL)
- Champs : from, to, value_eth (value/1e18), hash, block_time
- Table : `ethereum.transactions`
- Dédoublonnage sur le hash de transaction

### Infrastructure Layer (`src/infrastructure/cache.py`)
**Classe :** `CacheManager`

- Clé de cache : hash SHA256 de la requête SQL normalisée
- Format : fichiers `.pkl` (pickle) dans `cache/`
- Méthodes : `get(sql_query)`, `save(sql_query, df)`

---

## 6. Fonctionnement détaillé

### Flux d'exécution (main.py)
1. Chargement de la configuration (DUNE_API_KEY depuis .env)
2. Initialisation de `DuneAdapter`
3. Création de `CorrelationService` avec injection du adapter
4. Appel de `calculate_score()` qui :
   - Appelle `build_graph()`
   - `build_graph()` appelle `dune_adapter.get_transactions()`
   - L'adapter vérifie le cache d'abord, sinon appelle l'API Dune
   - Construction du MultiDiGraph avec les transactions
   - Calcul des métriques (nodes, edges, has_path)
5. Affichage des résultats
6. Appel de `visualize_graph()` pour générer le PNG

### Adresses de test (main.py)
```python
addr1 = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"  # vitalik.eth
addr2 = "0xF8fc9A91349eBd2033d53F2B97245102f00ABa96"
```

---

## 7. Points forts et bonnes pratiques

### ✅ Ce qui est bien fait
1. **Architecture modulaire** : Séparation claire des responsabilités (Domain/Services/Adapters)
2. **Typage statique** : Utilisation systématique des type hints
3. **Dataclasses** : Modèles immutables pour Address (frozen=True)
4. **Injection de dépendances** : CorrelationService reçoit DuneAdapter en paramètre
5. **Pattern Repository** : DuneAdapter abstrait l'accès aux données
6. **Caching intelligent** : Évite les appels API redondants
7. **Visualisation avancée** : Mise en page personnalisée avec arêtes courbées
8. **Outils modernes** : uv pour la gestion des dépendances

---

## 8. Plan d'action suggéré

### Améliorations possibles
- [ ] Implémenter l'algorithme de scoring dans `correlation.py`
  - Option A : Score binaire (100 si has_path, 0 sinon)
  - Option B : Indice de Jaccard sur les voisins communs
  - Option C : Score basé sur le volume de transactions
- [ ] Augmenter la limite de transactions ou implémenter recherche itérative
- [ ] Remplacer print() par logging
- [ ] Ajouter des tests unitaires (pytest)
- [ ] Valider le format des adresses Ethereum (regex 0x[0-9a-fA-F]{40})

---

## 9. Ressources et références

### Documentation utile
- [NetworkX Documentation](https://networkx.org/documentation/stable/)
- [Dune Analytics API](https://dune.com/docs/api/)
- [Dune Client Python](https://github.com/duneanalytics/dune-client)
- [UV Documentation](https://docs.astral.sh/uv/)

### Tables Dune Analytics utilisées
- `ethereum.transactions` : Transactions principales Ethereum
  - Colonnes utilisées : `from`, `to`, `value`, `hash`, `block_time`
  - Value en wei, conversion : `value/1e18` pour obtenir l'ETH

---

## 10. Notes pour les agents

### Avant de modifier le code
1. Lire `CLAUDE.md` pour les commandes de développement
2. Vérifier que `.env` contient `DUNE_API_KEY`
3. Tester avec `uv run python -m src.main`
4. Vérifier le cache dans `projet/cache/` pour éviter les appels API inutiles

### Conventions de code
- Typage : toujours utiliser les type hints
- Format : black (88 caractères par défaut)
- Imports : ordre standard (stdlib, tiers, local)
- Noms : snake_case pour fonctions/variables, PascalCase pour classes

### Tests
```bash
# Lancer tous les tests
uv run pytest

# Avec verbose
uv run pytest -v
```

### Points d'attention
- Le graphe est un `MultiDiGraph` (orienté, multi-arêtes)
- Les adresses sont normalisées en lowercase dans `Address.__post_init__`
- La visualisation sauvegarde dans `transaction_graph.png` (racine du projet)
- Les transactions self-loop (sender == receiver) sont supportées

---

*Dernière mise à jour : Février 2026*
