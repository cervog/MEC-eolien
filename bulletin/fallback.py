"""Sources de secours, sans clé d'API, utilisées quand ENTSO-E ne répond pas.

- Prix spot et mix de production : API Energy-Charts (Fraunhofer ISE).
- Indisponibilités : open data EDF (parc EDF SA uniquement, issu des
  publications REMIT d'EDF).
- Capacités installées : valeurs de référence du parc français.

Chaque fonction renvoie les données au même format qu'entsoe-py, pour que les
indicateurs n'aient pas à connaître la source.
"""

import io
import re
import unicodedata
from typing import Optional

import pandas as pd
import requests

from . import TZ

ENERGY_CHARTS = "https://api.energy-charts.info"
EDF_OUTAGES_CSV = (
    "https://opendata.edf.fr/api/explore/v2.1/catalog/datasets/"
    "indisponibilites-des-moyens-de-production-edf-sa/exports/csv"
)
TIMEOUT = 120  # l'export EDF complet peut être volumineux

# Capacités installées de référence (MW), à mettre à jour une fois par an
# à partir du bilan électrique RTE.
INSTALLED_REFERENCE = pd.Series(
    {
        "Nuclear": 63000.0,
        "Hydro Run-of-river and pondage": 11500.0,
        "Hydro Water Reservoir": 8300.0,
        "Hydro Pumped Storage": 5000.0,
        "Fossil Gas": 12600.0,
        "Fossil Hard coal": 1800.0,
        "Fossil Oil": 2500.0,
    }
)

# Libellés Energy-Charts (en minuscules) -> types ENTSO-E.
ENERGY_CHARTS_TYPES = {
    "nuclear": "Nuclear",
    "hydro run-of-river": "Hydro Run-of-river and pondage",
    "hydro water reservoir": "Hydro Water Reservoir",
    "hydro pumped storage": "Hydro Pumped Storage",
    "wind onshore": "Wind Onshore",
    "wind offshore": "Wind Offshore",
    "solar": "Solar",
    "fossil gas": "Fossil Gas",
    "fossil hard coal": "Fossil Hard coal",
    "fossil brown coal / lignite": "Fossil Brown coal/Lignite",
    "fossil oil": "Fossil Oil",
    "biomass": "Biomass",
    "waste": "Waste",
    "geothermal": "Geothermal",
    "others": "Other",
}


