"""Point d'entrée : python -m bulletin [--demo] [--send] [--out fichier.html]."""

import argparse
import re
import sys
from html import unescape
from pathlib import Path

import pandas as pd

from . import TZ
from .config import SmtpConfig, entsoe_token
from .render import build_context, render_html, subject


def html_to_text(html: str) -> str:
    """Version texte brut minimale, pour les clients mail qui n'affichent pas le HTML."""
    text = re.sub(r"<(style|head)[^>]*>.*?</\1>", "", html, flags=re.S)
    text = re.sub(r"</(tr|p|h2|div|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = (re.sub(r"[ \t]+", " ", unescape(line)).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bulletin quotidien du marché électrique français")
    parser.add_argument("--demo", action="store_true", help="données synthétiques, sans appel à ENTSO-E")
    parser.add_argument("--send", action="store_true", help="envoyer le bulletin par mail (variables SMTP_*)")
    parser.add_argument("--out", type=Path, help="écrire le HTML dans ce fichier")
    args = parser.parse_args(argv)

    now = pd.Timestamp.now(tz=TZ).floor("min")
    if args.demo:
        from .demo import demo_data

        data = demo_data(now)
    else:
        from .sources import fetch

        data = fetch(entsoe_token(), now)

    ctx = build_context(data)
    html = render_html(ctx)
    subj = subject(ctx)
    print(subj)
    for note in data.notes:
        print(f"[secours] {note}", file=sys.stderr)
    for name, err in data.errors.items():
        print(f"[erreur] {name} : {err}", file=sys.stderr)

    if args.out:
        args.out.write_text(html, encoding="utf-8")
        print(f"HTML écrit dans {args.out}")
    if args.send:
        from .mailer import send

        cfg = SmtpConfig.from_env()
        send(cfg, subj, html, html_to_text(html))
        print(f"Envoyé à {', '.join(cfg.recipients)}")

    # Échec si aucune source n'a répondu, pour que la planification le signale.
    sources = [data.prices, data.generation, data.outages]
    return 1 if all(s is None for s in sources) else 0


if __name__ == "__main__":
    sys.exit(main())
