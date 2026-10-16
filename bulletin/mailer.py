"""Envoi du bulletin par SMTP."""

import smtplib
import socket
import ssl
import sys
from dataclasses import replace
from email.message import EmailMessage

from .config import GMAIL_SMTP, SmtpConfig, is_gmail


def reachable_config(cfg: SmtpConfig) -> SmtpConfig:
    """Vérifie que le serveur SMTP existe ; pour un compte Gmail, repli sur smtp.gmail.com sinon."""
    try:
        socket.getaddrinfo(cfg.host, cfg.port)
        return cfg
    except socket.gaierror:
        if is_gmail(cfg.user) and cfg.host != GMAIL_SMTP:
            print(f"[secours] Serveur SMTP introuvable (secret SMTP_HOST à vérifier) : envoi via {GMAIL_SMTP}.",
                  file=sys.stderr)
            return replace(cfg, host=GMAIL_SMTP, port=cfg.port if cfg.port in (465, 587) else 587)
        raise RuntimeError("Serveur SMTP introuvable : vérifier le secret SMTP_HOST (nom du serveur seul, "
                           "sans espace, sans « smtp:// » ni port).") from None


def send(cfg: SmtpConfig, subject: str, html: str, text: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(cfg.recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    cfg = reachable_config(cfg)
    context = ssl.create_default_context()
    if cfg.port == 465:
        with smtplib.SMTP_SSL(cfg.host, cfg.port, context=context) as smtp:
            smtp.login(cfg.user, cfg.password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(cfg.host, cfg.port) as smtp:
            smtp.starttls(context=context)
            smtp.login(cfg.user, cfg.password)
            smtp.send_message(msg)
