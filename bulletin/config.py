"""Configuration lue depuis les variables d'environnement."""

import os
import re
from typing import Optional
from dataclasses import dataclass

GMAIL_SMTP = "smtp.gmail.com"


def is_gmail(address: str) -> bool:
    return address.strip().lower().endswith(("@gmail.com", "@googlemail.com"))


def clean_host(raw: str) -> tuple[str, Optional[int]]:
    """« smtp://smtp.gmail.com:587/ » -> ("smtp.gmail.com", 587) : un secret mal saisi ne bloque pas l'envoi."""
    host = re.sub(r"^[a-z]+://", "", raw.strip().lower()).strip("/ ")
    port = None
    if re.fullmatch(r"[^:]+:\d+", host):
        host, port_txt = host.rsplit(":", 1)
        port = int(port_txt)
    return host, port


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    recipients: list[str]

    @classmethod
    def from_env(cls) -> "SmtpConfig":
        missing = [k for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO") if not os.environ.get(k)]
        host, port_in_host = clean_host(os.environ.get("SMTP_HOST", ""))
        if not host:
            if is_gmail(os.environ.get("SMTP_USER", "")):
                host = GMAIL_SMTP
            else:
                missing.append("SMTP_HOST")
        if missing:
            raise RuntimeError(f"Variables d'environnement manquantes : {', '.join(missing)}")
        return cls(
            host=host,
            port=int((os.environ.get("SMTP_PORT") or "").strip() or port_in_host or 587),
            user=os.environ["SMTP_USER"].strip(),
            password=os.environ["SMTP_PASSWORD"],
            sender=os.environ.get("MAIL_FROM") or os.environ["SMTP_USER"],
            recipients=[r.strip() for r in os.environ["MAIL_TO"].split(",") if r.strip()],
        )


def entsoe_token() -> Optional[str]:
    """Clé ENTSO-E, ou None : le bulletin passe alors par les sources de secours."""
    return os.environ.get("ENTSOE_TOKEN") or None
