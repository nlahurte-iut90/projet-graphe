from dune_client.client import DuneClient
from src.config import config
from src.infrastructure.cache import CacheManager
import pandas as pd
from typing import Optional

class DuneAdapter:
    def __init__(self):
        self.client = DuneClient(config.DUNE_API_KEY) if config.DUNE_API_KEY else None
        self.cache = CacheManager()


    # recupère les données bruts de transaction entre deux adresses
    def get_transactions(self, address1: str, address2: str,limit:int = 5) -> pd.DataFrame:
        if not self.client:
            raise ValueError("Dune Client not initialized. Check API Key.")
            
        print(f"Fetching transactions for {address1} and {address2}...")

        # Requête SQL pour trouver les transactions entre les deux adresses
        # Note: 'ethereum.transactions' est une table standard sur Dune
        query_sql = f"""
            WITH address1_tx AS (
                SELECT "from", "to", (value/1e18) AS value_eth, hash, block_time
                FROM ethereum.transactions 
                WHERE ("from" = {address1} OR "to" = {address1})
                ORDER BY block_time DESC
                LIMIT {limit}
            ),
            address2_tx AS (
                SELECT "from", "to", (value/1e18) AS value_eth, hash, block_time
                FROM ethereum.transactions 
                WHERE ("from" = {address2} OR "to" = {address2})
                ORDER BY block_time DESC
                LIMIT {limit}
            )
            SELECT * FROM address1_tx
            UNION ALL
            SELECT * FROM address2_tx
        """
        
        # Check cache first
        cached_df = self.cache.get(query_sql)
        if cached_df is not None:
             return cached_df
        
        try:
             # Utilisation de run_sql (ou execute selon la version de la lib)
            results = self.client.run_sql(query_sql = query_sql)
            
            # Transformation en DataFrame Pandas
            if results and results.result and results.result.rows:
                 df = pd.DataFrame(results.result.rows)
                 df = df.drop_duplicates(subset=['hash'])
                 # Save to cache
                 self.cache.save(query_sql, df)
                 return df
            return pd.DataFrame()
        except Exception as e:
            print(f"Erreur Dune: {e}")
            # Retourner un DF vide en cas d'erreur pour ne pas crasher
            return pd.DataFrame()
