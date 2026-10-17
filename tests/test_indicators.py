import pandas as pd
import pytest

from bulletin import TZ
from bulletin import indicators as ind
from bulletin.demo import demo_data, demo_generation, demo_outages
from bulletin.render import build_context, duree, nombre, render_html, subject

NOW = pd.Timestamp("2026-10-12 14:00", tz=TZ)


def test_price_stats_quart_horaire():
    idx = pd.date_range("2026-10-12", periods=96, freq="15min", tz=TZ)
    prices = pd.Series(50.0, index=idx)
    prices[(idx.hour >= 12) & (idx.hour < 14)] = -5.0  # 2 h négatives
    prices[idx.hour == 19] = 200.0

    s = ind.price_stats(prices, NOW)
    assert s.negative_hours == pytest.approx(2.0)
    assert s.max == 200 and s.max_at.hour == 19
    assert s.min == -5
    assert s.base == pytest.approx(prices.mean())
    # Pointe 8h-20h : 48 quarts d'heure, dont 8 négatifs et 4 à 200.
    assert s.peak == pytest.approx((36 * 50 + 8 * -5 + 4 * 200) / 48)
    assert len(s.hourly) == 24


def test_price_stats_jour_non_publie():
    idx = pd.date_range("2026-10-12", periods=24, freq="h", tz=TZ)
    prices = pd.Series(50.0, index=idx)
    assert ind.price_stats(prices, NOW + pd.Timedelta(days=1)) is None
    assert ind.price_stats(None, NOW) is None


def test_generation_mix_regroupe_les_filieres():
    gen = demo_generation(pd.Timestamp("2026-10-11", tz=TZ))
    mix = ind.generation_mix(gen)
    assert list(mix.index)[:3] == ["Nucléaire", "Hydraulique", "Éolien"]
    assert "Charbon" not in mix.index  # production nulle
    assert mix["part"].sum() == pytest.approx(1.0)
    expected_wind = (gen["Wind Onshore"] + gen["Wind Offshore"]).sum() * 0.25 / 1000
    assert mix.loc["Éolien", "energie_gwh"] == pytest.approx(expected_wind)


def test_generation_mix_colonnes_multiindex():
    idx = pd.date_range("2026-10-11", periods=24, freq="h", tz=TZ)
    cols = pd.MultiIndex.from_tuples([("Nuclear", "Actual Aggregated"), ("Hydro Pumped Storage", "Actual Aggregated"),
                                      ("Hydro Pumped Storage", "Actual Consumption")])
    gen = pd.DataFrame([[1000.0, 100.0, 300.0]] * 24, index=idx, columns=cols)
    mix = ind.generation_mix(gen)
    assert mix.loc["Nucléaire", "energie_gwh"] == pytest.approx(24.0)
    assert mix.loc["Hydraulique", "energie_gwh"] == pytest.approx(2.4)


def test_outages_derniere_revision_et_annulations():
    outages = ind.latest_outages(demo_outages(NOW))
    assert "GOLFECH 1" not in set(outages["production_resource_psr_name"])
    current = ind.current_outages(outages, NOW)
    gravelines = current.set_index("production_resource_psr_name").loc["GRAVELINES 4"]
    assert gravelines["indispo_mw"] == 310  # 910 MW nominal, 600 MW disponibles
    assert current["indispo_mw"].is_monotonic_decreasing


def test_outages_unite_recouverte_comptee_une_fois():
    raw = demo_outages(NOW).reset_index()
    doublon = raw[raw["mrid"] == "m2"].assign(mrid="m2bis", avail_qty="650")
    raw = pd.concat([raw, doublon]).set_index("created_doc_time")
    current = ind.current_outages(ind.latest_outages(raw), NOW)
    cattenom = current[current["production_resource_psr_name"] == "CATTENOM 3"]
    assert len(cattenom) == 1 and cattenom["indispo_mw"].iloc[0] == 1300


def test_disponibilite_nucleaire():
    data = demo_data(NOW)
    current = ind.current_outages(ind.latest_outages(data.outages), NOW)
    dispo = ind.availability_by_filiere(current, data.installed)
    nuc = dispo.loc["Nucléaire"]
    assert nuc["indispo_mw"] == 1330 + 1300 + 1330 + 310 + 915 + 880 + 500
    assert nuc["dispo_mw"] == pytest.approx(62990 - nuc["indispo_mw"])


def test_retours_et_fortuites():
    current = ind.current_outages(ind.latest_outages(demo_outages(NOW)), NOW)
    retours = ind.upcoming_returns(current, NOW)
    assert "CATTENOM 3" not in set(retours["production_resource_psr_name"])  # retour à J+25
    assert retours["fin_prevue"].is_monotonic_increasing
    fortuites = ind.new_forced_outages(current, NOW)
    assert set(fortuites["production_resource_psr_name"]) == {"PALUEL 2", "CHOOZ B1", "BLENOD 5"}


def test_outages_vides():
    empty = pd.DataFrame(columns=["created_doc_time", "mrid", "revision", "docstatus"]).set_index("created_doc_time")
    assert ind.latest_outages(empty).empty


