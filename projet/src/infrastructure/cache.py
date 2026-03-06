import hashlib
import os
import pandas as pd
from typing import Optional
from pathlib import Path

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
