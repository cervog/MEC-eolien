"""Récupération des données brutes : ENTSO-E en priorité, sources de secours sinon."""

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from .fallback import fallback_for

ZONE = "FR"
ENTSOE = "ENTSO-E"


@dataclass
class MarketData:
    """Données brutes nécessaires au bulletin.

    Une donnée introuvable vaut None et son erreur est consignée dans `errors`,
    pour que le bulletin parte quand même avec les sections disponibles.
    `sources` indique d'où vient chaque donnée, `notes` les bascules en secours.
    """

    now: pd.Timestamp
    prices: Optional[pd.Series] = None  # €/MWh, J-1 à J+1
    generation: Optional[pd.DataFrame] = None  # MW par type de production, J-1
    installed: Optional[pd.Series] = None  # MW installés par type de production
    outages: Optional[pd.DataFrame] = None  # indisponibilités au format entsoe-py (doc A80)
    errors: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def attempt(self, name: str, fetch: Callable):
        try:
            value = fetch()
        except Exception as exc:  # une source en panne ne doit pas bloquer l'envoi
            self.errors[name] = f"{type(exc).__name__}: {exc}"
            return None
        if value is None or (hasattr(value, "empty") and value.empty and name != "Indisponibilités"):
            self.errors[name] = "réponse vide"
            return None
        return value


# Donnée -> (attribut de MarketData, requête ENTSO-E).
def _entsoe_queries(client, now: pd.Timestamp) -> dict:
    today = now.normalize()
    day = pd.Timedelta(days=1)
    year = pd.Timestamp(year=today.year, month=1, day=1, tz=today.tz)
    return {
        "Prix spot": ("prices", lambda: client.query_day_ahead_prices(ZONE, start=today - day, end=today + 2 * day)),
        "Production": ("generation", lambda: client.query_generation(ZONE, start=today - day, end=today, nett=True)),
        "Capacités installées": ("installed", lambda: client.query_installed_generation_capacity(
            ZONE, start=year, end=year + pd.DateOffset(years=1)).iloc[-1]),
        "Indisponibilités": ("outages", lambda: client.query_unavailability_of_generation_units(
            ZONE, start=now - day, end=now + 8 * day)),
    }


def fetch(token: Optional[str], now: pd.Timestamp) -> MarketData:
    data = MarketData(now=now)
    client = None
    if token:
        from entsoe import EntsoePandasClient

        client = EntsoePandasClient(api_key=token)
    else:
        data.notes.append("Pas de clé ENTSO-E : sources de secours utilisées.")

    for name, (attr, query) in _entsoe_queries(client, now).items():
        value = data.attempt(name, query) if client is not None else None
        if value is not None:
            data.sources[name] = ENTSOE
        else:
            fb_name, fb_fetch = fallback_for(name)
            primary_error = data.errors.pop(name, None)
            value = data.attempt(name, lambda: fb_fetch(now))
            if value is not None:
                data.sources[name] = fb_name
                if primary_error:
                    data.notes.append(f"{name} : ENTSO-E en échec ({primary_error}), repli sur {fb_name}.")
            elif primary_error:
                data.errors[name] = f"ENTSO-E : {primary_error} · {fb_name} : {data.errors[name]}"
        setattr(data, attr, value)
    return data
