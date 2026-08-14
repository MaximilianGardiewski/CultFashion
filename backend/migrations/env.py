"""Alembic-Umgebung.

Die Verbindung kommt aus DATABASE_URL, damit dieselben Migrationen gegen
SQLite (Entwicklung) und PostgreSQL (VPS) laufen.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.db.sitzung import datenbank_url  # noqa: E402
from app.db.tabellen import Basis  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", datenbank_url().replace("%", "%%"))
ziel_metadaten = Basis.metadata


def _ist_sqlite() -> bool:
    return datenbank_url().startswith("sqlite")


def offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=ziel_metadaten,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_ist_sqlite(),
    )
    with context.begin_transaction():
        context.run_migrations()


def online() -> None:
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as verbindung:
        context.configure(
            connection=verbindung,
            target_metadata=ziel_metadaten,
            # SQLite kann Spalten und Constraints nicht nachträglich ändern.
            # Batch-Modus baut die Tabelle im Hintergrund neu auf, damit
            # spätere Migrationen nicht nur auf PostgreSQL funktionieren.
            render_as_batch=_ist_sqlite(),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    offline()
else:
    online()
