"""Scorer initial pour évaluer les nœuds de base avant expansion."""

import math
from datetime import datetime
from typing import Dict, Any, List, Optional

import networkx as nx

from src.services.scoring.base import SimilarityStrategy, NodeScore


class InitialScorer(SimilarityStrategy):
    """
    Scorer initial basé sur volume, fréquence et bidirectionnalité.

    Formule: Correlation = 0.5 * Score_volume + 0.3 * Score_freq + 0.2 * Score_bidir

    Ce scorer est conçu pour évaluer les nœuds de base (voisins directs)
    avant l'expansion du graphe. Il utilise uniquement les transactions
    directes entre l'adresse principale et le nœud évalué.
    """

    W_VOLUME = 0.5  # Poids du score de volume
    W_FREQ = 0.3  # Poids du score de fréquence
    W_BIDIR = 0.2  # Poids du score de bidirectionnalité
    EPSILON = 1e-10  # Constante pour éviter division par zéro
    SYNC_WINDOW_BLOCKS = 10000  # ~34 jours de blocs Ethereum
    ETH_BLOCK_TIME = 12  # Secondes par bloc Ethereum
    ETH_GENESIS_TIMESTAMP = 1438269970  # Timestamp du bloc 0 (30 juillet 2015)

    def __init__(self, graph: nx.MultiDiGraph):
        super().__init__(graph)

    def get_name(self) -> str:
        """Retourne le nom de la stratégie."""
        return "InitialScorer"

    def get_description(self) -> str:
        """Retourne une description de la stratégie."""
        return (
            "Scorer initial basé sur trois dimensions: "
            "volume (50%% - équilibre des flux), "
            "fréquence (30%% - régularité des transactions), "
            "bidirectionnalité (20%% - qualité réciproque). "
            "Conçu pour évaluer les nœuds de base avant expansion."
        )

    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule le score de corrélation entre main_address et node.

        Args:
            main_address: Adresse principale de référence
            node: Nœud cible à évaluer

        Returns:
            NodeScore avec les dimensions et métriques
        """
        # Extraction des transactions
        tx_out = self._get_tx_out(main_address, node)
        tx_in = self._get_tx_in(main_address, node)

        # Cas sans aucune transaction
        if not tx_out and not tx_in:
            return NodeScore(
                total=0.0,
                activity=0.0,
                proximity=0.0,
                recency=0.0,
                metrics={
                    "vol_out": 0.0,
                    "vol_in": 0.0,
                    "n_out": 0,
                    "n_in": 0,
                    "score_volume": 0.0,
                    "score_freq": 0.0,
                    "score_bidir": 0.0,
                },
            )

        # Calcul des sous-scores
        score_volume = self._calc_volume_score(tx_out, tx_in)
        score_freq = self._calc_freq_score(tx_out, tx_in)
        score_bidir = self._calc_bidir_score(tx_out, tx_in)

        # Calcul du score total pondéré
        total = (
            self.W_VOLUME * score_volume * 100
            + self.W_FREQ * score_freq
            + self.W_BIDIR * score_bidir
        )

        # Calcul des volumes pour les métriques
        vol_out = sum(tx["weight"] for tx in tx_out)
        vol_in = sum(tx["weight"] for tx in tx_in)

        return NodeScore(
            total=round(total, 2),
            activity=round(score_volume * 100, 2),  # Volume -> Activity
            proximity=round(score_freq, 2),  # Freq -> Proximity
            recency=round(score_bidir, 2),  # Bidir -> Recency
            metrics={
                "vol_out": round(vol_out, 4),
                "vol_in": round(vol_in, 4),
                "n_out": len(tx_out),
                "n_in": len(tx_in),
                "score_volume": round(score_volume, 4),
                "score_freq": round(score_freq, 4),
                "score_bidir": round(score_bidir, 4),
            },
        )

    def _get_tx_out(self, main_address: str, node: str) -> List[Dict[str, Any]]:
        """
        Extrait les transactions sortantes (main_address -> node).

        Args:
            main_address: Adresse principale (expéditeur)
            node: Nœud cible (destinataire)

        Returns:
            Liste des transactions avec weight et time
        """
        edges = []
        edge_data = self.graph.get_edge_data(main_address, node, default={})
        for key, data in edge_data.items():
            edge = dict(data)
            edge["from"] = main_address
            edge["to"] = node
            edges.append(edge)
        return edges

    def _get_tx_in(self, main_address: str, node: str) -> List[Dict[str, Any]]:
        """
        Extrait les transactions entrantes (node -> main_address).

        Args:
            main_address: Adresse principale (destinataire)
            node: Nœud cible (expéditeur)

        Returns:
            Liste des transactions avec weight et time
        """
        edges = []
        edge_data = self.graph.get_edge_data(node, main_address, default={})
        for key, data in edge_data.items():
            edge = dict(data)
            edge["from"] = node
            edge["to"] = main_address
            edges.append(edge)
        return edges

    def _calc_volume_score(
        self, tx_out: List[Dict[str, Any]], tx_in: List[Dict[str, Any]]
    ) -> float:
        """
        Calcule le score de volume basé sur l'équilibre des flux.

        Args:
            tx_out: Transactions sortantes
            tx_in: Transactions entrantes

        Returns:
            Score de volume dans [0, 1]
        """
        vol_out = sum(tx.get("weight", 0) for tx in tx_out)
        vol_in = sum(tx.get("weight", 0) for tx in tx_in)

        total_vol = vol_out + vol_in
        if total_vol < self.EPSILON:
            return 0.0

        # Pénalité de déséquilibre (0 = parfaitement équilibré, 1 = complètement déséquilibré)
        disparity = abs(vol_out - vol_in) / (total_vol + self.EPSILON)

        # Score de base basé sur le volume total (logarithmique, saturé à 100 ETH)
        # log10(100 + 1) / 2 ≈ 1.0
        volume_factor = min(math.log10(total_vol + 1) / 2, 1.0)

        # Score final: volume * (1 - pénalité de déséquilibre)
        # Un flux parfaitement équilibré (disparity=0) garde 100% du volume_factor
        # Un flux complètement unidirectionnel (disparity=1) garde 0% mais
        # on utilise une pénalité douce: (1 - 0.5 * disparity) pour garder 50% dans le pire cas
        balance_factor = 1 - 0.5 * disparity

        score_volume = volume_factor * balance_factor
        return score_volume

    def _calc_freq_score(
        self, tx_out: List[Dict[str, Any]], tx_in: List[Dict[str, Any]]
    ) -> float:
        """
        Calcule le score de fréquence basé sur la régularité.

        Args:
            tx_out: Transactions sortantes
            tx_in: Transactions entrantes

        Returns:
            Score de fréquence dans [0, 100]
        """
        n_out = len(tx_out)
        n_in = len(tx_in)
        total_tx = n_out + n_in

        if total_tx == 0:
            return 0.0

        # Indice de Jaccard directionnel (overlap) - bonus pour bidirectionnalité
        # Si unidirectionnel, overlap = 0 mais on garde quand même un score de base
        overlap = (2 * min(n_out, n_in)) / (n_out + n_in + self.EPSILON)

        # Échelle logarithmique basée sur le nombre total de transactions
        # Même sans overlap (unidirectionnel), on a un score basé sur la fréquence
        freq_factor = math.log(1 + total_tx)

        # Combinaison: 60% basé sur la fréquence pure, 40% sur l'overlap
        # En cas unidirectionnel: on garde 60% du score
        # En cas bidirectionnel parfait: on garde 100% du score
        combined_factor = 0.6 + 0.4 * overlap

        # Normalisation à [0, 100]
        # log(1+100) ≈ 4.6, donc 100 tx donnent ~100 points
        score_freq = min(combined_factor * freq_factor / 4.6 * 100, 100.0)
        return score_freq

    def _calc_bidir_score(
        self, tx_out: List[Dict[str, Any]], tx_in: List[Dict[str, Any]]
    ) -> float:
        """
        Calcule le score de bidirectionnalité basé sur la qualité réciproque.

        Args:
            tx_out: Transactions sortantes
            tx_in: Transactions entrantes

        Returns:
            Score de bidirectionnalité dans [0, 100]
        """
        n_out = len(tx_out)
        n_in = len(tx_in)

        # Pas de bidirectionnalité si unidirectionnel
        if n_out == 0 or n_in == 0:
            return 0.0

        # Ratio de réciprocité
        ratio_bidir = min(n_out, n_in) / (max(n_out, n_in) + self.EPSILON)

        # Synchronicité temporelle (approximation via timestamps)
        try:
            avg_out = self._calc_avg_block(tx_out)
            avg_in = self._calc_avg_block(tx_in)

            if avg_out is None or avg_in is None:
                # Pas de timestamps valides, on utilise juste le ratio
                score_bidir = ratio_bidir * 0.7 * 100
            else:
                time_diff = abs(avg_out - avg_in)
                sync = 1 - min(time_diff / self.SYNC_WINDOW_BLOCKS, 1.0)

                # Agrégation: 70% ratio, 30% synchronicité
                score_bidir = ratio_bidir * (0.7 + 0.3 * sync) * 100
        except (ValueError, TypeError):
            # En cas d'erreur de parsing, on utilise juste le ratio
            score_bidir = ratio_bidir * 0.7 * 100

        return score_bidir

    def _calc_avg_block(
        self, transactions: List[Dict[str, Any]]
    ) -> Optional[float]:
        """
        Calcule le numéro de bloc moyen pour une liste de transactions.

        Args:
            transactions: Liste de transactions avec timestamps

        Returns:
            Numéro de bloc moyen ou None si pas de timestamps valides
        """
        blocks = []
        for tx in transactions:
            ts = tx.get("time")
            if ts and ts != "unknown":
                block = self._approximate_block(ts)
                if block is not None:
                    blocks.append(block)

        if not blocks:
            return None

        return sum(blocks) / len(blocks)

    def _approximate_block(self, timestamp: Any) -> Optional[float]:
        """
        Convertit un timestamp en numéro de bloc approximatif.

        Note: Le graphe stocke des timestamps, pas des numéros de bloc.
        Conversion approximative: Ethereum ~12 secondes par bloc.

        Args:
            timestamp: Timestamp (str ISO ou datetime)

        Returns:
            Numéro de bloc approximatif ou None si invalide
        """
        try:
            if isinstance(timestamp, str):
                # Parser ISO format
                ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            elif isinstance(timestamp, datetime):
                ts = timestamp
            else:
                return None

            # Conversion en timestamp Unix
            seconds_since_genesis = ts.timestamp() - self.ETH_GENESIS_TIMESTAMP

            # Conversion en blocs (approximatif)
            blocks = seconds_since_genesis / self.ETH_BLOCK_TIME

            return max(0, blocks)  # Pas de blocs négatifs
        except (ValueError, TypeError, AttributeError):
            return None
