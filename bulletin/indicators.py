"""Calcul des indicateurs du bulletin à partir des données brutes ENTSO-E.

Fonctions pures : elles ne font aucun appel réseau et sont testées sur des
données synthétiques.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

# Types de production ENTSO-E regroupés en filières françaises.
FILIERES = {
    "Nuclear": "Nucléaire",
    "Hydro Run-of-river and pondage": "Hydraulique",
    "Hydro Water Reservoir": "Hydraulique",
    "Hydro Pumped Storage": "Hydraulique",
    "Wind Onshore": "Éolien",
    "Wind Offshore": "Éolien",
    "Solar": "Solaire",
    "Fossil Gas": "Gaz",
    "Fossil Hard coal": "Charbon",
    "Fossil Brown coal/Lignite": "Charbon",
    "Fossil Oil": "Fioul",
    "Biomass": "Bioénergies",
    "Waste": "Bioénergies",
}
ORDRE_FILIERES = ["Nucléaire", "Hydraulique", "Éolien", "Solaire", "Gaz", "Charbon", "Fioul", "Bioénergies", "Autres"]

TYPES_INDISPO = {"Planned maintenance": "Programmée", "Unplanned outage": "Fortuite"}
STATUTS_ANNULES = {"Cancelled", "Withdrawn"}

HEURES_POINTE = range(8, 20)  # produit « peak » : 8h-20h


def filiere(psr_type: str) -> str:
    return FILIERES.get(psr_type, "Autres")


def _step_hours(index: pd.DatetimeIndex) -> float:
    """Pas de temps en heures (15 min depuis le passage du day-ahead au quart d'heure)."""
    if len(index) < 2:
        return 1.0
    return pd.Series(index).diff().median() / pd.Timedelta(hours=1)


def _flatten_by_type(obj):
    """Ramène les colonnes (type, Actual Aggregated/Consumption) à un niveau par type."""
    if isinstance(obj, pd.DataFrame) and isinstance(obj.columns, pd.MultiIndex):
        return obj.xs("Actual Aggregated", axis=1, level=1, drop_level=True)
    if isinstance(obj, pd.Series) and isinstance(obj.index, pd.MultiIndex):
        return obj.xs("Actual Aggregated", level=1, drop_level=True)
    return obj


# --- Prix spot -----------------------------------------------------------------


@dataclass
class PriceStats:
    day: pd.Timestamp
    base: float
    peak: Optional[float]
    min: float
    min_at: pd.Timestamp
    max: float
    max_at: pd.Timestamp
    negative_hours: float
    hourly: pd.Series  # moyenne horaire, pour le profil du jour


def price_stats(prices: Optional[pd.Series], day: pd.Timestamp) -> Optional[PriceStats]:
    """Statistiques day-ahead d'une journée (None si non publiée)."""
    if prices is None or prices.empty:
        return None
    day = day.normalize()
    sl = prices[(prices.index >= day) & (prices.index < day + pd.Timedelta(days=1))].dropna()
    if sl.empty:
        return None
    step = _step_hours(sl.index)
    peak = sl[sl.index.hour.isin(HEURES_POINTE)]
    return PriceStats(
        day=day,
        base=float(sl.mean()),
        peak=float(peak.mean()) if not peak.empty else None,
        min=float(sl.min()),
        min_at=sl.idxmin(),
        max=float(sl.max()),
        max_at=sl.idxmax(),
        negative_hours=float((sl < 0).sum() * step),
        hourly=sl.groupby(sl.index.hour).mean(),
    )


# --- Mix de production -------------------------------------------------------


def generation_mix(generation: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Énergie produite par filière (GWh) et part du total."""
    if generation is None or generation.empty:
        return None
    gen = _flatten_by_type(generation).clip(lower=0)
    energy_gwh = gen.sum() * _step_hours(gen.index) / 1000
    mix = energy_gwh.groupby(lambda t: filiere(t)).sum()
    mix = mix.reindex([f for f in ORDRE_FILIERES if f in mix.index])
    mix = mix[mix > 0]
    return pd.DataFrame({"energie_gwh": mix, "part": mix / mix.sum()})


# --- Indisponibilités ------------------------------------------------------------


def latest_outages(raw: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Dernière révision de chaque déclaration, sans les déclarations annulées.

    Renvoie une ligne par période déclarée avec la puissance indisponible.
    """
    if raw is None:
        return None
    df = raw.reset_index()
    if df.empty:
        return df.assign(indispo_mw=pd.Series(dtype=float))
    # L'annulation est portée par la dernière révision : filtrer après avoir gardé celle-ci.
    df = df[df["revision"] == df.groupby("mrid")["revision"].transform("max")]
    df = df[~df["docstatus"].isin(STATUTS_ANNULES)].copy()
    nominal = pd.to_numeric(df["nominal_power"], errors="coerce")
    avail = pd.to_numeric(df["avail_qty"], errors="coerce")
    df["indispo_mw"] = (nominal - avail).clip(lower=0)
    df["filiere"] = df["plant_type"].map(filiere)
    df["type"] = df["businesstype"].map(TYPES_INDISPO).fillna(df["businesstype"])
    df["fin_prevue"] = df.groupby("mrid")["end"].transform("max")
    return df


def current_outages(outages: Optional[pd.DataFrame], now: pd.Timestamp) -> Optional[pd.DataFrame]:
    """Unités indisponibles à l'instant `now`, une ligne par unité, triées par MW."""
    if outages is None:
        return None
    cur = outages[(outages["start"] <= now) & (outages["end"] > now) & (outages["indispo_mw"] > 0)]
    # Plusieurs déclarations peuvent se recouvrir sur une même unité : on garde la plus pénalisante.
    cur = cur.sort_values("indispo_mw", ascending=False)
    cur = cur.drop_duplicates(subset=["production_resource_id", "production_resource_psr_name"])
    cols = [
        "production_resource_psr_name", "production_resource_name", "filiere", "type",
        "nominal_power", "indispo_mw", "fin_prevue", "created_doc_time",
    ]
    return cur[cols].reset_index(drop=True)


def availability_by_filiere(current: Optional[pd.DataFrame], installed: Optional[pd.Series]) -> Optional[pd.DataFrame]:
    """Puissance indisponible et disponible par filière pilotable.

    Seules les unités de plus de 100 MW sont soumises à déclaration : le taux
    de disponibilité est donc une approximation pour les petites filières.
    """
    if current is None:
        return None
    indispo = current.groupby("filiere")["indispo_mw"].sum()
    table = pd.DataFrame({"indispo_mw": indispo})
    if installed is not None:
        inst = pd.to_numeric(_flatten_by_type(installed), errors="coerce")
        inst = inst.groupby(lambda t: filiere(t)).sum()
        table = table.join(pd.DataFrame({"installe_mw": inst}), how="outer")
    table["indispo_mw"] = table["indispo_mw"].fillna(0)
    if "installe_mw" in table:
        table = table[table.index.isin(["Nucléaire", "Hydraulique", "Gaz", "Charbon", "Fioul"]) | (table["indispo_mw"] > 0)]
        table["dispo_mw"] = table["installe_mw"] - table["indispo_mw"]
        table["taux_dispo"] = table["dispo_mw"] / table["installe_mw"]
    table = table.reindex([f for f in ORDRE_FILIERES if f in table.index])
    return table


def upcoming_returns(current: Optional[pd.DataFrame], now: pd.Timestamp, days: int = 7) -> Optional[pd.DataFrame]:
    """Unités dont le retour est annoncé dans les `days` prochains jours."""
    if current is None:
        return None
    horizon = now + pd.Timedelta(days=days)
    return current[current["fin_prevue"] <= horizon].sort_values("fin_prevue").reset_index(drop=True)


def new_forced_outages(current: Optional[pd.DataFrame], now: pd.Timestamp, hours: int = 24) -> Optional[pd.DataFrame]:
    """Indisponibilités fortuites en cours déclarées dans les dernières `hours` heures."""
    if current is None:
        return None
    created = pd.to_datetime(current["created_doc_time"], utc=True)
    recent = created >= (now - pd.Timedelta(hours=hours)).tz_convert("UTC")
    return current[(current["type"] == "Fortuite") & recent].reset_index(drop=True)
