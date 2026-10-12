"""Récupération des données brutes sur la plateforme de transparence ENTSO-E."""

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

ZONE = "FR"


@dataclass
class MarketData:
    """Données brutes nécessaires au bulletin.

    Une source en échec vaut None et son erreur est consignée dans `errors`,
    pour que le bulletin parte quand même avec les sections disponibles.
    """

    now: pd.Timestamp
    prices: Optional[pd.Series] = None  # €/MWh, J-1 à J+1
    generation: Optional[pd.DataFrame] = None  # MW par type de production, J-1
    installed: Optional[pd.Series] = None  # MW installés par type de production
    outages: Optional[pd.DataFrame] = None  # indisponibilités brutes (doc A80)
    errors: dict[str, str] = field(default_factory=dict)

    def attempt(self, name: str, fetch: Callable):
        try:
            return fetch()
        except Exception as exc:  # une source en panne ne doit pas bloquer l'envoi
            self.errors[name] = f"{type(exc).__name__}: {exc}"
            return None


def fetch_entsoe(token: str, now: pd.Timestamp) -> MarketData:
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=token)
    today = now.normalize()
    day = pd.Timedelta(days=1)
    data = MarketData(now=now)

    data.prices = data.attempt(
        "Prix spot", lambda: client.query_day_ahead_prices(ZONE, start=today - day, end=today + 2 * day)
    )
    data.generation = data.attempt(
        "Production", lambda: client.query_generation(ZONE, start=today - day, end=today, nett=True)
    )
    year = pd.Timestamp(year=today.year, month=1, day=1, tz=today.tz)
    installed = data.attempt(
        "Capacités installées",
        lambda: client.query_installed_generation_capacity(ZONE, start=year, end=year + pd.DateOffset(years=1)),
    )
    if installed is not None and not installed.empty:
        data.installed = installed.iloc[-1]
    data.outages = data.attempt(
        "Indisponibilités",
        lambda: client.query_unavailability_of_generation_units(ZONE, start=now - day, end=now + 8 * day),
    )
    return data
