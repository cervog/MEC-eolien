import pandas as pd
import pytest

from bulletin import TZ, fallback, sources
from bulletin import indicators as ind
from bulletin.demo import demo_data, demo_prices
from bulletin.render import build_context, render_html

NOW = pd.Timestamp("2026-10-12 14:00", tz=TZ)
T0 = int(pd.Timestamp("2026-10-11", tz=TZ).timestamp())


def test_prix_energy_charts():
    payload = {"unix_seconds": [T0 + 900 * i for i in range(4)], "price": [50.0, None, -3.5, 80.0], "unit": "EUR / MWh"}
    prices = fallback.parse_energy_charts_prices(payload)
    assert list(prices) == [50.0, -3.5, 80.0]
    assert str(prices.index.tz) == TZ and prices.index[0] == pd.Timestamp("2026-10-11", tz=TZ)


def test_production_energy_charts():
    payload = {
        "unix_seconds": [T0 + 900 * i for i in range(96)],
        "production_types": [
            {"name": "Nuclear", "data": [40000.0] * 96},
            {"name": "Hydro pumped storage consumption", "data": [-500.0] * 96},
            {"name": "Wind onshore", "data": [5000.0] * 96},
            {"name": "Load", "data": [55000.0] * 96},
            {"name": "Renewable share of load", "data": [20.0] * 96},
        ],
    }
    gen = fallback.parse_energy_charts_power(payload)
    assert set(gen.columns) == {"Nuclear", "Wind Onshore"}
    mix = ind.generation_mix(gen)
    assert mix.loc["Nucléaire", "energie_gwh"] == pytest.approx(960.0)


EDF_CSV = """Identifiant;Version;Statut;Date de publication;Nom de l'unité de production;Filière;Type d'indisponibilité;Date de début;Date de fin;Puissance maximale (MW);Puissance disponible (MW)
ID1;1;Active;2026-10-12T09:00:00+02:00;PALUEL 2;Nucléaire;Fortuite;2026-10-12T09:00:00+02:00;2026-10-14T16:00:00+02:00;1330;0
ID2;1;Active;2026-09-01T09:00:00+02:00;CATTENOM 3;Nucléaire;Planifiée;2026-09-30T00:00:00+02:00;2026-11-06T15:00:00+01:00;1300;0
ID2;2;Active;2026-10-01T09:00:00+02:00;CATTENOM 3;Nucléaire;Planifiée;2026-09-30T00:00:00+02:00;2026-11-10T15:00:00+01:00;1300;0
ID3;1;Active;2026-10-10T09:00:00+02:00;GRAVELINES 4;Nucléaire;Fortuite;2026-10-10T09:00:00+02:00;2026-10-13T16:00:00+02:00;910;600
ID4;2;Annulée;2026-10-11T09:00:00+02:00;GOLFECH 1;Nucléaire;Planifiée;2026-10-11T00:00:00+02:00;2026-10-20T00:00:00+02:00;1310;0
ID5;1;Active;2026-10-05T09:00:00+02:00;MONTEZIC 1;Hydraulique STEP;Planifiée;2026-10-05T00:00:00+02:00;2026-10-21T16:00:00+02:00;230;0
ID6;1;Active;2026-10-12T04:00:00+02:00;BLENOD 5;Thermique gaz (cycle combiné);Fortuite;2026-10-12T04:00:00+02:00;2026-10-13T22:00:00+02:00;430;0
"""


def test_indisponibilites_edf():
    current = ind.current_outages(ind.latest_outages(fallback.parse_edf_outages(EDF_CSV)), NOW)
    units = current.set_index("production_resource_psr_name")
    assert "GOLFECH 1" not in units.index  # annulée
    assert units.loc["CATTENOM 3", "fin_prevue"] == pd.Timestamp("2026-11-10 15:00", tz=TZ)  # dernière version
    assert units.loc["GRAVELINES 4", "indispo_mw"] == 310
    assert units.loc["MONTEZIC 1", "filiere"] == "Hydraulique"
    assert units.loc["BLENOD 5", "filiere"] == "Gaz"
    fortuites = ind.new_forced_outages(current, NOW)
    assert set(fortuites["production_resource_psr_name"]) == {"PALUEL 2", "BLENOD 5"}


def test_colonnes_edf_introuvables():
    with pytest.raises(ValueError, match="colonnes EDF introuvables"):
        fallback.parse_edf_outages("a;b\n1;2\n")


class FakeClient:
    """Client ENTSO-E dont seuls les prix répondent."""

    def __init__(self, api_key):
        pass

    def query_day_ahead_prices(self, *a, **k):
        return demo_prices(NOW.normalize() - pd.Timedelta(days=1))

    def query_generation(self, *a, **k):
        raise ConnectionError("503")

    def query_installed_generation_capacity(self, *a, **k):
        raise ConnectionError("503")

    def query_unavailability_of_generation_units(self, *a, **k):
        raise ConnectionError("503")


def _fake_fallbacks(monkeypatch, fail=()):
    demo = demo_data(NOW)
    values = {"Prix spot": demo.prices, "Production": demo.generation,
              "Capacités installées": demo.installed, "Indisponibilités": demo.outages}

    def fallback_for(name):
        def fetch(now):
            if name in fail:
                raise TimeoutError("hors ligne")
            return values[name]
        return (f"secours-{name}", fetch)

    monkeypatch.setattr(sources, "fallback_for", fallback_for)


def test_bascule_vers_le_secours(monkeypatch):
    import entsoe

    monkeypatch.setattr(entsoe, "EntsoePandasClient", FakeClient)
    _fake_fallbacks(monkeypatch, fail={"Capacités installées"})
    data = sources.fetch("token", NOW)

    assert data.sources["Prix spot"] == "ENTSO-E"
    assert data.sources["Production"] == "secours-Production"
    assert data.sources["Indisponibilités"] == "secours-Indisponibilités"
    assert data.generation is not None and data.outages is not None
    assert any("Production : ENTSO-E en échec" in n for n in data.notes)
    # Les deux sources en échec : l'erreur mentionne les deux.
    assert data.installed is None
    assert "ENTSO-E" in data.errors["Capacités installées"] and "hors ligne" in data.errors["Capacités installées"]

    html = render_html(build_context(data))
    assert "ENTSO-E en échec" in html and "open data EDF" not in html


def test_sans_cle_entsoe(monkeypatch):
    _fake_fallbacks(monkeypatch)
    data = sources.fetch(None, NOW)
    assert "ENTSO-E" not in data.sources.values()
    assert not data.errors
    assert data.notes == ["Pas de clé ENTSO-E : sources de secours utilisées."]
