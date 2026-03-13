# Analyse de correlation entre addresses ethereum    

Analyse des relations entre adresses Ethereum en utilisant la théorie des graphes.

## Presentation du projet

Ce projet universitaire a pour but d'utiliser les propriétés de la théorie des graphes.
Cet outil récupère les transactions Ethereum via l'API Dune Analytics, construit un graphe de relations entre adresses, et calcule des scores de corrélation basés sur l'analyse temporelle des transactions.

## Utilisation

uv run python3 -m src.main

---

## Workflow Détaillé

### 1. Configuration Interactive (`src/main.py`)

L'outil démarre avec une configuration interactive via le CLI:

```
╔════════════════════════════════════════════════════════════╗
║ Ethereum Address Correlation Tool                          ║
║ Analyse des relations entre adresses Ethereum              ║
╚════════════════════════════════════════════════════════════╝
```

#### Paramètres configurables :

| Paramètre                  | Description                                               | Défaut                |
|----------------------------|-----------------------------------------------------------|-----------------------|
| **Adresses**               | Deux adresses Ethereum à analyser                         | vitalik.eth + exemple |
| **Profondeur d'expansion** | Niveaux de découverte de nœuds (1=base, 2=1 niveau, etc.) |            2          |
| **Top N**                  | Nombre de nœuds à sélectionner par niveau                 |            3          | 
| **Limite TX (base)**       | Transactions à récupérer pour les adresses principales    |            5          |
| **Limite TX (expansion)**  | Transactions à récupérer pour les nœuds découverts        |            3          |

#### Options de sortie :
- Graphique statique matplotlib
- Graphique interactif HTML
- Export JSON
- Export CSV

---

### 2. Construction du Graphe avec Expansion (`src/services/correlation.py`)

Le processus d'expansion se déroule en plusieurs niveaux :

#### Niveau 0 (Base)
```
[Expansion] === LEVEL 0 (Base) ===
[Expansion] Fetching transactions for main addresses...
[Expansion] Level 0: X nodes, X edges
```

1. **Récupération des transactions** pour les deux adresses principales via `DuneAdapter`
2. **Construction du graphe** : les transactions deviennent des arêtes pondérées (poids = valeur de tx en ETH)
3. **Découverte des voisins** : identification des nœuds de niveau 0 (adresses en contact direct avec une address principale)

#### Niveaux d'Expansion (1+)
```
[Expansion] === LEVEL 1 (Expansion 1/1) ===
[Expansion] Selected X candidates from X newly discovered nodes
[Expansion] Fetching transactions for selected candidates...
```

Pour chaque niveau d'expansion :

1. **Sélection** : Les `top_n` nœuds avec les meilleurs scores de correlation avec address principale sont sélectionnés comme candidats
2. **Récupération** : Récupération des transactions pour chaque candidat
3. **Extension** : Ajout des nouvelles transactions au graphe
4. **Recalcul** : Recalcul de tous les scores avec les nouvelles données

---

### 3. Formule de Scoring - Analyse Détaillée (`src/services/scoring/temporal_scorer.py`)

Le système de scoring combine **trois types de scores** pour capturer différentes facettes des relations entre adresses Ethereum. Chaque composante répond à une problématique spécifique de l'analyse de graphe transactionnel.

---

#### Score Direct — Relations immédiates

Mesure la force d'une relation **bidirectionnelle directe** entre deux adresses.

```
SD = 0.50 × I + 0.25 × R + 0.15 × S + 0.10 × E
```

| Composante               | Formule                                      | Justification                                              | Contexte d'utilisation                               |
|--------------------------|----------------------------------------------|------------------------------------------------------------|------------------------------------------------------|
| **I — Intensité** (50%)  | `min(ln(1+V)/ln(1+V_ref), 1) × (1-e^(-N/τ))` | Pénalise les micro-transactions, récompense la régularité  | Détecter les relations économiques significatives    |
| **R — Récence** (25%)    | `exp(-λ_rec × Δ_blocks)`                     | Décroissance exponentielle avec demi-vie ~15 jours         | Privilégier les relations actives sur les anciennes  |
| **S — Synchronie** (15%) | `Σ 1[|τ_out - τ_in| ≤ Δ_sync] / N_tot`       | Compte les paires de transactions temporellement corrélées | Identifier les échanges rapides                      |
| **E — Équilibre** (10%)  | `0.5 × min(V_out, V_in) / V_total`           | Bonus pour réciprocité équilibrée                          | Détecter relations symétriques vs unidirectionnelles |

**Paramètres clés :**
- `V_ref` = percentile 95 du volume de l'adresse principale (normalisation adaptative)
- `τ = 15` (saturation fréquentielle : 15 tx → 63% du max)
- `λ_rec = 0.000154` (demi-vie de 4500 blocs ≈ 15 jours)
- `Δ_sync = 100` blocs (~20 minutes, fenêtre de "simultanéité")

