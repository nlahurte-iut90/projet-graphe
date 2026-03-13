"""Service de récupération des prix crypto via CoinGecko API."""

import requests
import time
from typing import Optional
from datetime import datetime, timedelta


class PriceService:
    """Service pour récupérer les prix des cryptomonnaies via CoinGecko."""

    COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
    CACHE_DURATION_MINUTES = 5  # Rafraîchir le prix toutes les 5 minutes

    def __init__(self):
        self._eth_price_eur: Optional[float] = None
        self._last_update: Optional[datetime] = None
        self._session = requests.Session()

    def get_eth_price_eur(self) -> Optional[float]:
        """
        Récupère le prix actuel de l'ETH en EUR.

        Returns:
            Prix de l'ETH en EUR ou None si erreur
        """
        # Vérifier si le prix en cache est encore valide
        if self._is_cache_valid():
            return self._eth_price_eur

        try:
            response = self._session.get(
                f"{self.COINGECKO_API_URL}/simple/price",
                params={
                    "ids": "ethereum",
                    "vs_currencies": "eur",
                    "include_24hr_change": "true"
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            self._eth_price_eur = data["ethereum"]["eur"]
            self._last_update = datetime.now()

            return self._eth_price_eur

        except requests.RequestException as e:
            print(f"[PriceService] Erreur lors de la récupération du prix: {e}")
            # Retourner le dernier prix connu s'il existe
            return self._eth_price_eur

        except (KeyError, ValueError) as e:
            print(f"[PriceService] Erreur de parsing: {e}")
            return self._eth_price_eur

    def _is_cache_valid(self) -> bool:
        """Vérifie si le prix en cache est encore valide."""
        if self._eth_price_eur is None or self._last_update is None:
            return False

        age = datetime.now() - self._last_update
        return age < timedelta(minutes=self.CACHE_DURATION_MINUTES)

    def eth_to_eur(self, eth_amount: float) -> Optional[float]:
        """
        Convertit un montant en ETH vers EUR.

        Args:
            eth_amount: Montant en ETH

        Returns:
            Montant en EUR ou None si prix non disponible
        """
        price = self.get_eth_price_eur()
        if price is None:
            return None
        return eth_amount * price

    def format_eth_eur(self, eth_amount: float) -> str:
        """
        Formate un montant ETH avec sa conversion EUR.

        Args:
            eth_amount: Montant en ETH

        Returns:
            Chaîne formatée (ex: "1.50 ETH (~4,523.45 €)")
        """
        eur_amount = self.eth_to_eur(eth_amount)
        if eur_amount is None:
            return f"{eth_amount:.4f} ETH"

        # Formatter avec des espaces pour les milliers
        if eur_amount >= 1000:
            eur_str = f"{eur_amount:,.2f} €".replace(",", " ")
        else:
            eur_str = f"{eur_amount:.2f} €"

        return f"{eth_amount:.4f} ETH (~{eur_str})"

    def get_price_info(self) -> dict:
        """
        Retourne les informations complètes sur le prix.

        Returns:
            Dict avec prix, date de mise à jour, etc.
        """
        price = self.get_eth_price_eur()
        return {
            "eth_price_eur": price,
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "cache_valid": self._is_cache_valid()
        }


# Singleton pour réutiliser le même service
_price_service_instance: Optional[PriceService] = None


def get_price_service() -> PriceService:
    """Retourne l'instance singleton du PriceService."""
    global _price_service_instance
    if _price_service_instance is None:
        _price_service_instance = PriceService()
    return _price_service_instance
