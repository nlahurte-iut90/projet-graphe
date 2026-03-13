"""Génération de données synthétiques pour valider le scoring temporel.

Ce script crée des scénarios de transactions synthétiques avec des patterns connus,
calcule les scores, et génère des visualisations interactives pour validation visuelle.
"""

import pandas as pd
import networkx as nx
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from dataclasses import dataclass

from src.services.scoring import TemporalScorer
from src.services.correlation import CorrelationService
from src.domain.models import Address
from src.services.interactive_viz import InteractiveGraphVisualizer


@dataclass
class SyntheticScenario:
    """Un scénario de test avec description et données."""
    name: str
    description: str
    address1: str
    address2: str
    transactions: List[Dict]
    expected_score_range: Tuple[float, float]  # (min, max)
    expected_classification: str


class SyntheticDataGenerator:
    """Générateur de données de transaction synthétiques."""

    def __init__(self):
        self.now = datetime(2026, 3, 12, 12, 0, 0)
        self.base_addresses = {
            'addr1': '0x1111111111111111111111111111111111111111',
            'addr2': '0x2222222222222222222222222222222222222222',
            'inter1': '0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
            'inter2': '0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB',
            'inter3': '0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC',
            'hub': '0xHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH',
        }

    def _tx(self, from_key: str, to_key: str, value: float,
            days_ago: float = 0, hours_offset: float = 0) -> Dict:
        """Crée une transaction."""
        timestamp = self.now - timedelta(days=days_ago, hours=hours_offset)
        return {
            'from': self.base_addresses[from_key],
            'to': self.base_addresses[to_key],
            'value_eth': value,
            'value_wei': int(value * 1e18),
            'hash': f'tx_{from_key}_{to_key}_{days_ago}_{hours_offset}',
            'block_time': timestamp.isoformat()
        }

    def scenario_1_strong_correlation(self) -> SyntheticScenario:
        """Scénario 1: Forte corrélation (même entité probable).

        Pattern: Beaucoup de transactions récentes, bidirectionnelles,
        volumes équilibrés, synchronie temporelle forte.
        Attendu: Score élevé (70-100), classification 'entity_unique' ou 'economic_partner'
        """
        transactions = []

        # 20 paires de transactions sur 40 jours
        for i in range(20):
            # addr1 -> addr2 (envoi)
            transactions.append(self._tx('addr1', 'addr2', 5.0,
                                         days_ago=i*2, hours_offset=0))
            # addr2 -> addr1 (retour rapide, ~30 min)
            transactions.append(self._tx('addr2', 'addr1', 4.8,
                                         days_ago=i*2, hours_offset=0.5))

        return SyntheticScenario(
            name="strong_correlation",
            description="Forte corrélation bidirectionnelle (même entité probable)",
            address1=self.base_addresses['addr1'],
            address2=self.base_addresses['addr2'],
            transactions=transactions,
            expected_score_range=(50.0, 100.0),
            expected_classification="economic_partner"
        )

    def scenario_2_weak_correlation(self) -> SyntheticScenario:
        """Scénario 2: Corrélation faible (contact occasionnel).

        Pattern: Quelques transactions unidirectionnelles, anciennes,
        volumes faibles et irréguliers.
        Attendu: Score faible (10-30), classification 'occasional_contact'
        """
        transactions = []

        # 3 transactions unidirectionnelles sur 6 mois
        for i in [180, 120, 60]:
            transactions.append(self._tx('addr1', 'addr2', 0.5,
                                         days_ago=i))

        return SyntheticScenario(
            name="weak_correlation",
            description="Corrélation faible (contact occasionnel)",
            address1=self.base_addresses['addr1'],
            address2=self.base_addresses['addr2'],
            transactions=transactions,
            expected_score_range=(5.0, 30.0),
            expected_classification="occasional_contact"
        )

    def scenario_3_indirect_path(self) -> SyntheticScenario:
        """Scénario 3: Chemin indirect via intermédiaire.

        Pattern: addr1 -> inter -> addr2, pas de transaction directe.
        Les flux sont cohérents (volume conservé, temporalité respectée).
        Attendu: Score indirect significatif, total modéré (20-50)
        """
        transactions = []

        # addr1 envoie à l'intermédiaire
        for i in range(8):
            transactions.append(self._tx('addr1', 'inter1', 10.0,
                                         days_ago=i*5, hours_offset=0))

        # L'intermédiaire transfère à addr2 (même jour, volume légèrement inférieur)
        for i in range(8):
            transactions.append(self._tx('inter1', 'addr2', 9.8,
                                         days_ago=i*5, hours_offset=2))

        return SyntheticScenario(
            name="indirect_path",
            description="Chemin indirect via intermédiaire (pas de lien direct)",
            address1=self.base_addresses['addr1'],
            address2=self.base_addresses['addr2'],
            transactions=transactions,
            expected_score_range=(15.0, 50.0),
            expected_classification="structural_relation"
        )

    def scenario_4_hub_pattern(self) -> SyntheticScenario:
        """Scénario 4: Pattern de hub (exchange ou service).

        Pattern: addr1 et addr2 utilisent tous les deux le même hub,
        mais pas de transactions directes entre eux.
        Attendu: Score indirect faible à modéré (hub = pénalité),
        classification 'structural_relation' ou 'no_correlation'
        """
        transactions = []

        # addr1 utilise le hub fréquemment
        for i in range(15):
            transactions.append(self._tx('addr1', 'hub', 2.0,
                                         days_ago=i*3, hours_offset=0))
            transactions.append(self._tx('hub', 'addr1', 1.9,
                                         days_ago=i*3, hours_offset=1))

        # addr2 utilise aussi le hub
        for i in range(12):
            transactions.append(self._tx('addr2', 'hub', 3.0,
                                         days_ago=i*4, hours_offset=0.5))
            transactions.append(self._tx('hub', 'addr2', 2.95,
                                         days_ago=i*4, hours_offset=1.5))

        return SyntheticScenario(
            name="hub_pattern",
            description="Pattern de hub (utilisent le même service)",
            address1=self.base_addresses['addr1'],
            address2=self.base_addresses['addr2'],
            transactions=transactions,
            expected_score_range=(5.0, 40.0),
            expected_classification="structural_relation"
        )

    def scenario_5_arbitrage_pattern(self) -> SyntheticScenario:
        """Scénario 5: Pattern d'arbitrage (synchronie forte).

        Pattern: Transactions très rapprochées dans le temps (< 20 min),
        volumes identiques, bidirectionnel.
        Attendu: Synchronie élevée, score modéré à élevé
        """
        transactions = []

        # 15 cycles d'arbitrage sur 30 jours
        for i in range(15):
            # Achat rapide
            transactions.append(self._tx('addr1', 'addr2', 50.0,
                                         days_ago=i*2, hours_offset=10))
            # Revente très rapide (5 min)
            transactions.append(self._tx('addr2', 'addr1', 49.5,
                                         days_ago=i*2, hours_offset=10.08))

        return SyntheticScenario(
            name="arbitrage_pattern",
            description="Pattern d'arbitrage (synchronie temporelle forte)",
            address1=self.base_addresses['addr1'],
            address2=self.base_addresses['addr2'],
            transactions=transactions,
            expected_score_range=(40.0, 80.0),
            expected_classification="economic_partner"
        )

    def scenario_6_one_way_flow(self) -> SyntheticScenario:
        """Scénario 6: Flux unidirectionnel constant.

        Pattern: addr1 envoie régulièrement à addr2, jamais de retour.
        Pourrait être un salaire, un paiement de service, etc.
        Attendu: Équilibre = 0, score modéré (30-50)
        """
        transactions = []

        # 12 paiements mensuels
        for i in range(12):
            transactions.append(self._tx('addr1', 'addr2', 2.5,
                                         days_ago=i*30))

        return SyntheticScenario(
            name="one_way_flow",
            description="Flux unidirectionnel constant (paiements réguliers)",
            address1=self.base_addresses['addr1'],
            address2=self.base_addresses['addr2'],
            transactions=transactions,
            expected_score_range=(20.0, 50.0),
            expected_classification="economic_partner"
        )

    def generate_all_scenarios(self) -> List[SyntheticScenario]:
        """Génère tous les scénarios."""
        return [
            self.scenario_1_strong_correlation(),
            self.scenario_2_weak_correlation(),
            self.scenario_3_indirect_path(),
            self.scenario_4_hub_pattern(),
            self.scenario_5_arbitrage_pattern(),
            self.scenario_6_one_way_flow(),
        ]


