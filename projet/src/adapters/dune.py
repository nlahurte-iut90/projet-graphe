from dune_client.client import DuneClient
from src.config import config
from src.infrastructure.cache import CacheManager
import pandas as pd
from typing import Optional
import time
import random

class DuneAdapter:
    def __init__(self):
        self.client = DuneClient(config.DUNE_API_KEY) if config.DUNE_API_KEY else None
        self.cache = CacheManager()

    def _run_sql_with_retry(self, query_sql: str, max_retries: int = 3, base_delay: float = 2.0) -> Optional[pd.DataFrame]:
        """
        Execute SQL query with exponential backoff retry logic.

        Args:
            query_sql: The SQL query to execute
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds (will be multiplied by 2^retry_count + jitter)

        Returns:
            DataFrame with results, or None if all retries failed
        """
        for attempt in range(max_retries):
            try:
                results = self.client.run_sql(query_sql=query_sql)
                if results and results.result and results.result.rows:
                    df = pd.DataFrame(results.result.rows)
                    df = df.drop_duplicates(subset=['hash'])
                    return df
                return pd.DataFrame()
            except Exception as e:
                error_str = str(e)
                is_rate_limit = '429' in error_str or 'too many' in error_str.lower()

                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)

                    if is_rate_limit:
                        print(f"    Rate limited (429), waiting {delay:.1f}s before retry {attempt + 1}/{max_retries}...")
                    else:
                        print(f"    Error: {error_str[:50]}..., retrying in {delay:.1f}s...")

                    time.sleep(delay)
                else:
                    # Last attempt failed
                    if is_rate_limit:
                        print(f"    Rate limited after {max_retries} attempts, giving up")
                    else:
                        print(f"    Error after {max_retries} attempts: {error_str[:80]}")
                    return None
        return None


    # recupère les données bruts de transaction entre deux adresses
    def get_transactions(self, address1: str, address2: str,limit:int = 5) -> Optional[pd.DataFrame]:
        if not self.client:
            raise ValueError("Dune Client not initialized. Check API Key.")
            
        print(f"Fetching transactions for {address1} and {address2}...")

        # Requête SQL pour trouver les transactions entre les deux adresses
        # Note: 'ethereum.transactions' est une table standard sur Dune
        query_sql = f"""
            WITH address1_tx AS (
                SELECT "from", "to", (value/1e18) AS value_eth, value AS value_wei, hash, block_time
                FROM ethereum.transactions
                WHERE ("from" = from_hex('{address1}') OR "to" = from_hex('{address1}'))
                ORDER BY block_time DESC
                LIMIT {limit}
            ),
            address2_tx AS (
                SELECT "from", "to", (value/1e18) AS value_eth, value AS value_wei, hash, block_time
                FROM ethereum.transactions
                WHERE ("from" = from_hex('{address2}') OR "to" = from_hex('{address2}'))
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

        # Execute with retry logic
        df = self._run_sql_with_retry(query_sql, max_retries=3, base_delay=2.0)

        if df is not None:
            # Save to cache
            self.cache.save(query_sql, df)
            return df
        else:
            # All retries failed - return None to indicate failure
            return None

    def get_transactions_for_address(self, address: str, limit: int = 5) -> Optional[pd.DataFrame]:
        """Récupère les transactions pour une adresse spécifique (entrantes et sortantes)."""
        if not self.client:
            raise ValueError("Dune Client not initialized. Check API Key.")

        print(f"Fetching transactions for {address}...")

        query_sql = f"""
            SELECT "from", "to", (value/1e18) AS value_eth, value AS value_wei, hash, block_time
            FROM ethereum.transactions
            WHERE ("from" = {address} OR "to" = {address} )
            ORDER BY block_time DESC
            LIMIT {limit}
        """

        cached_df = self.cache.get(query_sql)
        if cached_df is not None:
            return cached_df

        # Execute with retry logic
        df = self._run_sql_with_retry(query_sql, max_retries=3, base_delay=2.0)

        if df is not None:
            # Save to cache
            self.cache.save(query_sql, df)
            return df
        else:
            # All retries failed - return None to indicate failure
            return None
