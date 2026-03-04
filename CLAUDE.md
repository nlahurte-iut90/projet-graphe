# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python application for analyzing Ethereum address correlations using graph theory. It fetches transaction data from Dune Analytics and builds a network graph to visualize relationships between addresses.

## Development Commands

All commands should be run from the `projet/` directory:

```bash
cd /home/lgz/Documents/code/projet-graphe/projet
```

### Running the Application

```bash
# Run the main application
uv run python -m src.main

# Or activate the virtual environment first
source .venv/bin/activate
python -m src.main
```

### Dependency Management

```bash
# Add a new dependency
uv add <package-name>

# Add a dev dependency
uv add --dev <package-name>

# Sync dependencies (install from lock file)
uv sync
```

### Testing

```bash
# Run all tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_specific.py

# Run with verbose output
uv run pytest -v
```

### Code Formatting

```bash
# Format code with black
uv run black src/
```

## Architecture

The project follows a layered Clean Architecture pattern:

```
src/
├── domain/          # Core business logic and models
│   └── models.py    # Address, Transaction, CorrelationResult dataclasses
├── services/        # Application services (orchestration)
│   └── correlation.py  # CorrelationService: builds graph, calculates scores, visualizes
├── adapters/        # External service interfaces
│   └── dune.py      # DuneAdapter: fetches transaction data from Dune Analytics
├── infrastructure/  # Technical infrastructure
│   └── cache.py     # CacheManager: pickles DataFrames to cache/ directory
├── config.py        # Configuration (DUNE_API_KEY from .env)
└── main.py          # Entry point
```

### Key Design Patterns

1. **Dependency Injection**: `CorrelationService` receives `DuneAdapter` via constructor
2. **Repository Pattern**: `DuneAdapter` abstracts data access, with `CacheManager` for local caching
3. **Value Objects**: `Address` is a frozen dataclass with automatic lowercase normalization

### Data Flow

1. `main.py` creates `DuneAdapter` and `CorrelationService`
2. `CorrelationService.build_graph()` calls `DuneAdapter.get_transactions()`
3. `DuneAdapter` checks cache first, then queries Dune Analytics SQL API
4. Results are cached as pickled DataFrames in `cache/` directory
5. `CorrelationService` builds a `networkx.MultiDiGraph` from transactions
6. Graph is visualized with matplotlib (custom layout with address1 left, address2 right)

## Important Notes

- **DUNE_API_KEY**: Must be set in `projet/.env` file (already gitignored)
- **Cache**: SQL query results are cached as pickle files in `projet/cache/`
- **Graph Depth**: Currently limited to 1-hop (direct transactions only) with limit=5 per address
- **Scoring**: The correlation score is currently hardcoded to 0.0 (placeholder implementation)
- **SQL Injection Risk**: The Dune adapter uses f-string interpolation for SQL queries - addresses should be validated

## Known Issues (from CODE_AUDIT.md)

1. Correlation scoring algorithm not implemented (returns 0.0)
2. Limited graph depth prevents detecting indirect relationships
3. SQL query construction uses string interpolation
4. Uses `print()` instead of proper logging
5. Pickle cache has security implications if cache files are shared