def build_graph_from_transactions(transactions: List[Dict]) -> nx.MultiDiGraph:
    """Construit un graphe NetworkX à partir des transactions."""
    graph = nx.MultiDiGraph()

    for tx in transactions:
        sender = tx['from'].lower()
        receiver = tx['to'].lower()

        graph.add_edge(
            sender,
            receiver,
            weight=tx['value_eth'],
            weight_wei=tx['value_wei'],
            time=tx['block_time'],
            hash=tx['hash']
        )

    return graph


def analyze_scenario(scenario: SyntheticScenario) -> Dict:
    """Analyse un scénario et retourne les résultats détaillés."""
    graph = build_graph_from_transactions(scenario.transactions)
    scorer = TemporalScorer(graph)

    score = scorer.score(scenario.address1, scenario.address2)
    classification = scorer._classify_score(score.direct)

    # Calculer quelques statistiques
    df = pd.DataFrame(scenario.transactions)
    direct_tx = df[
        ((df['from'] == scenario.address1) & (df['to'] == scenario.address2)) |
        ((df['from'] == scenario.address2) & (df['to'] == scenario.address1))
    ]

    stats = {
        'total_transactions': len(df),
        'direct_transactions': len(direct_tx),
        'total_volume': df['value_eth'].sum(),
        'direct_volume': direct_tx['value_eth'].sum() if len(direct_tx) > 0 else 0,
    }

    return {
        'scenario': scenario,
        'score': score,
        'classification': classification,
        'stats': stats,
        'in_expected_range': scenario.expected_score_range[0] <= score.total <= scenario.expected_score_range[1],
        'expected_classification_match': classification == scenario.expected_classification or
                                        classification in ['occasional_contact', 'structural_relation']
    }


