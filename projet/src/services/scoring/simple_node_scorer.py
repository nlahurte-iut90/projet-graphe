"""Scorer simplifié pour évaluer la relation entre une main address et un nœud."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime
import math
import networkx as nx

from src.domain.models import Address


@dataclass
class NodeScore:
    """Résultat du scoring d'un nœud."""
    total: float
    activity: float
    proximity: float
    recency: float
    metrics: Dict[str, Any]
    
    def __repr__(self) -> str:
        return (f"NodeScore(total={self.total:.1f}, "
                f"activity={self.activity:.1f}, "
                f"proximity={self.proximity:.1f}, "
                f"recency={self.recency:.1f})")


class SimpleNodeScorer:
    """
    Scorer léger et interprétable pour la relation main_address ↔ nœud.
    
    Basé sur 3 dimensions:
    - Activité (50%): volume, fréquence, bidirectionnalité
    - Proximité (30%): distance dans le graphe
    - Récence (20%): fraîcheur de la dernière transaction
    """
    
    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph
        self._edge_cache: Dict[tuple, List[Dict]] = {}
    
    def score(self, main_address: str, node: str) -> NodeScore:
        """
        Calcule le score de relation entre la main address et un nœud.
        
        Args:
            main_address: Adresse principale (source)
            node: Nœud cible à évaluer
            
        Returns:
            NodeScore avec les 3 dimensions et le total
        """
        # Calcul des 3 dimensions
        activity = self._calc_activity(main_address, node)
        proximity = self._calc_proximity(main_address, node)
        recency = self._calc_recency(main_address, node)
        
        # Agrégation
        total = self._aggregate(activity, proximity, recency)
        
        # Métriques détaillées pour debug
        metrics = self._get_metrics(main_address, node)
        
        return NodeScore(
            total=round(total, 2),
            activity=round(activity, 2),
            proximity=round(proximity, 2),
            recency=round(recency, 2),
            metrics=metrics
        )
    
    def _get_all_edges(self, u: str, v: str) -> List[Dict]:
        """Récupère toutes les arêtes entre u et v (dans les deux sens)."""
        cache_key = (u, v)
        if cache_key in self._edge_cache:
            return self._edge_cache[cache_key]
        
        edges = []
        
        # u -> v
        forward = self.graph.get_edge_data(u, v, default={})
        for key, data in forward.items():
            edge_data = dict(data)
            edge_data['from'] = u
            edge_data['to'] = v
            edges.append(edge_data)
        
        # v -> u
        backward = self.graph.get_edge_data(v, u, default={})
        for key, data in backward.items():
            edge_data = dict(data)
            edge_data['from'] = v
            edge_data['to'] = u
            edges.append(edge_data)
        
        self._edge_cache[cache_key] = edges
        return edges
    
    def _calc_activity(self, u: str, v: str) -> float:
        """
        Score d'activité basé sur volume, fréquence et bidirectionnalité.
        
        Formule: 100 * (0.6 * volume_score + 0.3 * freq_score + 0.1 * bidirectional)
        """
        edges = self._get_all_edges(u, v)
        if not edges:
            return 0.0
        
        # Volume total
        total_volume = sum(e.get('weight', 0) for e in edges)
        tx_count = len(edges)
        
        # Bidirectionnel?
        has_uv = any(e['from'] == u for e in edges)
        has_vu = any(e['from'] == v for e in edges)
        bidirectional_ratio = 1.0 if (has_uv and has_vu) else 0.5
        
        # Volume: log10 normalisé (0-1), saturé à 1000 ETH
        # log10(1000 + 1) / 3 ≈ 1.0
        volume_score = min(math.log10(total_volume + 1) / 3, 1.0)
        
        # Fréquence: plafonnée à 10 transactions
        freq_score = min(tx_count / 10, 1.0)
        
        activity = 100 * (0.6 * volume_score + 0.3 * freq_score + 0.1 * bidirectional_ratio)
        return activity
    
    def _calc_proximity(self, source: str, target: str) -> float:
        """
        Score de proximité basé sur la distance dans le graphe.
        
        Formule: max(0, 100 - (distance - 1) * 35)
        - Distance 1 (voisin direct): 100
        - Distance 2: 65
        - Distance 3: 30
        - Distance >= 4: 0
        """
        if source == target:
            return 100.0
        
        try:
            # Utilise le graphe non orienté pour la distance
            undirected = self.graph.to_undirected()
            distance = nx.shortest_path_length(undirected, source, target)
            
            # Pénalité de 35 points par saut au-delà du premier
            score = max(0, 100 - (distance - 1) * 35)
            return float(score)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return 0.0
    
    def _calc_recency(self, u: str, v: str) -> float:
        """
        Score de récence basé sur la dernière transaction.
        
        Formule: 100 * exp(-days / 30)
        Demi-vie de 30 jours.
        """
        edges = self._get_all_edges(u, v)
        if not edges:
            return 0.0
        
        # Extraction des timestamps
        timestamps = []
        for e in edges:
            ts = e.get('time')
            if ts and ts != 'unknown':
                timestamps.append(ts)
        
        if not timestamps:
            # Pas d'info temporelle = neutre
            return 50.0
        
        # Dernière transaction
        try:
            last_tx = max(timestamps)
            days_ago = self._days_since(last_tx)
            recency = 100 * math.exp(-days_ago / 30)
            return recency
        except (ValueError, TypeError):
            return 50.0
    
    def _days_since(self, timestamp) -> float:
        """Calcule le nombre de jours depuis un timestamp."""
        try:
            if isinstance(timestamp, str):
                # Essayer de parser ISO format
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            elif isinstance(timestamp, datetime):
                dt = timestamp
            else:
                return 365.0  # Valeur par défaut: vieux
            
            now = datetime.now().astimezone() if dt.tzinfo else datetime.now()
            delta = now - dt
            return max(0, delta.total_seconds() / 86400)
        except Exception:
            return 365.0
    
    def _aggregate(self, activity: float, proximity: float, recency: float) -> float:
        """
        Agrège les 3 dimensions en un score final.
        
        Poids:
        - Activité: 50%
        - Proximité: 30%
        - Récence: 20%
        
        Règle: Si proximité = 0 (pas de chemin), le score total est 0.
        """
        if proximity == 0:
            return 0.0
        
        total = 0.5 * activity + 0.3 * proximity + 0.2 * recency
        
        # Boost pour les relations directes récentes actives
        if proximity == 100 and recency > 50 and activity > 50:
            total = min(total * 1.15, 100)
        
        return total
    
    def _get_metrics(self, u: str, v: str) -> Dict[str, Any]:
        """Extrait les métriques brutes pour debug."""
        edges = self._get_all_edges(u, v)
        
        return {
            'tx_count': len(edges),
            'total_volume': sum(e.get('weight', 0) for e in edges),
            'has_incoming': any(e['from'] == v for e in edges),
            'has_outgoing': any(e['from'] == u for e in edges),
            'last_tx': max((e.get('time', '') for e in edges), default=None),
        }
    
    def get_interpretation(self, score: NodeScore) -> str:
        """Retourne une interprétation textuelle du score."""
        if score.total >= 80:
            return "Relation forte"
        elif score.total >= 50:
            return "Relation modérée"
        elif score.total >= 20:
            return "Relation faible"
        elif score.total > 0:
            return "Trace"
        else:
            return "Aucun lien"