def _get_json(path: str, **params) -> dict:
    resp = requests.get(f"{ENERGY_CHARTS}/{path}", params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _window(now: pd.Timestamp, before: int, after: int) -> dict:
    today = now.normalize()
    return {
        "start": (today - pd.Timedelta(days=before)).strftime("%Y-%m-%d"),
        "end": (today + pd.Timedelta(days=after)).strftime("%Y-%m-%d"),
    }


def _index(unix_seconds) -> pd.DatetimeIndex:
    return pd.to_datetime(unix_seconds, unit="s", utc=True).tz_convert(TZ)


# --- Energy-Charts ---------------------------------------------------------------


def parse_energy_charts_prices(payload: dict) -> pd.Series:
    prices = pd.Series(payload["price"], index=_index(payload["unix_seconds"]), dtype=float)
    return prices.dropna().sort_index()


def parse_energy_charts_power(payload: dict) -> pd.DataFrame:
    idx = _index(payload["unix_seconds"])
    columns = {}
    for series in payload["production_types"]:
        psr = ENERGY_CHARTS_TYPES.get(series["name"].strip().lower())
        if psr is None:  # charge, échanges, consommation du pompage, parts renouvelables…
            continue
        columns[psr] = pd.Series(series["data"], index=idx, dtype=float)
    if not columns:
        raise ValueError("aucune filière reconnue dans la réponse Energy-Charts")
    return pd.DataFrame(columns).sort_index()


def energy_charts_prices(now: pd.Timestamp) -> pd.Series:
    today = now.normalize()
    prices = parse_energy_charts_prices(_get_json("price", bzn="FR", **_window(now, 2, 3)))
    return prices[(prices.index >= today - pd.Timedelta(days=1)) & (prices.index < today + pd.Timedelta(days=2))]


def energy_charts_generation(now: pd.Timestamp) -> pd.DataFrame:
    today = now.normalize()
    gen = parse_energy_charts_power(_get_json("public_power", country="fr", **_window(now, 2, 1)))
    return gen[(gen.index >= today - pd.Timedelta(days=1)) & (gen.index < today)]


# --- Open data EDF -------------------------------------------------------------


def _norm(label: str) -> str:
    s = unicodedata.normalize("NFKD", str(label)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# Colonnes recherchées par mots-clés, car les libellés exacts du jeu EDF peuvent évoluer.
# Chaque entrée : (mots tous présents, mots exclus).
EDF_COLUMNS = {
    "start": [({"debut"}, {"publication", "creation"})],
    "end": [({"fin"}, {"debut", "publication", "creation"})],
    "avail": [({"puissance", "disponible"}, {"indisponible"})],
    "nominal": [({"puissance", "maximale"}, set()), ({"puissance", "installee"}, set()),
                ({"puissance", "nominale"}, set()), ({"pmax"}, set())],
    "unit": [({"unite"}, {"identifiant", "code"}), ({"nom"}, {"identifiant", "code"})],
    "filiere": [({"filiere"}, set()), ({"combustible"}, set()), ({"type", "production"}, set())],
    "kind": [({"type", "indisponibilite"}, set()), ({"nature"}, set()), ({"type", "evenement"}, set())],
    "status": [({"statut"}, set()), ({"etat"}, set())],
    "id": [({"identifiant"}, {"unite"}), ({"id"}, {"unite"})],
    "version": [({"version"}, set()), ({"revision"}, set())],
    "created": [({"publication"}, set()), ({"creation"}, set()), ({"modification"}, set())],
}
EDF_REQUIRED = ("start", "end", "avail", "unit")


def _find_columns(columns) -> dict:
    words = {c: set(_norm(c).split()) for c in columns}
    found = {}
    for key, rules in EDF_COLUMNS.items():
        for required, excluded in rules:
            match = next((c for c, w in words.items() if required <= w and not (excluded & w)
                          and c not in found.values()), None)
            if match is not None:
                found[key] = match
                break
    missing = [k for k in EDF_REQUIRED if k not in found]
    if missing:
        raise ValueError(f"colonnes EDF introuvables ({', '.join(missing)}) parmi : {', '.join(map(str, columns))}")
    return found


def _edf_type(filiere: str) -> str:
    f = _norm(filiere)
    if "nucl" in f:
        return "Nuclear"
    if "fil de l eau" in f or "eclusee" in f:
        return "Hydro Run-of-river and pondage"
    if "step" in f or "pompage" in f:
        return "Hydro Pumped Storage"
    if "hydr" in f or "lac" in f:
        return "Hydro Water Reservoir"
    if "gaz" in f or "cycle combine" in f or "tac" in f.split():
        return "Fossil Gas"
    if "charbon" in f:
        return "Fossil Hard coal"
    if "fioul" in f or "fuel" in f or "petrole" in f:
        return "Fossil Oil"
    return "Other"


def parse_edf_outages(csv_text: str) -> pd.DataFrame:
    """CSV de l'open data EDF -> format des indisponibilités entsoe-py."""
    raw = pd.read_csv(io.StringIO(csv_text), sep=None, engine="python")
    col = _find_columns(raw.columns)

    def text(key, default=""):
        return raw[col[key]].astype(str) if key in col else pd.Series(default, index=raw.index)

    start = pd.to_datetime(raw[col["start"]], utc=True).dt.tz_convert(TZ)
    end = pd.to_datetime(raw[col["end"]], utc=True).dt.tz_convert(TZ)
    unit = text("unit")
    avail = pd.to_numeric(raw[col["avail"]], errors="coerce")
    nominal = pd.to_numeric(raw[col["nominal"]], errors="coerce") if "nominal" in col else avail * float("nan")
    kind = text("kind").map(_norm)
    status = text("status").map(_norm)
    mrid = text("id") if "id" in col else unit + "|" + start.astype(str)
    created = (pd.to_datetime(raw[col["created"]], utc=True) if "created" in col
               else pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns, UTC]"))

    df = pd.DataFrame(
        {
            "created_doc_time": created,
            "docstatus": status.map(lambda s: "Cancelled" if re.search(r"annul|retir|supprim", s) else "Active"),
            "mrid": mrid,
            "revision": pd.to_numeric(raw[col["version"]], errors="coerce").fillna(0) if "version" in col else 0,
            "businesstype": kind.map(lambda k: "Unplanned outage" if re.search(r"fortuit|non planif|imprevu", k)
                                     else "Planned maintenance"),
            "production_resource_id": unit,
            "production_resource_name": unit,
            "production_resource_psr_name": unit,
            "plant_type": text("filiere").map(_edf_type),
            "nominal_power": nominal,
            "start": start,
            "end": end,
            "avail_qty": avail,
        }
    )
    return df.set_index("created_doc_time").sort_index()


def edf_outages(now: pd.Timestamp) -> pd.DataFrame:
    resp = requests.get(EDF_OUTAGES_CSV, params={"use_labels": "true", "delimiter": ";"}, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    df = parse_edf_outages(resp.text)
    return df[(df["end"] > now - pd.Timedelta(days=1)) & (df["start"] < now + pd.Timedelta(days=8))]


def installed_reference() -> pd.Series:
    return INSTALLED_REFERENCE.copy()


def fallback_for(name: str):
    """Fonction de secours associée à une donnée (None s'il n'y en a pas)."""
    return {
        "Prix spot": ("Energy-Charts", energy_charts_prices),
        "Production": ("Energy-Charts", energy_charts_generation),
        "Indisponibilités": ("open data EDF", edf_outages),
        "Capacités installées": ("valeurs de référence", lambda now: installed_reference()),
    }.get(name)