def create_interactive_visualization(scenario: SyntheticScenario, output_dir: str = "output/synthetic"):
    """Crée une visualisation interactive pour un scénario."""
    graph = build_graph_from_transactions(scenario.transactions)

    # Créer les tables de relation
    addr1 = Address(scenario.address1)
    addr2 = Address(scenario.address2)

    scorer = TemporalScorer(graph)

    # Calculer tous les scores
    from src.domain.models import AddressRelationshipTable, RelationshipScore

    relationships1 = {}
    relationships2 = {}

    for node in graph.nodes():
        if node == scenario.address1.lower() or node == scenario.address2.lower():
            continue

        target = Address(node)

        # Score depuis addr1
        score1 = scorer.score(scenario.address1, node)
        rel1 = RelationshipScore(
            source=addr1,
            target=target,
            direct_score=score1.direct,
            indirect_score=score1.indirect,
            confidence=score1.confidence,
            metrics=score1.metrics
        )
        relationships1[node] = rel1

        # Score depuis addr2
        score2 = scorer.score(scenario.address2, node)
        rel2 = RelationshipScore(
            source=addr2,
            target=target,
            direct_score=score2.direct,
            indirect_score=score2.indirect,
            confidence=score2.confidence,
            metrics=score2.metrics
        )
        relationships2[node] = rel2

    table1 = AddressRelationshipTable(main_address=addr1, relationships=relationships1)
    table2 = AddressRelationshipTable(main_address=addr2, relationships=relationships2)

    # Créer la visualisation
    visualizer = InteractiveGraphVisualizer(output_dir=output_dir)
    visualizer.set_relationship_tables([table1, table2])

    output_path = visualizer.visualize(
        graph=graph,
        main_addresses=[addr1, addr2],
        title=f"Synthetic: {scenario.name}",
        auto_open=False
    )

    return output_path


