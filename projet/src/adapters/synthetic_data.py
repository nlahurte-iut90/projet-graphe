"""Générateur de données synthétiques pour tester le graphe de corrélation.

Ce module fournit des jeux de données synthétiques pour valider toutes les
fonctionnalités du graphe sans dépendre de l'API Dune.
"""
import random
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import pandas as pd

from src.domain.models import Address, Transaction


@dataclass
class SyntheticDataset:
    """Un jeu de données synthétiques complet."""
    name: str
    description: str
    address1: str
    address2: str
    transactions_df: pd.DataFrame
    expected_direct_score: float
    expected_indirect_paths: int
    expected_propagation_depth: int


class SyntheticDataGenerator:
    """Générateur de données de transaction synthétiques."""

    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)
        self._address_counter = 0
        self._tx_counter = 0

    def _generate_address(self, prefix: str = "0x") -> str:
        """Génère une adresse Ethereum synthétique unique (en minuscules)."""
        self._address_counter += 1
        # Format: 0x + 40 caractères hex (minuscules pour compatibilité avec Address)
        suffix = hashlib.sha256(f"addr_{self._address_counter}".encode()).hexdigest()[:40]
        return f"{prefix}{suffix}".lower()

    def _generate_tx_hash(self) -> str:
        """Génère un hash de transaction unique."""
        self._tx_counter += 1
        return f"0x{hashlib.sha256(f"tx_{self._tx_counter}".encode()).hexdigest()}"

    def _random_timestamp(self, days_back: int = 30) -> datetime:
        """Génère un timestamp aléatoire dans les derniers jours."""
        now = datetime.now()
        delta = timedelta(
            days=self.random.randint(0, days_back),
            hours=self.random.randint(0, 23),
            minutes=self.random.randint(0, 59)
        )
        return now - delta

    def _create_transaction(
        self,
        from_addr: str,
        to_addr: str,
        value_eth: float,
        timestamp: Optional[datetime] = None
    ) -> Dict:
        """Crée un enregistrement de transaction."""
        value_wei = int(value_eth * 1e18)
        return {
            "from": from_addr,
            "to": to_addr,
            "value_eth": value_eth,
            "value_wei": value_wei,
            "hash": self._generate_tx_hash(),
            "block_time": timestamp or self._random_timestamp()
        }

    def _create_dataframe(self, transactions: List[Dict]) -> pd.DataFrame:
        """Convertit une liste de transactions en DataFrame."""
        df = pd.DataFrame(transactions)
        if not df.empty:
            df = df.drop_duplicates(subset=['hash'])
        return df

    # =========================================================================
    # SCÉNARIO 1: Connexion directe forte
    # =========================================================================
    def generate_strong_direct_connection(self) -> SyntheticDataset:
        """
        Deux adresses avec beaucoup de transactions directes entre elles.
        Attendu: high direct_score, pas de chemins indirects nécessaires.
        """
        addr1 = self._generate_address("0xA1")
        addr2 = self._generate_address("0xB1")

        transactions = []
        # 10 transactions dans chaque sens avec des montants significatifs
        for i in range(10):
            # A1 -> B1
            transactions.append(self._create_transaction(
                addr1, addr2,
                value_eth=self.random.uniform(1.0, 10.0),
                timestamp=datetime.now() - timedelta(hours=i*2)
            ))
            # B1 -> A1
            transactions.append(self._create_transaction(
                addr2, addr1,
                value_eth=self.random.uniform(0.5, 5.0),
                timestamp=datetime.now() - timedelta(hours=i*2 + 1)
            ))

        return SyntheticDataset(
            name="strong_direct",
            description="Forte connexion directe (20 transactions réciproques)",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=80.0,
            expected_indirect_paths=0,
            expected_propagation_depth=0
        )

    # =========================================================================
    # SCÉNARIO 2: Connexion faible/directe minime
    # =========================================================================
    def generate_weak_direct_connection(self) -> SyntheticDataset:
        """
        Deux adresses avec très peu de transactions directes.
        Attendu: low direct_score, l'algorithme doit chercher des chemins indirects.
        """
        addr1 = self._generate_address("0xA2")
        addr2 = self._generate_address("0xB2")

        transactions = []
        # Seulement 1 petite transaction
        transactions.append(self._create_transaction(
            addr1, addr2,
            value_eth=0.01,
            timestamp=datetime.now() - timedelta(days=30)
        ))

        return SyntheticDataset(
            name="weak_direct",
            description="Connexion directe faible (1 petite transaction)",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=10.0,
            expected_indirect_paths=0,
            expected_propagation_depth=0
        )

    # =========================================================================
    # SCÉNARIO 3: Chemins indirects (A -> X -> B)
    # =========================================================================
    def generate_indirect_paths(self, num_intermediaries: int = 3) -> SyntheticDataset:
        """
        A et B n'ont pas de transactions directes mais partagent des intermédiaires.
        Attendu: indirect_score élevé via les chemins A->X->B.
        """
        addr1 = self._generate_address("0xA3")
        addr2 = self._generate_address("0xB3")

        intermediaries = [self._generate_address(f"0xI3{i}") for i in range(num_intermediaries)]
        transactions = []

        for inter in intermediaries:
            # A3 -> Intermédiaire (transactions significatives)
            for _ in range(3):
                transactions.append(self._create_transaction(
                    addr1, inter,
                    value_eth=self.random.uniform(2.0, 8.0)
                ))
            # Intermédiaire -> B3 (transactions significatives)
            for _ in range(3):
                transactions.append(self._create_transaction(
                    inter, addr2,
                    value_eth=self.random.uniform(1.0, 5.0)
                ))

        return SyntheticDataset(
            name="indirect_paths",
            description=f"Chemins indirects via {num_intermediaries} intermédiaires",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=0.0,
            expected_indirect_paths=num_intermediaries,
            expected_propagation_depth=2
        )

    # =========================================================================
    # SCÉNARIO 4: Propagation multi-hop (A -> X -> Y -> B)
    # =========================================================================
    def generate_propagation_chain(self, chain_length: int = 3) -> SyntheticDataset:
        """
        Chaîne de propagation: A -> X1 -> X2 -> ... -> B
        Attendu: propagated_score significatif malgré l'absence de connexion directe.
        """
        addr1 = self._generate_address("0xA4")
        addr2 = self._generate_address("0xB4")

        # Créer une chaîne d'adresses
        chain = [self._generate_address(f"0xC4{i}") for i in range(chain_length - 1)]
        all_nodes = [addr1] + chain + [addr2]

        transactions = []
        # Créer des transactions le long de la chaîne
        for i in range(len(all_nodes) - 1):
            from_addr = all_nodes[i]
            to_addr = all_nodes[i + 1]
            # Transactions fortes pour une bonne propagation
            for _ in range(5):
                transactions.append(self._create_transaction(
                    from_addr, to_addr,
                    value_eth=self.random.uniform(5.0, 15.0)
                ))

        return SyntheticDataset(
            name="propagation_chain",
            description=f"Chaîne de propagation ({chain_length+1} hops)",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=0.0,
            expected_indirect_paths=0,
            expected_propagation_depth=chain_length + 1
        )

    # =========================================================================
    # SCÉNARIO 5: Réseau dense avec multiple chemins
    # =========================================================================
    def generate_dense_network(
        self,
        num_nodes: int = 10,
        edge_probability: float = 0.3
    ) -> SyntheticDataset:
        """
        Réseau dense avec beaucoup de nœuds et de connexions.
        Attendu: multiple chemins possibles, scores variés.
        """
        addr1 = self._generate_address("0xA5")
        addr2 = self._generate_address("0xB5")

        # Générer des nœuds aléatoires
        other_nodes = [self._generate_address(f"0xN5{i}") for i in range(num_nodes)]
        all_nodes = [addr1, addr2] + other_nodes

        transactions = []

        # Créer des transactions aléatoires entre les nœuds
        for i, from_addr in enumerate(all_nodes):
            for j, to_addr in enumerate(all_nodes):
                if i != j and self.random.random() < edge_probability:
                    num_tx = self.random.randint(1, 5)
                    for _ in range(num_tx):
                        transactions.append(self._create_transaction(
                            from_addr, to_addr,
                            value_eth=self.random.uniform(0.1, 5.0)
                        ))

        # S'assurer qu'il y a au moins un chemin entre A et B
        if not any(t['from'] == addr1 and t['to'] == addr2 for t in transactions):
            # Ajouter un chemin indirect garanti
            intermediate = other_nodes[0]
            transactions.append(self._create_transaction(addr1, intermediate, 10.0))
            transactions.append(self._create_transaction(intermediate, addr2, 8.0))

        return SyntheticDataset(
            name="dense_network",
            description=f"Réseau dense ({num_nodes} nœuds, probabilité {edge_probability})",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=50.0,
            expected_indirect_paths=num_nodes // 3,
            expected_propagation_depth=3
        )

    # =========================================================================
    # SCÉNARIO 6: Aucune connexion
    # =========================================================================
    def generate_no_connection(self) -> SyntheticDataset:
        """
        Deux adresses complètement isolées (aucune transaction entre elles).
        Attendu: tous les scores à 0.
        """
        addr1 = self._generate_address("0xA6")
        addr2 = self._generate_address("0xB6")

        transactions = []

        # Chaque adresse a des transactions mais pas entre elles
        other1 = self._generate_address("0xO6A")
        other2 = self._generate_address("0xO6B")

        for _ in range(5):
            transactions.append(self._create_transaction(addr1, other1, 5.0))
            transactions.append(self._create_transaction(other1, addr1, 3.0))
            transactions.append(self._create_transaction(addr2, other2, 7.0))
            transactions.append(self._create_transaction(other2, addr2, 4.0))

        return SyntheticDataset(
            name="no_connection",
            description="Aucune connexion entre les deux adresses",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=0.0,
            expected_indirect_paths=0,
            expected_propagation_depth=0
        )

    # =========================================================================
    # SCÉNARIO 7: Transactions anciennes vs récentes
    # =========================================================================
    def generate_recency_test(self) -> SyntheticDataset:
        """
        Test de la composante 'recency' du scoring.
        Transactions anciennes (faible score) vs récentes (fort score).
        """
        addr1 = self._generate_address("0xA7")
        addr2 = self._generate_address("0xB7")

        transactions = []

        # Anciennes transactions (il y a 1 an)
        old_time = datetime.now() - timedelta(days=365)
        for _ in range(5):
            transactions.append(self._create_transaction(
                addr1, addr2, 10.0, timestamp=old_time
            ))

        # Récentes transactions (hier)
        recent_time = datetime.now() - timedelta(days=1)
        for _ in range(2):
            transactions.append(self._create_transaction(
                addr1, addr2, 2.0, timestamp=recent_time
            ))

        return SyntheticDataset(
            name="recency_test",
            description="Test de la récence (anciennes vs récentes transactions)",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=60.0,  # Boosté par la récence
            expected_indirect_paths=0,
            expected_propagation_depth=0
        )

    # =========================================================================
    # SCÉNARIO 8: Grand écart de volume
    # =========================================================================
    def generate_volume_test(self) -> SyntheticDataset:
        """
        Test de la composante 'volume' du scoring.
        Beaucoup de petites transactions vs quelques grosses.
        """
        addr1 = self._generate_address("0xA8")
        addr2 = self._generate_address("0xB8")

        transactions = []

        # Beaucoup de petites transactions
        for _ in range(20):
            transactions.append(self._create_transaction(
                addr1, addr2, self.random.uniform(0.01, 0.1)
            ))

        # Quelques grosses transactions
        for _ in range(3):
            transactions.append(self._create_transaction(
                addr2, addr1, self.random.uniform(50.0, 100.0)
            ))

        return SyntheticDataset(
            name="volume_test",
            description="Test du volume (petites vs grosses transactions)",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=75.0,
            expected_indirect_paths=0,
            expected_propagation_depth=0
        )

    # =========================================================================
    # SCÉNARIO 9: Expansion de graphe complexe
    # =========================================================================
    def generate_expansion_test(self) -> SyntheticDataset:
        """
        Test de l'expansion du graphe avec plusieurs niveaux.
        """
        addr1 = self._generate_address("0xA9")
        addr2 = self._generate_address("0xB9")

        transactions = []

        # Niveau 1: voisins directs
        level1_a = [self._generate_address(f"0xL1A{i}") for i in range(3)]
        level1_b = [self._generate_address(f"0xL1B{i}") for i in range(3)]

        # Niveau 2: voisins des voisins
        level2 = [self._generate_address(f"0xL2{i}") for i in range(5)]

        # Connexions addr1 -> level1_a
        for node in level1_a:
            for _ in range(3):
                transactions.append(self._create_transaction(addr1, node, 5.0))

        # Connexions addr2 -> level1_b
        for node in level1_b:
            for _ in range(3):
                transactions.append(self._create_transaction(addr2, node, 5.0))

        # Expansion: level1_a -> level2
        for l1 in level1_a:
            for l2 in level2[:3]:
                transactions.append(self._create_transaction(l1, l2, 2.0))

        # Expansion: level1_b -> level2
        for l1 in level1_b:
            for l2 in level2[2:]:
                transactions.append(self._create_transaction(l1, l2, 2.0))

        # Un chemin indirect entre addr1 et addr2 via level2
        transactions.append(self._create_transaction(level2[2], addr2, 1.0))

        return SyntheticDataset(
            name="expansion_test",
            description="Test d'expansion de graphe (2 niveaux)",
            address1=addr1,
            address2=addr2,
            transactions_df=self._create_dataframe(transactions),
            expected_direct_score=0.0,
            expected_indirect_paths=3,
            expected_propagation_depth=3
        )

    # =========================================================================
    # GÉNÉRATION DE TOUS LES JEUX DE DONNÉES
    # =========================================================================
    def generate_all_datasets(self) -> List[SyntheticDataset]:
        """Génère tous les jeux de données de test."""
        return [
            self.generate_strong_direct_connection(),
            self.generate_weak_direct_connection(),
            self.generate_indirect_paths(num_intermediaries=3),
            self.generate_propagation_chain(chain_length=3),
            self.generate_dense_network(num_nodes=8, edge_probability=0.25),
            self.generate_no_connection(),
            self.generate_recency_test(),
            self.generate_volume_test(),
            self.generate_expansion_test(),
        ]


