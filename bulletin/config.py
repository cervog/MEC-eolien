"""Configuration lue depuis les variables d'environnement."""

import os
from dataclasses import dataclass


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
        missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"Variables d'environnement manquantes : {', '.join(missing)}")
        return cls(
            host=os.environ["SMTP_HOST"],
            port=int(os.environ.get("SMTP_PORT") or "587"),
            user=os.environ["SMTP_USER"],
            password=os.environ["SMTP_PASSWORD"],
            sender=os.environ.get("MAIL_FROM") or os.environ["SMTP_USER"],
            recipients=[r.strip() for r in os.environ["MAIL_TO"].split(",") if r.strip()],
        )


def entsoe_token() -> str:
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        raise RuntimeError("Variable d'environnement ENTSOE_TOKEN manquante")
    return token