def main():
    """Point d'entrée principal."""
    print("=" * 80)
    print("GÉNÉRATION DE DONNÉES SYNTHÉTIQUES - VALIDATION DU SCORING")
    print("=" * 80)

    generator = SyntheticDataGenerator()
    scenarios = generator.generate_all_scenarios()

    print(f"\n{len(scenarios)} scénarios générés:\n")

    results = []

    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{'─' * 80}")
        print(f"SCÉNARIO {i}: {scenario.name.upper()}")
        print(f"{'─' * 80}")
        print(f"Description: {scenario.description}")
        print(f"Transactions: {len(scenario.transactions)}")
        print(f"Attendu: score dans [{scenario.expected_score_range[0]:.1f}, "
              f"{scenario.expected_score_range[1]:.1f}], classification '{scenario.expected_classification}'")

        # Analyser le scénario
        result = analyze_scenario(scenario)
        results.append(result)

        score = result['score']
        stats = result['stats']

        print(f"\n📊 RÉSULTATS:")
        print(f"  Score Total:    {score.total:.2f}/100 {'✓' if result['in_expected_range'] else '✗'}")
        print(f"  Score Direct:   {score.direct:.4f}")
        print(f"  Score Indirect: {score.indirect:.4f}")
        print(f"  Classification: {result['classification']} {'✓' if result['expected_classification_match'] else '✗'}")
        print(f"  Confiance:      {score.confidence}")

        print(f"\n📈 DIMENSIONS:")
        breakdown = score.metrics.get('score_breakdown', {})
        print(f"  Intensité:  {breakdown.get('intensite', 0)*100:.1f}%")
        print(f"  Récence:    {breakdown.get('recence', 0)*100:.1f}%")
        print(f"  Synchronie: {breakdown.get('synchronie', 0)*100:.1f}%")
        print(f"  Équilibre:  {breakdown.get('equilibre', 0)*100:.1f}%")

        print(f"\n📉 STATISTIQUES:")
        print(f"  Transactions totales: {stats['total_transactions']}")
        print(f"  Transactions directes: {stats['direct_transactions']}")
        print(f"  Volume total: {stats['total_volume']:.2f} ETH")
        print(f"  Volume direct: {stats['direct_volume']:.2f} ETH")

        # Créer la visualisation
        print(f"\n🎨 Création de la visualisation...", end=" ")
        try:
            output_path = create_interactive_visualization(scenario)
            print(f"OK -> {output_path}")
        except Exception as e:
            print(f"ERREUR: {e}")

    # Résumé
    print(f"\n{'=' * 80}")
    print("RÉSUMÉ")
    print(f"{'=' * 80}")

    passed = sum(1 for r in results if r['in_expected_range'])
    total = len(results)

    print(f"\nTests dans la plage attendue: {passed}/{total}")

    if passed == total:
        print("\n✅ TOUS LES SCÉNARIOS SONT VALIDES")
    else:
        print("\n⚠️  Certains scénarios sont hors plage:")
        for r in results:
            if not r['in_expected_range']:
                s = r['scenario']
                print(f"  - {s.name}: {r['score'].total:.1f} (attendu: {s.expected_score_range})")

    print(f"\nLes visualisations sont dans: output/synthetic/")


if __name__ == "__main__":
    main()
