"""Point d'entrée : python -m bulletin [--demo] [--send] [--out fichier.html].

Envoi avec résumé en deux temps : un premier run génère le bulletin sans l'envoyer,
puis « --from-html bulletin.html --resume "…" --send » le reprend tel quel, place
le résumé en tête et l'envoie.
"""

import argparse
import re
import sys
from html import unescape
from pathlib import Path

import pandas as pd

from . import TZ
from .config import SmtpConfig, entsoe_token
from .render import build_context, insert_summary, render_html, subject, subject_from_html


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
    parser.add_argument("--print", action="store_true", dest="print_text", help="afficher la version texte du bulletin")
    parser.add_argument("--from-html", type=Path, help="reprendre un bulletin déjà généré au lieu de collecter les données")
    parser.add_argument("--resume", default="", help="résumé rédigé à placer en tête du mail")
    args = parser.parse_args(argv)

    if args.from_html:
        html = insert_summary(args.from_html.read_text(encoding="utf-8"), args.resume)
        return deliver(args, subject_from_html(html), html)

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
    for note in data.notes:
        print(f"[secours] {note}", file=sys.stderr)
    for name, err in data.errors.items():
        print(f"[erreur] {name} : {err}", file=sys.stderr)

    html = insert_summary(html, args.resume)
    deliver(args, subj, html)

    # Échec si aucune source n'a répondu, pour que la planification le signale.
    sources = [data.prices, data.generation, data.outages]
    return 1 if all(s is None for s in sources) else 0


def deliver(args, subj: str, html: str) -> int:
    print(subj)
    if args.print_text:
        print(html_to_text(html))
    if args.out:
        args.out.write_text(html, encoding="utf-8")
        print(f"HTML écrit dans {args.out}")
    if args.send:
        from .mailer import send

        cfg = SmtpConfig.from_env()
        send(cfg, subj, html, html_to_text(html))
        print(f"Envoyé à {', '.join(cfg.recipients)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
