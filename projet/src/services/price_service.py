"""Service pour récupérer le prix de l'ETH via CoinGecko API."""
import requests
from typing import Optional
from datetime import datetime, timedelta


class PriceService:
    """Récupère le prix live de l'ETH en EUR via CoinGecko."""

    COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"

    def __init__(self):
        self._eth_price_eur: Optional[float] = None
        self._last_fetch: Optional[datetime] = None
        self._cache_duration = timedelta(minutes=5)  # Cache de 5 minutes

    def get_eth_price_eur(self) -> Optional[float]:
        """
        Récupère le prix actuel de l'ETH en EUR.
        Utilise le cache si disponible et récent.
        """
        # Vérifier si on a un cache valide
        if self._eth_price_eur is not None and self._last_fetch is not None:
            if datetime.now() - self._last_fetch < self._cache_duration:
                return self._eth_price_eur

        # Sinon, faire la requête API
        try:
            response = requests.get(
                self.COINGECKO_API_URL,
                params={
                    "ids": "ethereum",
                    "vs_currencies": "eur",
                    "include_24hr_change": "false"
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            self._eth_price_eur = data["ethereum"]["eur"]
            self._last_fetch = datetime.now()
            return self._eth_price_eur

        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[PriceService] Erreur lors de la récupération du prix: {e}")
            # Retourner le dernier prix connu même si périmé
            return self._eth_price_eur

    def calculate_eur_value(self, eth_amount: float) -> Optional[float]:
        """Calcule la valeur en EUR d'un montant en ETH."""
        price = self.get_eth_price_eur()
        if price is None:
            return None
        return eth_amount * price

    def format_price(self) -> str:
        """Formate le prix actuel pour affichage."""
        price = self.get_eth_price_eur()
        if price is None:
            return "Prix ETH indisponible"
        return f"{price:,.2f} EUR"
