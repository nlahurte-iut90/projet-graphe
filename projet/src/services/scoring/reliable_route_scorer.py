"""Scorer basé sur les routes fiables avec cohérence temporelle."""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import math
import statistics
import networkx as nx

from src.services.scoring.base import SimilarityStrategy, NodeScore


class ReliableRouteScorer(SimilarityStrategy):
    """
    Scorer basé sur les routes fiables entre deux nœuds.

    Évalue la fiabilité des chemins indirects via:
    - Cohérence temporelle (transactions coordonnées dans le temps)
    - Fiabilité des arêtes (volume + fréquence)
    - Multiplicité des chemins indépendants

    Plus un chemin a des transactions coordonnées dans le temps,
    plus il suggère une relation réelle entre les adresses.
    """

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        max_depth: int = 3,
        min_edge_reliability: float = 0.1
    ):
        super().__init__(graph)
        self.max_depth = max_depth
        self.min_edge_reliability = min_edge_reliability

    def get_name(self) -> str:
        return "ReliableRouteScorer"

    def get_description(self) -> str:
        return ("Routes fiables avec cohérence temporelle - "
                "détecte les patterns coordonnés")

    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Score basé sur les routes fiables entre main_address et node.
        """
        if main_address == node:
            return NodeScore(
                total=100.0,
                activity=100.0,
                proximity=100.0,
                recency=100.0,
                metrics={'self': True}
            )

        if main_address not in self.graph or node not in self.graph:
            return NodeScore(
                total=0.0,
                activity=0.0,
                proximity=0.0,
                recency=0.0,
                metrics={'error': 'Node not in graph'}
            )

        # Trouver tous les chemins fiables
        all_paths = self._find_reliable_paths(main_address, node)

        if not all_paths:
            return NodeScore(
                total=0.0,
                activity=0.0,
                proximity=0.0,
                recency=0.0,
                metrics={'reliable_paths': 0}
            )

        # Agréger les scores des chemins
        total_reliability = sum(path['reliability'] for path in all_paths)
        best_path_score = max(path['score'] for path in all_paths)

        # Bonus pour cohérence temporelle
        temporal_score = self._calc_temporal_coherence(all_paths)

        # Score combiné
        combined = min(
            best_path_score * (1 + temporal_score * 0.5),
            100.0
        )

        # Activité = fiabilité agrégée
        activity = min(total_reliability * 100, 100.0)

        # Proximité = meilleur chemin
        proximity = best_path_score

        # Récence = cohérence temporelle
        recency = temporal_score * 100

        return NodeScore(
            total=round(combined, 2),
            activity=round(activity, 2),
            proximity=round(proximity, 2),
            recency=round(recency, 2),
            metrics={
                'reliable_paths': len(all_paths),
                'temporal_coherence': temporal_score,
                'total_reliability': total_reliability,
                'best_path_score': best_path_score,
                'path_details': [
                    {
                        'path': ' -> '.join(p['path'][:3]) + '...' if len(p['path']) > 3 else ' -> '.join(p['path']),
                        'score': round(p['score'], 2),
                        'reliability': round(p['reliability'], 2),
                        'length': p['length']
                    }
                    for p in all_paths[:5]  # Top 5 chemins
                ]
            }
        )

    def _find_reliable_paths(self, source: str, target: str) -> List[Dict]:
        """
        Trouve les chemins fiables avec cohérence temporelle.

        Returns:
            Liste de dictionnaires avec 'path', 'score', 'reliability', etc.
        """
        paths = []

        # Chercher dans les deux directions
        for start, end in [(source, target), (target, source)]:
            try:
                for path in nx.all_simple_paths(
                    self.graph, start, end, cutoff=self.max_depth
                ):
                    if len(path) <= 2:  # Ignorer connexions directes
                        continue

                    path_info = self._evaluate_path(path)
                    if path_info and path_info['reliability'] >= self.min_edge_reliability:
                        paths.append(path_info)

            except nx.NetworkXNoPath:
                continue

        # Trier par score décroissant
        paths.sort(key=lambda x: x['score'], reverse=True)
        return paths

    def _evaluate_path(self, path: List[str]) -> Optional[Dict]:
        """
        Évalue la fiabilité d'un chemin spécifique.

        Returns:
            Dict avec les métriques du chemin ou None si trop peu fiable
        """
        reliability = 1.0
        timestamps = []
        edge_details = []

        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            edge_data = self._get_edge_data(u, v)

            # Fiabilité de l'arête: volume + fréquence
            tx_count = edge_data.get('tx_count', 0)
            volume = edge_data.get('total_volume', 0)

            if tx_count == 0:
                return None

            # Score de fiabilité de l'arête
            vol_score = min(math.log10(volume + 1) / 3, 1.0)
            freq_score = min(tx_count / 5, 1.0)
            edge_reliability = (vol_score + freq_score) / 2

            reliability *= edge_reliability

            # Collecter timestamps
            for ts in edge_data.get('timestamps', []):
                parsed_ts = self._parse_timestamp(ts)
                if parsed_ts:
                    timestamps.append((i, parsed_ts))

            edge_details.append({
                'from': u[:8] + '...',
                'to': v[:8] + '...',
                'reliability': edge_reliability,
                'tx_count': tx_count,
                'volume': volume
            })

        # Pénalité de longueur
        decay = 0.7 ** (len(path) - 2)
        reliability *= decay

        # Bonus de cohérence temporelle
        temporal_bonus = self._calc_path_temporal_coherence(timestamps, len(path) - 1)

        final_score = reliability * 100 * (1 + temporal_bonus)

        return {
            'path': path,
            'score': final_score,
            'reliability': reliability,
            'temporal_bonus': temporal_bonus,
            'length': len(path) - 1,
            'timestamps': timestamps,
            'edge_details': edge_details
        }

    def _calc_path_temporal_coherence(
        self,
        timestamps: List[Tuple[int, datetime]],
        path_length: int
    ) -> float:
        """
        Calcule le bonus de cohérence temporelle pour un chemin.

        Un chemin avec des transactions proches dans le temps
        suggère une coordination.

        Returns:
            Bonus entre 0 et 1
        """
        if len(timestamps) < 2:
            return 0.0

        # Extraire les timestamps
        times = [ts for _, ts in timestamps]

        if len(times) < 2:
            return 0.0

        # Calculer la variance temporelle
        try:
            # Convertir en timestamps UNIX pour calcul
            unix_times = [t.timestamp() for t in times]
            variance = statistics.variance(unix_times)

            # Normaliser: faible variance = haute cohérence
            # Variance de 1 jour = bonus faible
            # Variance de 1 heure = bonus élevé
            seconds_in_day = 24 * 3600
            coherence = max(0, 1 - variance / (seconds_in_day ** 2))

            return coherence ** 0.5  # Racine carrée pour adoucir

        except statistics.StatisticsError:
            return 0.0

    def _calc_temporal_coherence(self, paths: List[Dict]) -> float:
        """
        Calcule la cohérence temporelle globale entre les chemins.

        Chemins avec timestamps similaires suggèrent coordination.

        Returns:
            Score de cohérence entre 0 et 1
        """
        if len(paths) < 2:
            return 0.0

        # Extraire les timestamps moyens de chaque chemin
        path_times = []
        for p in paths:
            if 'timestamps' in p and p['timestamps']:
                times = [t.timestamp() for _, t in p['timestamps']]
                if times:
                    path_times.append(statistics.mean(times))

        if len(path_times) < 2:
            return 0.0

        # Variance des timestamps moyens
        try:
            variance = statistics.variance(path_times)
            # Normaliser: faible variance = haute cohérence
            max_var = (30 * 24 * 3600) ** 2  # 30 jours en secondes, au carré
            coherence = max(0, 1 - variance / max_var)
            return coherence

        except statistics.StatisticsError:
            return 0.0

    def _parse_timestamp(self, ts) -> Optional[datetime]:
        """Parse un timestamp en datetime."""
        if ts is None or ts == 'unknown':
            return None

        try:
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace('Z', '+00:00'))
            elif isinstance(ts, datetime):
                return ts
        except (ValueError, TypeError):
            pass

        return None

    def get_reliable_paths_details(self, source: str, target: str, top_n: int = 5) -> List[Dict]:
        """
        Retourne les détails des chemins les plus fiables.

        Utile pour l'analyse et la visualisation.
        """
        paths = self._find_reliable_paths(source, target)
        return [
            {
                'path': p['path'],
                'score': p['score'],
                'reliability': p['reliability'],
                'temporal_bonus': p['temporal_bonus'],
                'length': p['length'],
                'edges': p.get('edge_details', [])
            }
            for p in paths[:top_n]
        ]
