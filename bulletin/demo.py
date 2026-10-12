"""Données synthétiques au format entsoe-py, pour prévisualiser le bulletin et pour les tests."""

import numpy as np
import pandas as pd

from . import TZ
from .sources import MarketData


def demo_prices(start: pd.Timestamp, days: int = 3, seed: int = 0) -> pd.Series:
    """Prix au quart d'heure avec creux solaire (prix négatifs en milieu de journée) et pointe du soir."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days * 96, freq="15min", tz=TZ)
    h = idx.hour + idx.minute / 60
    profile = 75 + 35 * np.exp(-((h - 19.5) ** 2) / 4) + 15 * np.exp(-((h - 8.5) ** 2) / 3) - 85 * np.exp(-((h - 13.5) ** 2) / 5)
    level = np.repeat(rng.normal(0, 8, days), 96)
    return pd.Series(profile + level + rng.normal(0, 3, len(idx)), index=idx).round(2)


def demo_generation(start: pd.Timestamp) -> pd.DataFrame:
    idx = pd.date_range(start, periods=96, freq="15min", tz=TZ)
    h = idx.hour + idx.minute / 60
    sun = np.clip(np.sin((h - 7) / 12 * np.pi), 0, None)
    return pd.DataFrame(
        {
            "Nuclear": 44000 + 1500 * np.cos(h / 24 * 2 * np.pi),
            "Hydro Run-of-river and pondage": 4200.0,
            "Hydro Water Reservoir": 2500 + 2000 * np.exp(-((h - 19) ** 2) / 3),
            "Hydro Pumped Storage": 600 * np.exp(-((h - 20) ** 2) / 2),
            "Wind Onshore": 6500 + 1500 * np.sin(h / 24 * np.pi),
            "Wind Offshore": 900.0,
            "Solar": 11000 * sun,
            "Fossil Gas": 2500 + 1500 * np.exp(-((h - 19) ** 2) / 4),
            "Fossil Hard coal": 0.0,
            "Fossil Oil": 80.0,
            "Biomass": 650.0,
            "Waste": 420.0,
        },
        index=idx,
    )


def demo_installed() -> pd.Series:
    return pd.Series(
        {
            "Nuclear": 62990.0,
            "Hydro Run-of-river and pondage": 11450.0,
            "Hydro Water Reservoir": 8200.0,
            "Hydro Pumped Storage": 5000.0,
            "Wind Onshore": 23000.0,
            "Wind Offshore": 1500.0,
            "Solar": 25000.0,
            "Fossil Gas": 12500.0,
            "Fossil Hard coal": 1800.0,
            "Fossil Oil": 2500.0,
            "Biomass": 2200.0,
            "Waste": 900.0,
        }
    )


def _outage(mrid, revision, unit, plant, psr, nominal, avail, start, end, kind="A53", status="Active", created=None):
    return {
        "created_doc_time": created,
        "docstatus": status,
        "mrid": mrid,
        "revision": revision,
        "businesstype": {"A53": "Planned maintenance", "A54": "Unplanned outage"}[kind],
        "biddingzone_domain": "FR",
        "qty_uom": "MAW",
        "curvetype": "A03",
        "production_resource_id": f"17W-{plant[:6].upper()}",
        "production_resource_name": plant,
        "production_resource_psr_name": unit,
        "production_resource_location": "",
        "plant_type": psr,
        "nominal_power": str(nominal),
        "start": start,
        "end": end,
        "resolution": "PT1M",
        "pstn": "1",
        "avail_qty": str(avail),
    }


def demo_outages(now: pd.Timestamp) -> pd.DataFrame:
    d = pd.Timedelta(days=1)
    h = pd.Timedelta(hours=1)
    rows = [
        _outage("m1", 1, "FLAMANVILLE 1", "FLAMANVILLE", "Nuclear", 1330, 0, now - 40 * d, now + 3 * d, created=now - 41 * d),
        _outage("m2", 2, "CATTENOM 3", "CATTENOM", "Nuclear", 1300, 0, now - 12 * d, now + 25 * d, created=now - 13 * d),
        _outage("m3", 1, "PALUEL 2", "PALUEL", "Nuclear", 1330, 0, now - 5 * h, now + 2 * d, "A54", created=now - 5 * h),
        _outage("m4", 1, "GRAVELINES 4", "GRAVELINES", "Nuclear", 910, 600, now - 3 * d, now + 1 * d, "A54", created=now - 3 * d),
        _outage("m5", 3, "TRICASTIN 2", "TRICASTIN", "Nuclear", 915, 0, now - 60 * d, now + 15 * d, created=now - 61 * d),
        _outage("m6", 1, "BUGEY 5", "BUGEY", "Nuclear", 880, 0, now - 20 * d, now + 6 * d, created=now - 21 * d),
        _outage("m7", 1, "CHOOZ B1", "CHOOZ", "Nuclear", 1500, 1000, now - 2 * h, now + 10 * h, "A54", created=now - 3 * h),
        _outage("m8", 1, "MONTEZIC 1", "MONTEZIC", "Hydro Pumped Storage", 230, 0, now - 4 * d, now + 9 * d, created=now - 5 * d),
        _outage("m9", 1, "BLENOD 5", "BLENOD", "Fossil Gas", 430, 0, now - 10 * h, now + 30 * h, "A54", created=now - 10 * h),
        _outage("m10", 1, "CORDEMAIS 4", "CORDEMAIS", "Fossil Hard coal", 580, 0, now - 90 * d, now + 40 * d, created=now - 91 * d),
        # Déclaration remplacée par une révision ultérieure annulée : ne doit pas apparaître.
        _outage("m11", 1, "GOLFECH 1", "GOLFECH", "Nuclear", 1310, 0, now - d, now + 5 * d, created=now - 2 * d),
        _outage("m11", 2, "GOLFECH 1", "GOLFECH", "Nuclear", 1310, 0, now - d, now + 5 * d, status="Cancelled", created=now - d),
    ]
    df = pd.DataFrame(rows)
    df["created_doc_time"] = pd.to_datetime(df["created_doc_time"]).dt.tz_convert("UTC")
    return df.set_index("created_doc_time").sort_index()


def demo_data(now: pd.Timestamp) -> MarketData:
    today = now.normalize()
    return MarketData(
        now=now,
        prices=demo_prices(today - pd.Timedelta(days=1)),
        generation=demo_generation(today - pd.Timedelta(days=1)),
        installed=demo_installed(),
        outages=demo_outages(now),
        sources={name: "démo" for name in ("Prix spot", "Production", "Capacités installées", "Indisponibilités")},
    )
