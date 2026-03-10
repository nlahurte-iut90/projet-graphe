"""Scorer simplifié pour évaluer la relation entre une main address et un nœud."""

from typing import Dict, List, Optional, Any
from datetime import datetime
import math
import networkx as nx

from src.services.scoring.base import SimilarityStrategy, NodeScore
from src.services.scoring.correlation_scorer import calculate_correlation_from_edges


class SimpleNodeScorer(SimilarityStrategy):
    """
    Scorer léger et interprétable pour la relation main_address ↔ nœud.

    Basé sur 3 dimensions:
    - Activité (50%): volume, fréquence, bidirectionnalité (nouveau scoring v2.0.0)
    - Proximité (30%): distance dans le graphe
    - Récence (20%): fraîcheur de la dernière transaction

    Le scoring d'activité utilise l'algorithme composite à 4 composants:
    - Volume (40%): Équilibre directionnel
    - Fréquence (20%): Indice de Jaccard
    - Récence (30%): Décroissance exponentielle
    - Bidirectionnalité (10%): Détection de handshakes
    """

    def __init__(self, graph: nx.MultiDiGraph):
        super().__init__(graph)
        self._edge_cache: Dict[tuple, List[Dict]] = {}

    def get_name(self) -> str:
        """Retourne le nom de la stratégie."""
        return "SimpleNodeScorer"

    def get_description(self) -> str:
        """Retourne une description de la stratégie."""
        return ("Scorer basé sur 3 dimensions: Activité (50%), "
                "Proximité (30%), Récence (20%) - avec scoring composite v2.0.0")
    
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
        Score d'activité basé sur le nouveau scoring composite v2.0.0.

        Utilise calculate_correlation_from_edges avec:
        - Volume (40%): Équilibre directionnel des flux
        - Fréquence (20%): Indice de Jaccard avec intensité logarithmique
        - Récence (30%): Décroissance exponentielle par bloc
        - Bidirectionnalité (10%): Détection de handshakes synchronisés

        Le résultat est converti de [0,1] à [0,100] pour compatibilité.
        """
        edges = self._get_all_edges(u, v)
        if not edges:
            return 0.0

        # Utiliser le nouveau correlation scorer
        result = calculate_correlation_from_edges(u, v, edges)

        # Convertir [0,1] en [0,100] pour compatibilité avec l'ancien système
        return result.final_score * 100
    
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

        # Récupérer les métriques détaillées du nouveau scorer
        result = calculate_correlation_from_edges(u, v, edges)

        return {
            'tx_count': len(edges),
            'total_volume': sum(e.get('weight', 0) for e in edges),
            'has_incoming': any(e['from'] == v for e in edges),
            'has_outgoing': any(e['from'] == u for e in edges),
            'last_tx': max((e.get('time', '') for e in edges), default=None),
            # Nouvelles métriques v2.0.0
            'correlation_details': result.components,
            'metadata': result.metadata,
            'is_correlated': result.is_correlated,
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
