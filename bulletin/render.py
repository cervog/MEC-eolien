"""Mise en forme du bulletin (HTML pour le mail + objet)."""

from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import indicators as ind
from .sources import MarketData

SEUIL_RETOURS_MW = 100  # en dessous, les retours sont seulement comptés dans le total

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def nombre(x, decimales: int = 0) -> str:
    """Format français : espace fine insécable en séparateur de milliers, virgule décimale."""
    if x is None or pd.isna(x):
        return "–"
    s = f"{x:,.{decimales}f}"
    return s.replace(",", " ").replace(".", ",")


def pourcent(x, decimales: int = 0) -> str:
    return "–" if x is None or pd.isna(x) else f"{nombre(100 * x, decimales)} %"


def date_longue(ts: pd.Timestamp) -> str:
    return f"{JOURS[ts.weekday()]} {ts.day} {MOIS[ts.month - 1]} {ts.year}"


def date_courte(ts) -> str:
    """« 14/10 23h », avec l'année si ce n'est pas l'année en cours : « 11/09/27 00h »."""
    if ts is None or pd.isna(ts):
        return "–"
    ts = pd.Timestamp(ts)
    return ts.strftime("%d/%m %Hh" if ts.year == pd.Timestamp.now().year else "%d/%m/%y %Hh")


def heure(ts) -> str:
    return pd.Timestamp(ts).strftime("%Hh%M")


def duree(heures: float) -> str:
    """3.25 -> « 3h15 », 0 -> « 0 »."""
    if not heures:
        return "0"
    h, m = divmod(round(heures * 60), 60)
    return f"{h}h{m:02d}" if m else f"{h}h"


def couleur_prix(p: float, lo: float, hi: float) -> str:
    """Fond de cellule : bleu si négatif, puis dégradé vert → rouge."""
    if pd.isna(p):
        return "#eeeeee"
    if p < 0:
        return "#9ecae1"
    t = 0.0 if hi <= lo else (p - lo) / (hi - lo)
    r = int(120 + 135 * t)
    g = int(200 - 110 * t)
    return f"#{r:02x}{g:02x}78"


def build_context(data: MarketData) -> dict:
    now = data.now
    today = now.normalize()
    day = pd.Timedelta(days=1)

    veille = ind.price_stats(data.prices, today - day)
    jour = ind.price_stats(data.prices, today)
    lendemain = ind.price_stats(data.prices, today + day)
    reference = jour or veille

    profil = lendemain or jour
    profil_cells = []
    if profil is not None:
        lo, hi = max(profil.hourly.min(), 0), profil.hourly.max()
        profil_cells = [
            {"h": h, "prix": nombre(p), "fond": couleur_prix(p, lo, hi)} for h, p in profil.hourly.items()
        ]

    outages = ind.latest_outages(data.outages)
    current = ind.current_outages(outages, now)
    dispo = ind.availability_by_filiere(current, data.installed)
    retours = ind.upcoming_returns(current, now)
    nucleaire = None
    if dispo is not None and "Nucléaire" in dispo.index:
        nucleaire = dispo.loc["Nucléaire"]

    return {
        "now": now,
        "titre_date": date_longue(today),
        "veille": veille,
        "jour": jour,
        "lendemain": lendemain,
        "reference": reference,
        "profil": profil,
        "profil_cells": profil_cells,
        "mix": ind.generation_mix(data.generation),
        "dispo": dispo,
        "nucleaire": nucleaire,
        "current": current,
        "top_indispo": current.head(15) if current is not None else None,
        "retours": retours,
        "retours_affiches": None if retours is None else retours[retours["indispo_mw"] >= SEUIL_RETOURS_MW],
        "fortuites": ind.new_forced_outages(current, now),
        "errors": data.errors,
        "sources": data.sources,
        "notes": data.notes,
    }


def subject(ctx: dict) -> str:
    parts = [f"Bulletin électricité FR – {ctx['now']:%d/%m/%Y}"]
    if ctx["lendemain"] is not None:
        parts.append(f"Spot J+1 base {nombre(ctx['lendemain'].base)} €/MWh")
    elif ctx["jour"] is not None:
        parts.append(f"Spot J base {nombre(ctx['jour'].base)} €/MWh")
    nuc = ctx["nucleaire"]
    if nuc is not None and "dispo_mw" in nuc:
        parts.append(f"Nucléaire dispo {nombre(nuc['dispo_mw'] / 1000, 1)} GW")
    return " · ".join(parts)


def render_html(ctx: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(nombre=nombre, pourcent=pourcent, date_courte=date_courte, heure=heure,
                       date_longue=date_longue, duree=duree)
    return env.get_template("bulletin.html.j2").render(**ctx)
