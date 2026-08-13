"""FastAPI-Anwendung."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routen import router
from app.db.sitzung import datenbank_url


BACKEND = Path(__file__).resolve().parent.parent.parent


def migriere() -> None:
    """Bringt die Datenbank auf den aktuellen Stand.

    Frueher wurde hier create_all aufgerufen. Das legt fehlende Tabellen an,
    aendert aber bestehende nie - eine Schemaaenderung liess sich nur durch
    Wegwerfen der Datenbank nachziehen. Waehrend einer laufenden Zaehlung
    waere das der Verlust der Inventur.
    """
    from alembic import command
    from alembic.config import Config

    einstellungen = Config(str(BACKEND / "alembic.ini"))
    einstellungen.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(einstellungen, "head")


@asynccontextmanager
async def lebenszyklus(_: FastAPI):
    # Abschaltbar, weil zwei Fälle keine Migration beim Start wollen: Tests
    # bauen ihr Schema selbst, und auf einem Server mit mehreren Prozessen
    # soll genau einmal migriert werden statt bei jedem Start erneut.
    if os.environ.get("INVENTUR_AUTO_MIGRATION", "1") != "0":
        migriere()
    yield


app = FastAPI(
    title="Cult Fashion – Inventur",
    description="Smartphone-Inventur für die Filiale Bad Krozingen.",
    version="0.1.0",
    lifespan=lebenszyklus,
)

# Die PWA laeuft im Browser der Mitarbeiterinnen, also auf einer anderen Herkunft.
herkuenfte = os.environ.get(
    "CORS_HERKUENFTE", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[h.strip() for h in herkuenfte if h.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api/status")
def status() -> dict:
    url = datenbank_url()
    return {"status": "ok", "datenbank": url.split("://", 1)[0]}


# Die PWA wird von derselben Herkunft ausgeliefert wie die API. Das spart im
# Laden die CORS-Konfiguration und macht die Installation auf dem Homescreen
# ohne zweiten Server moeglich. Muss NACH den Routen gemountet werden.
STATISCH = Path(__file__).resolve().parent.parent.parent / "static"
if STATISCH.is_dir():
    app.mount("/", StaticFiles(directory=STATISCH, html=True), name="pwa")