def test_rendu_complet_et_sources_en_erreur():
    data = demo_data(NOW)
    ctx = build_context(data)
    html = render_html(ctx)
    assert "Lundi 12 octobre 2026" in html
    assert "PALUEL 2" in html
    assert "Nucléaire dispo" in subject(ctx)

    data.prices = None
    data.errors["Prix spot"] = "HTTPError: 503"
    ctx = build_context(data)
    html = render_html(ctx)
    assert "HTTPError: 503" in html
    assert "Spot" not in subject(ctx)


def test_formats_francais():
    assert nombre(62990) == "62 990"
    assert nombre(72.84, 1) == "72,8"
    assert nombre(None) == "–"
    assert duree(1.75) == "1h45"
    assert duree(2.0) == "2h"
    assert duree(0) == "0"


def test_source_en_echec_consignee():
    from bulletin.sources import MarketData

    data = MarketData(now=NOW)
    assert data.attempt("Prix spot", lambda: 1 / 0) is None
    assert data.errors["Prix spot"].startswith("ZeroDivisionError")


def test_envoi_smtp(monkeypatch):
    from bulletin import mailer
    from bulletin.config import SmtpConfig

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port):
            sent["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = user

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.socket, "getaddrinfo", lambda *a, **k: [object()])
    cfg = SmtpConfig("smtp.example.org", 587, "moi@example.org", "x", "moi@example.org", ["a@example.org", "b@example.org"])
    mailer.send(cfg, "Objet", "<p>html</p>", "texte")
    assert sent["server"] == ("smtp.example.org", 587) and sent["tls"]
    assert sent["msg"]["To"] == "a@example.org, b@example.org"
    assert sent["msg"].get_body(("html",)).get_content().strip() == "<p>html</p>"


def test_unite_declaree_sous_deux_identifiants_et_plafond():
    raw = demo_outages(NOW).reset_index()
    cordemais = raw[raw["mrid"] == "m10"]
    # Même unité, autre identifiant de centrale et nom écrit différemment.
    doublon = cordemais.assign(mrid="m10bis", production_resource_id="17W-AUTRE", production_resource_psr_name="Cordemais-4")
    raw = pd.concat([raw, doublon]).set_index("created_doc_time")
    current = ind.current_outages(ind.latest_outages(raw), NOW)
    assert (current["filiere"] == "Charbon").sum() == 1

    installed = demo_data(NOW).installed.copy()
    installed["Fossil Hard coal"] = 300.0  # capacité recensée inférieure à l'indisponibilité déclarée
    dispo = ind.availability_by_filiere(current, installed)
    assert dispo.loc["Charbon", "indispo_mw"] == 300
    assert dispo.loc["Charbon", "dispo_mw"] == 0


def test_date_courte_avec_annee_si_autre_annee():
    from bulletin.render import date_courte

    this_year = pd.Timestamp.now(tz=TZ).year
    assert date_courte(pd.Timestamp(f"{this_year}-10-14 23:00", tz=TZ)) == "14/10 23h"
    assert date_courte(pd.Timestamp(f"{this_year + 1}-09-11 00:00", tz=TZ)) == f"11/09/{(this_year + 1) % 100:02d} 00h"


def test_retours_petites_unites_resumees():
    data = demo_data(NOW)
    ctx = build_context(data)
    assert "SABLONS G1" in set(ctx["retours"]["production_resource_psr_name"])
    assert "SABLONS G1" not in set(ctx["retours_affiches"]["production_resource_psr_name"])
    html = render_html(ctx)
    assert "1 unité(s) de moins de 100 MW non détaillée(s) (40 MW)" in html


def test_bulletin_du_matin_sans_prix_j1():
    data = demo_data(NOW)
    data.prices = data.prices[data.prices.index < NOW.normalize() + pd.Timedelta(days=1)]
    ctx = build_context(data)
    assert ctx["lendemain"] is None
    html = render_html(ctx)
    assert "Spot base aujourd" in html and "vs hier" in html
    assert "publication vers 13h" in html
    assert "Spot J base" in subject(ctx)


def test_resume_insere_en_tete_et_reprise_du_bulletin(tmp_path):
    from bulletin.__main__ import main

    brut = tmp_path / "brut.html"
    assert main(["--demo", "--out", str(brut)]) == 0
    html = brut.read_text(encoding="utf-8")
    assert "<!--RESUME-->" in html and "En bref" not in html
    assert "<title>Bulletin électricité FR – " in html

    final = tmp_path / "final.html"
    resume = "Prix en hausse <nette>.\nNucléaire stable.\n\nDeuxième paragraphe."
    assert main(["--from-html", str(brut), "--resume", resume, "--out", str(final)]) == 0
    out = final.read_text(encoding="utf-8")
    assert "En bref" in out and "<!--RESUME-->" not in out
    assert "Prix en hausse &lt;nette&gt;.<br>Nucléaire stable." in out
    assert out.count("<p style=\"margin:0 0 8px") == 2
    # Le reste du bulletin est repris à l'identique.
    assert out.replace(out[out.index("<tr><td style=\"padding:16px 20px 0;\"><div"):out.index("</div></td></tr>") + 16], "<!--RESUME-->") == html


def test_resume_vide_laisse_le_bulletin_intact():
    from bulletin.render import insert_summary, subject_from_html

    html = "<html><head><title>Bulletin électricité FR – 17/10/2026 · Spot J base 139 €/MWh</title></head><!--RESUME--></html>"
    assert insert_summary(html, "  \n ") == html
    assert subject_from_html(html) == "Bulletin électricité FR – 17/10/2026 · Spot J base 139 €/MWh"