**Exemple concret :**
```
Alice envoie 10 ETH à Bob (tx 1)
Bob renvoie 9 ETH à Alice 5 min plus tard (tx 2)

→ Intensité = ln(11)/ln(51) × (1-e^(-2/15)) = 0.43 × 0.12 = 0.05
→ Récence = 1.0 (transactions récentes)
→ Synchronie = 1/2 = 0.5 (1 paire synchrone sur 2 tx)
→ Équilibre = 0.5 × min(10,9)/19 = 0.24

Score Direct = 0.50×0.05 + 0.25×1.0 + 0.15×0.5 + 0.10×0.24 = 0.34 (34%)
```

---

#### Score Indirect — Connexions cachées

Pour les adresses sans transactions directes, mesure la corrélation via les **chemins indirects** (amis d'amis).

```
SI = Σ_paths θ^depth × path_score × conservation
```

**Composantes du chemin :**

| Élément                 | Formule                           | Utilité                                                                    |
|-------------------------|-----------------------------------|----------------------------------------------------------------------------|
| **Atténuation Katz**    | `θ^depth` avec `θ = 0.7`          | Pénalise les chemins longs : 1 saut = 0.7, 2 sauts = 0.49, 3 sauts = 0.34  |
| **Score local**         | `s_edge = min(ln(1+w)/ln(51), 1)` | Force de chaque arête du chemin (basé sur le volume transité)              |
| **Pénalité temporelle** | `exp(-λ_chain × gap_blocks)`      | Pénalise les pauses longues entre transactions consécutives                |
| **Pénalité hub**        | `1/(1 + 0.2×ln(degree))`          | Réduit l'impact des nœuds ultra-connectés (exchanges, contrats populaires) |
| **Conservation**        | `(ratio^ρ) × v_mag`               | Vérifie que le volume est préservé (signe de flux cohérent)                |

**Pourquoi ces pénalités ?**
- **Katz** : Un chemin A→B→C→D est moins significatif que A→B direct
- **Temporelle** : Une transaction A→B suivie de B→C 3 jours plus tard est moins liée que dans la même heure
- **Hub** : Passer par Binance n'indique pas une relation spécifique (tout le monde passe par là)
- **Conservation** : Si A envoie 100 ETH à B, et B envoie 100 ETH à C, c'est un flux cohérent (possiblement le même bénéficiaire final)

**Exemple de calcul :**
```
Chemin : Alice (100 ETH) → Exchange → Bob (100 ETH)
Depth = 2, θ^2 = 0.49
Score arête 1 = ln(101)/ln(51) = 1.0
Score arête 2 = 1.0
Conservation = (100/100)^1.5 × (100/(100+1)) = 0.99
Pénalité hub (exchange a 10000 connexions) = 1/(1+0.2×ln(10000)) = 0.26

Contribution = 0.49 × 1.0 × 1.0 × 0.26 × 0.99 = 0.13
```

---

#### Score Propagé — Expansion du graphe

Pour les nœuds découverts lors de l'expansion, propage le score depuis les **nœuds connus** via les liens existants.

```
SP(target) = Σ_{p ∈ parents} S_parent × w(p,target) × γ^d

où w(p,t) = s_edge(p,t) / Σ_k s_edge(p,k)  (poids normalisé)
```

| Paramètre | Valeur               | Signification                                           |
|-----------|----------------------|---------------------------------------------------------|
| `γ = 0.7` | Facteur de distance  | Atténuation par saut depuis l'adresse principale        |
| `w(p,t)`  | Poids de propagation | Proportion de la "force" du parent dévolue à cet enfant |

**Contexte d'utilisation :**
Quand l'expansion découvre une nouvelle adresse X (via A→X), on calcule :
1. Le score de A (connu)
2. La qualité du lien A→X (poids de l'arête)
3. La propagation : `SP(X) = S(A) × w(A,X) × 0.7^1`

Cela permet d'estimer la pertinence des nœuds distants même sans données complètes sur leurs transactions.

---

####  Score Total — Combinaison pondérée

```
ST = w_dir × SD + w_ind × SI + w_prop × SP + 0.05 × SD × SI
```

**Poids dynamiques** (adaptatifs selon la richesse des données) :

| Cas                 | N transactions | w_dir | w_ind | w_prop | Justification                                               |
|---------------------|----------------|-------|-------|--------|-------------------------------------------------------------|
| **Données pauvres** | N < 3          | 0.35  | 0.45  | 0.15   | Peu de données directes → on privilégie l'indirect (réseau) |
| **Données riches**  | N ≥ 3          | 0.60  | 0.20  | 0.15   | Assez d'historique → on privilégie le direct (plus fiable)  |

**Terme d'interaction** (`0.05 × SD × SI`) :
- Bonus pour les adresses ayant **à la fois** une relation directe forte ET des connexions indirectes
- Ex : Alice et Bob échangent souvent (SD élevé) ET ont des amis communs (SI élevé) → relation communautaire forte

**Exemple complet :**
```
Adresse : Bob (3 transactions directes avec Alice)
SD = 0.45, SI = 0.12, SP = 0.0

Poids (N≥3) : w_dir=0.60, w_ind=0.20, w_prop=0.15
ST = 0.60×0.45 + 0.20×0.12 + 0.15×0.0 + 0.05×0.45×0.12
ST = 0.27 + 0.024 + 0 + 0.0027 = 0.297 → 29.7%
```

---

#### 📊 Tableau récapitulatif des scores

| Score | Quand utilisé ?               | Formule clé             | Seuil "intéressant"                    |
|------- |------------------------------|-------------------------|----------------------------------------|
| **SD** | Toujours (si tx directes)    | Combinaison pondérée 4D | > 0.3 (relation directe significative) |
| **SI** | SD faible ou nul             | Katz temporel           | > 0.1 (connexion indirecte détectable) |
| **SP** | Nœuds d'expansion uniquement | Propagation pondérée    | > 0.05 (nœud potentiellement lié)      |
| **ST** | Score final affiché          | Combinaison dynamique   | > 20 (relation à investiguer)          |

---

### 4. Affichage des Résultats (`src/presentation/table_formatter.py`)

Deux tableaux sont affichés avec Rich :

```
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┓
┃ Target Address       ┃    Act ┃   Prox ┃    Rec ┃    Dir ┃    Total ┃ Tx Count┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━┩
│ 0xf8fc9a91349ebd203… │      6 │      0 │      0 │    0.0 │     24.8 │        1│
│ 0x9a26be25ca0da8a7f… │      3 │      0 │      7 │    0.0 │     24.7 │        2│
└──────────────────────┴────────┴────────┴────────┴────────┴──────────┴─────────┘
```

**Colonnes :**
- **Act** (Activity) : Intensité des transactions (0-100)
- **Prox** (Proximity) : Synchronie temporelle (0-100)
- **Rec** (Recency) : Récence des transactions (0-100)
- **Dir** : Score direct normalisé (0-1)
- **Total** : Score total combiné (0-100)
- **Tx Count** : Nombre de transactions

---

### 5. Export des Données

Tous les exports sont placés dans un dossier timestampé unique :

```
output/
└── 20240313_143453/
    ├── interactive_graph_0xd8da6b_...html
    ├── data.json
    └── data.csv
```

#### Format JSON
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

#### Format CSV
```csv
main_address,target_address,score,total_score,tx_count,volume_eth
0xd8da...,0xf8fc...,0.03,24.8,1,0.0001
```

---

### 6. Visualisation

#### Graphique Matplotlib (Statique)
- Couleurs des nœuds selon le score de corrélation
- Taille des arêtes proportionnelle au volume
- Layout personnalisé avec les adresses principales de part et d'autre

#### Graphique Interactif HTML
- Navigation zoom/pan
- Tooltips détaillés au survol
- Légende des scores
- Graphe dynamique avec animation force-directed

---

## Architecture du Projet

```
src/
├── main.py                    # Point d'entrée
├── config.py                  # Configuration (API keys)
├── domain/
│   └── models.py             # Dataclasses (Address, Transaction, RelationshipScore)
├── services/
│   ├── correlation.py        # CorrelationService (orchestration)
│   ├── interactive_viz.py    # Visualisation HTML interactive
│   └── scoring/
│       ├── base.py           # Classes de base
│       └── temporal_scorer.py # Scoring temporel avancé
├── adapters/
│   └── dune.py               # DuneAdapter (API Dune Analytics)
├── infrastructure/
│   └── cache.py              # CacheManager (pickle)
└── presentation/
    ├── table_formatter.py    # Affichage des tableaux Rich
    └── exporter.py           # Export JSON/CSV
```

---

## Commandes

```bash
# Lancer l'application
uv run python -m src.main

# Lancer les tests
uv run pytest

# Formater le code
uv run black src/
```

---

## Configuration

Créer un fichier `.env` dans le dossier `projet/` :

```bash
DUNE_API_KEY=votre_clé_api_dune
```

## Exemple de Session

```
$ uv run python -m src.main

[Expansion] Configuration: depth=2, top_n=3, base_tx_limit=5, expansion_tx_limit=3
[Expansion] Level 0: 8 nodes, 10 edges
[Expansion] Selected 6 candidates from 6 newly discovered nodes
[Expansion] After fetch: 11 nodes, 27 edges

Score de corrélation global: 24.76

✓ Analyse terminée!
```

---

## Notes Techniques

- **Cache** : Les résultats Dune sont mis en cache dans `cache/` (pickle)
- **Rate Limiting** : Délai de 0.5s entre les requêtes d'expansion
- **Normalisation** : Les adresses sont normalisées en minuscules
- **ERC20** : Les transferts de tokens (volume ~0) sont traités avec un score minimal
- **Developpement** : claude code ( avec k2p5-coding ) et mon cerveau ont été uriliser pour le développement de ce projet 
