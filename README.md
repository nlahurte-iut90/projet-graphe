![Bananagraph](/projet/nom-ascii.png)


**Analyse de corrélation entre adresses Ethereum par théorie des graphes**
Détection de relations transactionnelles, scoring temporel avancé et visualisation interactive

---

##  Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Architecture du système](#architecture-du-système)
- [Méthodologie de scoring](#méthodologie-de-scoring)
  - [Score Direct (SD)](#score-direct--relations-immédiates)
  - [Score Indirect (SI)](#score-indirect--connexions-cachées)
  - [Score Propagé (SP)](#score-propagé--expansion-du-graphe)
  - [Score Total (ST)](#score-total--combinaison-pondérée)
- [Workflow d'expansion](#workflow-dexpansion)
- [Exports et visualisation](#exports-et-visualisation)
- [Notes techniques](#notes-techniques)

---

## Vue d'ensemble

**Bananagraph** est un moteur d'analyse forensique pour la blockchain Ethereum. L'outil récupère les données transactionnelles via l'API Dune Analytics, construit un graphe orienté et pondéré des relations entre adresses, et calcule des scores de corrélation multi-dimensionnels basés sur l'analyse temporelle des flux de valeur.

### Cas d'usage

- **Forensique on-chain** : identifier des clusters d'adresses contrôlés par une même entité
- **Due diligence** : évaluer la proximité entre deux adresses suspectes
- **Recherche académique** : modélisation des réseaux transactionnels Ethereum via la théorie des graphes

---

##  Installation

### Prérequis

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) pour la gestion des dépendances
- Une clé API Dune Analytics

### Configuration

1. **Cloner le dépôt**

   ```bash
   git clone <repository-url>
   cd bananagraph
   ```

2. **Configurer les credentials**

   ```bash
   cp .env.example .env
   # Éditer .env avec votre clé API
   echo "DUNE_API_KEY=votre_clé_api" >> .env
   ```

3. **Lancer l'application**

   ```bash
   uv run python -m src.main
   ```

> **Note** : Tous les outputs (JSON, CSV, HTML) sont générés dans le répertoire `/output/<timestamp>/`.

---

##  Utilisation

L'interface démarre avec une configuration interactive en ligne de commande :

```
╔════════════════════════════════════════════════════════════╗
║  Bananagraph — Ethereum Address Correlation Tool         ║
║ Analyse des relations entre adresses Ethereum              ║
╚════════════════════════════════════════════════════════════╝
```

### Paramètres configurables

| Paramètre | Description | Défaut |
|-----------|-------------|--------|
| **Adresses** | Paire d'adresses Ethereum à analyser | `vitalik.eth` + exemple |
| **Profondeur d'expansion** | Niveaux de découverte de nœuds (1 = base seule) | `2` |
| **Top N** | Nombre de nœuds sélectionnés par niveau d'expansion | `3` |
| **Limite TX (base)** | Transactions récupérées pour les adresses principales | `5` |
| **Limite TX (expansion)** | Transactions récupérées pour les nœuds découverts | `3` |

### Options de sortie

- [x] Graphique statique (Matplotlib)
- [x] Graphique interactif HTML (force-directed)
- [x] Export JSON structuré
- [x] Export CSV tabulaire

---

##  Architecture du système

```
src/
├── main.py                    # Point d'entrée CLI
├── config.py                  # Configuration et variables d'environnement
├── domain/
│   └── models.py             # Dataclasses métier (Address, Transaction, RelationshipScore)
├── services/
│   ├── correlation.py         # CorrelationService — orchestration du pipeline
│   ├── interactive_viz.py    # Moteur de visualisation HTML interactive
│   └── scoring/
│       ├── base.py           # Classes abstraites et interfaces
│       └── temporal_scorer.py # Implémentation du scoring temporel avancé
├── adapters/
│   └── dune.py               # DuneAdapter — client API Dune Analytics
├── infrastructure/
│   └── cache.py              # CacheManager (sérialisation pickle)
└── presentation/
    ├── table_formatter.py    # Rendu des tableaux (Rich)
    └── exporter.py           # Export JSON / CSV
```

---

##  Méthodologie de scoring

Le système combine **trois familles de scores** pour capturer les différentes dimensions d'une relation on-chain. Chaque composante répond à une problématique spécifique de l'analyse de graphe transactionnel.

### Score Direct — Relations immédiates

Mesure la force d'une relation **bidirectionnelle directe** entre deux adresses via leurs transactions mutuelles.

```
SD = 0.50 × I + 0.25 × R + 0.15 × S + 0.10 × E
```

| Composante | Formule | Pondération | Justification |
|------------|---------|-------------|---------------|
| **I — Intensité** | `min(ln(1+V)/ln(1+V_ref), 1) × (1-e^(-N/τ))` | 50% | Pénalise les micro-transactions, récompense la régularité |
| **R — Récence** | `exp(-λ_rec × Δ_blocks)` | 25% | Décroissance exponentielle avec demi-vie ~15 jours |
| **S — Synchronie** | `Σ 1[\|τ_out - τ_in\| ≤ Δ_sync] / N_tot` | 15% | Fréquence des échanges rapides (fenêtre ~20 min) |
| **E — Équilibre** | `0.5 × min(V_out, V_in) / V_total` | 10% | Bonus pour réciprocité équilibrée |

**Paramètres clés :**

- `V_ref` : percentile 95 du volume de l'adresse principale (normalisation adaptative)
- `τ = 15` : saturation fréquentielle (15 tx → 63% du maximum)
- `λ_rec = 0.000154` : demi-vie de 4500 blocs (~15 jours)
- `Δ_sync = 100` blocs (~20 minutes)

---

### Score Indirect — Connexions cachées

Pour les adresses sans transactions directes, évalue la corrélation via les **chemins multi-sauts** (amis d'amis).

```
SI = Σ_paths θ^depth × path_score × conservation
```

| Élément | Formule | Utilité |
|---------|---------|---------|
| **Atténuation Katz** | `θ^depth` avec `θ = 0.7` | Pénalise la distance : 1 saut = 0.7, 2 sauts = 0.49, 3 sauts = 0.34 |
| **Score local** | `s_edge = min(ln(1+w)/ln(51), 1)` | Force de chaque arête du chemin |
| **Pénalité temporelle** | `exp(-λ_chain × gap_blocks)` | Pénalise les pauses longues entre tx consécutives |
| **Pénalité hub** | `1/(1 + 0.2×ln(degree))` | Réduit l'impact des nœuds ultra-connectés (exchanges, contrats populaires) |
| **Conservation** | `(ratio^ρ) × v_mag` | Vérifie la préservation du volume (signe de flux cohérent) |

---

### Score Propagé — Expansion du graphe

Propage le score depuis les nœuds connus vers les nouveaux nœuds découverts lors de l'expansion.

```
SP(target) = Σ_{p ∈ parents} S_parent × w(p,target) × γ^d

où w(p,t) = s_edge(p,t) / Σ_k s_edge(p,k)
```

| Paramètre | Valeur | Signification |
|-----------|--------|---------------|
| `γ = 0.7` | Facteur de distance | Atténuation par saut depuis l'adresse principale |
| `w(p,t)` | Poids de propagation | Proportion de la "force" du parent dévolue à l'enfant |

---

### Score Total — Combinaison pondérée

```
ST = w_dir × SD + w_ind × SI + w_prop × SP + 0.05 × SD × SI
```

**Poids dynamiques adaptatifs :**

| Profil de données | N transactions | w_dir | w_ind | w_prop | Logique |
|-------------------|----------------|-------|-------|--------|---------|
| **Données pauvres** | N < 3 | 0.35 | 0.45 | 0.15 | Privilégie le signal réseau (indirect) |
| **Données riches** | N ≥ 3 | 0.60 | 0.20 | 0.15 | Privilégie le signal empirique (direct) |

**Terme d'interaction** (`0.05 × SD × SI`) : bonus pour les adresses présentant simultanément une relation directe forte ET des connexions indirectes (indicateur de relation communautaire).

---

###  Seuils d'interprétation

| Score | Contexte | Seuil "significatif" |
|-------|----------|----------------------|
| **SD** | Relations directes | > 0.30 |
| **SI** | Connexions cachées | > 0.10 |
| **SP** | Nœuds d'expansion | > 0.05 |
| **ST** | Évaluation finale | > 0.20 (20%) |

---

## Workflow d'expansion

Le pipeline d'exploration du graphe fonctionne par niveaux successifs :

### Niveau 0 (Base)

1. Récupération des transactions pour les deux adresses principales via `DuneAdapter`
2. Construction du graphe : arêtes pondérées par valeur en ETH
3. Découverte des voisins de niveau 0 (contacts directs)

### Niveaux 1+ (Expansion)

Pour chaque niveau :

1. **Sélection** : les `top_n` nœuds au meilleur score de corrélation sont retenus
2. **Récupération** : fetch des transactions pour chaque candidat
3. **Extension** : ajout des nouvelles transactions au graphe global
4. **Recalcul** : réévaluation de tous les scores avec les données enrichies

```
[Expansion] === LEVEL 0 (Base) ===
[Expansion] Level 0: 8 nodes, 10 edges

[Expansion] === LEVEL 1 (Expansion 1/1) ===
[Expansion] Selected 6 candidates from 6 newly discovered nodes
[Expansion] After fetch: 11 nodes, 27 edges
```

---

## Exports et visualisation

### Structure des outputs

```
output/
└── 20240313_143453/
    ├── interactive_graph_0xd8da6b_...html
    ├── data.json
    └── data.csv
```

### Format JSON

```json
{
  "timestamp": "20240313_143453",
  "tables": [
    {
      "main_address": "0xd8da...",
      "relationships": [...],
      "top_relationships": [...]
    }
  ]
}
```

### Tableau de résultats (CLI)

```
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┓
┃ Target Address       ┃   Act  ┃   Prox ┃   Rec  ┃   Dir  ┃   Total  ┃ Tx Count┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━┩
│ 0xf8fc9a91349ebd203… │      6 │      0 │      0 │    0.0 │     24.8 │        1│
│ 0x9a26be25ca0da8a7f… │      3 │      0 │      7 │    0.0 │     24.7 │        2│
└──────────────────────┴────────┴────────┴────────┴────────┴──────────┴─────────┘
```

**Légende :**

- **Act** (Activity) : Intensité transactionnelle (0-100)
- **Prox** (Proximity) : Synchronie temporelle (0-100)
- **Rec** (Recency) : Récence des interactions (0-100)
- **Dir** : Score direct normalisé (0-1)
- **Total** : Score combiné final (0-100)

### Visualisations

| Type | Technologie | Features |
|------|-------------|----------|
| **Statique** | Matplotlib | Layout personnalisé, couleurs par score, taille des arêtes ∝ volume |
| **Interactif** | HTML/JS | Zoom, pan, tooltips détaillés, force-directed animation |

---

## Notes techniques

| Aspect | Implémentation |
|--------|----------------|
| **Cache** | Résultats Dune sérialisés en `cache/` (pickle) |
| **Rate limiting** | Délai de 0.5s entre requêtes d'expansion |
| **Normalisation** | Toutes les adresses en lowercase |
| **ERC20** | Transferts de tokens (volume ~0) traités avec un score minimal |
| **Précision** | Des paramètres élevés augmentent la résolution du graphe et la précision des scores |

---
