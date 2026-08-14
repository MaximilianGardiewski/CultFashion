"""Datenbankverbindung.

Laeuft gegen PostgreSQL (Zielumgebung auf dem VPS) und gegen SQLite
(Tests und lokale Entwicklung ohne Serverinstallation). Gesteuert ueber
die Umgebungsvariable DATABASE_URL.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.tabellen import Basis

STANDARD_URL = "sqlite:///./inventur.db"


def datenbank_url() -> str:
    return os.environ.get("DATABASE_URL", STANDARD_URL)


def baue_engine(url: str | None = None):
    url = url or datenbank_url()
    optionen: dict = {"future": True}
    if url.startswith("sqlite"):
        # check_same_thread=False, weil FastAPI die Session aus Workerthreads nutzt
        optionen["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # Ohne StaticPool bekaeme jede Verbindung ihre eigene leere
            # In-Memory-Datenbank - Tests wuerden ins Nichts schreiben.
            optionen["poolclass"] = StaticPool
    return create_engine(url, **optionen)


engine = baue_engine()
SessionFabrik = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def schema_anlegen(ziel_engine=None) -> None:
    Basis.metadata.create_all(ziel_engine or engine)


def hole_sitzung():
    """FastAPI-Dependency."""
    sitzung = SessionFabrik()
    try:
        yield sitzung
    finally:
        sitzung.close()


__all__ = ["Session", "engine", "SessionFabrik", "schema_anlegen",
           "hole_sitzung", "baue_engine", "datenbank_url"]
