#!/usr/bin/env python3
"""
Exemple d'utilisation des algorithmes de scoring avancés.

Ce script démontre comment utiliser les différents scorers avec le CorrelationService.
"""

from src.services.correlation import CorrelationService
from src.adapters.synthetic_data import SyntheticDuneAdapter
from src.domain.models import Address


def demonstrate_scoring_strategies():
    """Démontre les différentes stratégies de scoring."""

    print("=" * 80)
    print("DÉMONSTRATION DES STRATÉGIES DE SCORING AVANCÉES")
    print("=" * 80)

    # Scénarios de test
    scenarios = [
        ("strong_direct", "Connexion directe forte"),
        ("multiple_disjoint_paths", "Chemins disjoints multiples"),
        ("hub_intermediary", "Connexion via hub"),
        ("temporal_coordination", "Coordination temporelle"),
    ]

    # Stratégies disponibles
    strategies = [
        ("simple", "Scorer basique (activité, proximité, récence)"),
        ("multipath", "Multiplicité des chemins (connectivité, résistance effective)"),
        ("simrank", "SimRank (similarité structurelle)"),
        ("ppr", "Personalized PageRank"),
        ("reliable", "Routes fiables (cohérence temporelle)"),
        ("ensemble", "Combinaison adaptative (tous les scorers)"),
    ]

    for scenario_name, scenario_desc in scenarios:
        print(f"\n{'=' * 80}")
        print(f"SCÉNARIO: {scenario_desc} ({scenario_name})")
        print(f"{'=' * 80}")

        adapter = SyntheticDuneAdapter(dataset_name=scenario_name)
        addr1 = Address(adapter.current_dataset.address1)
        addr2 = Address(adapter.current_dataset.address2)

        print(f"\nAdresses: {addr1.address[:15]}... <-> {addr2.address[:15]}...")

        for strategy_name, strategy_desc in strategies:
            print(f"\n  [{strategy_name}] {strategy_desc}")

            # Créer le service avec la stratégie
            service = CorrelationService(
                adapter,
                scoring_strategy=strategy_name,
                use_advanced_scoring=False  # Pour l'exemple, on ne calcule pas tout
            )

            # Construire le graphe et calculer
            result = service.calculate_score(
                addr1, addr2,
                expansion_depth=1,
                base_tx_limit=10
            )

            print(f"    Score: {result.score:.1f}")
            print(f"    Nœuds: {result.details['nodes']}, Arêtes: {result.details['edges']}")

            # Afficher les scores détaillés si disponibles
            rel = service._table1.get_relationship(addr2) if service._table1 else None
            if rel:
                print(f"    Direct: {rel.direct_score:.1f}, "
                      f"Indirect: {rel.indirect_score:.1f}, "
                      f"Propagated: {rel.propagated_score:.1f}")


def demonstrate_ensemble_with_breakdown():
    """Démontre le scorer ensemble avec détail des contributions."""

    print("\n" + "=" * 80)
    print("DÉMONSTRATION DU SCORER ENSEMBLE (AVEC DÉTAIL)")
    print("=" * 80)

    adapter = SyntheticDuneAdapter(dataset_name='multiple_disjoint_paths')
    addr1 = Address(adapter.current_dataset.address1)
    addr2 = Address(adapter.current_dataset.address2)

    # Créer le service avec ensemble et calcul avancé
    service = CorrelationService(
        adapter,
        scoring_strategy='ensemble',
        use_advanced_scoring=True
    )

    result = service.calculate_score(addr1, addr2, expansion_depth=1)

    print(f"\nScénario: Chemins disjoints multiples")
    print(f"Stratégie: ensemble (avec tous les scores avancés)")
    print(f"\nScore total: {result.score:.1f}")

    # Afficher les détails avancés
    rel = service._table1.get_relationship(addr2)
    if rel:
        print(f"\nScores avancés:")
        print(f"  Similarité structurelle: {rel.structural_similarity:.1f}")
        print(f"  Score multipath: {rel.multipath_score:.1f}")
        print(f"  Dynamique temporelle: {rel.temporal_dynamics:.1f}")
        print(f"  Total adaptatif: {rel.adaptive_total:.1f}")

        print(f"\nScores individuels (depuis les métriques):")
        advanced = rel.metrics.get('advanced_scores', {})
        for name, scores in advanced.items():
            print(f"  {name}: total={scores['total']:.1f}, "
                  f"activity={scores['activity']:.1f}, "
                  f"proximity={scores['proximity']:.1f}")


def demonstrate_comparison():
    """Compare les différents scorers sur le même scénario."""

    print("\n" + "=" * 80)
    print("COMPARAISON DES SCORERS SUR LE MÊME SCÉNARIO")
    print("=" * 80)

    adapter = SyntheticDuneAdapter(dataset_name='hub_intermediary')
    addr1 = Address(adapter.current_dataset.address1)
    addr2 = Address(adapter.current_dataset.address2)

    strategies = ['simple', 'multipath', 'simrank', 'ppr', 'reliable', 'ensemble']

    results = []
    for strategy in strategies:
        service = CorrelationService(adapter, scoring_strategy=strategy)
        result = service.calculate_score(addr1, addr2, expansion_depth=1)
        results.append((strategy, result.score))

    print(f"\nScénario: Connexion via hub (spécificité attendue)")
    print(f"\n{'Stratégie':<15} {'Score':>10}")
    print("-" * 30)
    for strategy, score in results:
        print(f"{strategy:<15} {score:>10.1f}")


if __name__ == "__main__":
    demonstrate_scoring_strategies()
    demonstrate_ensemble_with_breakdown()
    demonstrate_comparison()

    print("\n" + "=" * 80)
    print("Démonstration terminée!")
    print("=" * 80)