class SyntheticDuneAdapter:
    """
    Adaptateur compatible avec DuneAdapter mais utilisant des données synthétiques.

    Usage:
        adapter = SyntheticDuneAdapter(dataset_name="strong_direct")
        # ou
        adapter = SyntheticDuneAdapter()  # utilise le scénario par défaut
    """

    def __init__(self, dataset_name: str = "strong_direct", seed: int = 42):
        self.generator = SyntheticDataGenerator(seed=seed)
        self.datasets = {d.name: d for d in self.generator.generate_all_datasets()}

        if dataset_name not in self.datasets:
            available = ", ".join(self.datasets.keys())
            raise ValueError(f"Dataset '{dataset_name}' inconnu. Disponibles: {available}")

        self.current_dataset = self.datasets[dataset_name]
        self._cache = {}

    def get_transactions(self, address1: str, address2: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Simule get_transactions de DuneAdapter.
        Retourne les transactions du dataset actuel.
        """
        # Normaliser les adresses en minuscules
        addr1 = address1.lower()
        addr2 = address2.lower()

        df = self.current_dataset.transactions_df.copy()

        # Filtrer les transactions pertinentes pour ces deux adresses
        mask = (
            ((df['from'] == addr1) & (df['to'] == addr2)) |
            ((df['from'] == addr2) & (df['to'] == addr1)) |
            (df['from'] == addr1) | (df['to'] == addr1) |
            (df['from'] == addr2) | (df['to'] == addr2)
        )
        filtered = df[mask]

        if len(filtered) > limit:
            filtered = filtered.head(limit)

        return filtered if not filtered.empty else pd.DataFrame()

    def get_transactions_for_address(self, address: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Simule get_transactions_for_address de DuneAdapter.
        """
        # Normaliser l'adresse en minuscules
        addr = address.lower()

        df = self.current_dataset.transactions_df.copy()
        mask = (df['from'] == addr) | (df['to'] == addr)
        filtered = df[mask]

        if len(filtered) > limit:
            filtered = filtered.head(limit)

        return filtered if not filtered.empty else pd.DataFrame()

    def list_available_datasets(self) -> Dict[str, str]:
        """Liste tous les datasets disponibles avec leur description."""
        return {name: ds.description for name, ds in self.datasets.items()}

    def switch_dataset(self, name: str):
        """Change le dataset actif."""
        if name not in self.datasets:
            raise ValueError(f"Dataset '{name}' inconnu")
        self.current_dataset = self.datasets[name]


# Fonction utilitaire pour créer un dataset personnalisé
def create_custom_dataset(
    scenario: str,
    num_transactions: int = 10,
    value_range: Tuple[float, float] = (0.1, 10.0),
    reciprocal: bool = True,
    seed: int = 42
) -> SyntheticDataset:
    """
    Crée un dataset personnalisé avec des paramètres configurables.

    Args:
        scenario: Nom du scénario ('direct', 'indirect', 'chain', 'random')
        num_transactions: Nombre de transactions à générer
        value_range: Tuple (min, max) des montants en ETH
        reciprocal: Si True, génère des transactions dans les deux sens
        seed: Graine pour la reproductibilité
    """
    gen = SyntheticDataGenerator(seed=seed)
    addr1 = gen._generate_address("0xC1")
    addr2 = gen._generate_address("0xC2")

    transactions = []

    if scenario == "direct":
        for i in range(num_transactions):
            from_addr = addr1 if i % 2 == 0 else addr2 if reciprocal else addr1
            to_addr = addr2 if i % 2 == 0 else addr1 if reciprocal else addr2
            value = gen.random.uniform(*value_range)
            transactions.append(gen._create_transaction(from_addr, to_addr, value))

    elif scenario == "indirect":
        intermediaries = [gen._generate_address(f"0xI{i}") for i in range(3)]
        for inter in intermediaries:
            for _ in range(num_transactions // 3):
                transactions.append(gen._create_transaction(addr1, inter, gen.random.uniform(*value_range)))
                transactions.append(gen._create_transaction(inter, addr2, gen.random.uniform(*value_range)))

    elif scenario == "chain":
        nodes = [addr1] + [gen._generate_address(f"0xN{i}") for i in range(2)] + [addr2]
        for i in range(len(nodes) - 1):
            for _ in range(num_transactions // len(nodes)):
                transactions.append(gen._create_transaction(
                    nodes[i], nodes[i+1], gen.random.uniform(*value_range)
                ))

    elif scenario == "random":
        extra_nodes = [gen._generate_address(f"0xR{i}") for i in range(5)]
        all_nodes = [addr1, addr2] + extra_nodes
        for _ in range(num_transactions):
            from_addr = gen.random.choice(all_nodes)
            to_addr = gen.random.choice([n for n in all_nodes if n != from_addr])
            transactions.append(gen._create_transaction(
                from_addr, to_addr, gen.random.uniform(*value_range)
            ))

    else:
        raise ValueError(f"Scénario inconnu: {scenario}")

    return SyntheticDataset(
        name=f"custom_{scenario}",
        description=f"Dataset personnalisé: {scenario} ({num_transactions} tx)",
        address1=addr1,
        address2=addr2,
        transactions_df=gen._create_dataframe(transactions),
        expected_direct_score=50.0 if scenario == "direct" else 0.0,
        expected_indirect_paths=3 if scenario == "indirect" else 0,
        expected_propagation_depth=3 if scenario == "chain" else 0
    )
