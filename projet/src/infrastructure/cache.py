import hashlib
import os
import pickle
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from pathlib import Path
import networkx as nx


class GraphMetricsCache:
    """Cache spécialisé pour métriques de graphe coûteuses."""

    def __init__(self, base_cache_dir: Path = None):
        if base_cache_dir is None:
            src_dir = Path(__file__).parent.parent  # src/
            project_dir = src_dir.parent  # projet/
            base_cache_dir = project_dir / "cache" / "graph_metrics"

        self.cache_dir = Path(base_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache mémoire pour accès rapide
        self._memory_cache: Dict[str, Any] = {}

    def _get_graph_hash(self, graph: nx.Graph) -> str:
        """Génère un hash unique pour le graphe."""
        # Utiliser le nombre de nœuds/arêtes et les IDs
        nodes_str = ','.join(sorted(str(n) for n in graph.nodes()))
        edges_str = ','.join(sorted(f"{u}-{v}" for u, v in graph.edges()))
        content = f"{nodes_str}|{edges_str}|{graph.number_of_nodes()}|{graph.number_of_edges()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cache_path(self, key: str) -> Path:
        """Retourne le chemin du fichier de cache."""
        return self.cache_dir / f"{key}.pkl"

    def get_shortest_paths(self, graph: nx.Graph) -> Optional[Dict]:
        """Récupère les plus courts chemins précalculés."""
        graph_hash = self._get_graph_hash(graph)
        key = f"sp_{graph_hash}"

        # Vérifier le cache mémoire d'abord
        if key in self._memory_cache:
            return self._memory_cache[key]

        # Vérifier le cache disque
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    data = pickle.load(f)
                    self._memory_cache[key] = data
                    return data
            except Exception:
                return None

        return None

    def cache_shortest_paths(self, graph: nx.Graph, paths: Dict):
        """Cache les plus courts chemins."""
        graph_hash = self._get_graph_hash(graph)
        key = f"sp_{graph_hash}"

        self._memory_cache[key] = paths

        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(paths, f)
        except Exception as e:
            print(f"[GraphMetricsCache] Error caching shortest paths: {e}")

    def get_laplacian_pinv(self, graph: nx.Graph) -> Optional[np.ndarray]:
        """Récupère la pseudoinverse du Laplacien."""
        graph_hash = self._get_graph_hash(graph)
        key = f"laplacian_{graph_hash}"

        # Vérifier le cache mémoire
        if key in self._memory_cache:
            return self._memory_cache[key]

        # Stockage disque pour matrices volumineuses (format .npy)
        cache_path = self.cache_dir / f"{key}.npy"
        if cache_path.exists():
            try:
                data = np.load(cache_path)
                self._memory_cache[key] = data
                return data
            except Exception:
                return None

        return None

    def cache_laplacian_pinv(self, graph: nx.Graph, L_pinv: np.ndarray):
        """Cache la pseudoinverse du Laplacien."""
        graph_hash = self._get_graph_hash(graph)
        key = f"laplacian_{graph_hash}"

        self._memory_cache[key] = L_pinv

        cache_path = self.cache_dir / f"{key}.npy"
        try:
            np.save(cache_path, L_pinv)
        except Exception as e:
            print(f"[GraphMetricsCache] Error caching laplacian: {e}")

    def get_ppr_vectors(self, graph: nx.Graph, alpha: float) -> Optional[Dict[str, Dict]]:
        """Récupère les vecteurs PPR précalculés."""
        graph_hash = self._get_graph_hash(graph)
        key = f"ppr_{graph_hash}_{alpha:.4f}"

        if key in self._memory_cache:
            return self._memory_cache[key]

        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    data = pickle.load(f)
                    self._memory_cache[key] = data
                    return data
            except Exception:
                return None

        return None

    def cache_ppr_vectors(self, graph: nx.Graph, alpha: float, vectors: Dict[str, Dict]):
        """Cache les vecteurs PPR."""
        graph_hash = self._get_graph_hash(graph)
        key = f"ppr_{graph_hash}_{alpha:.4f}"

        self._memory_cache[key] = vectors

        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(vectors, f)
        except Exception as e:
            print(f"[GraphMetricsCache] Error caching PPR vectors: {e}")

    def clear_memory_cache(self):
        """Vide le cache mémoire."""
        self._memory_cache.clear()

    def clear_disk_cache(self):
        """Vide le cache disque."""
        for file in self.cache_dir.glob("*"):
            try:
                file.unlink()
            except Exception:
                pass


class CacheManager:
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            # Chemin absolu basé sur l'emplacement du fichier source
            # Remonter de src/infrastructure/ à la racine du projet
            src_dir = Path(__file__).parent.parent  # src/
            project_dir = src_dir.parent  # projet/
            cache_dir = project_dir / "cache"

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        print(f"[Cache] Using cache directory: {self.cache_dir}")

    def _get_hash(self, sql_query: str) -> str:
        # Normalize query to avoid misses due to whitespace
        normalized_query = " ".join(sql_query.split())
        return hashlib.sha256(normalized_query.encode('utf-8')).hexdigest()

    def _get_file_path(self, query_hash: str) -> str:
        return os.path.join(self.cache_dir, f"{query_hash}.pkl")

    def get(self, sql_query: str) -> Optional[pd.DataFrame]:
        query_hash = self._get_hash(sql_query)
        file_path = self._get_file_path(query_hash)
        
        if os.path.exists(file_path):
            try:
                print(f"Loading data from cache: {file_path}")
                return pd.read_pickle(file_path)
            except Exception as e:
                print(f"Error loading cache: {e}")
        return None

    def save(self, sql_query: str, df: pd.DataFrame):
        if df.empty:
            return
            
        query_hash = self._get_hash(sql_query)
        file_path = self._get_file_path(query_hash)
        
        try:
            df.to_pickle(file_path)
            print(f"Saved data to cache: {file_path}")
        except Exception as e:
            print(f"Error saving to cache: {e}")
