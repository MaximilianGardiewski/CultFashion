"""FastAPI-Anwendung."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routen import router
from app.db.sitzung import datenbank_url, schema_anlegen

app = FastAPI(
    title="Cult Fashion – Inventur",
    description="Smartphone-Inventur für die Filiale Bad Krozingen.",
    version="0.1.0",
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


@app.on_event("startup")
def starte() -> None:
    schema_anlegen()


@app.get("/api/status")
def status() -> dict:
    url = datenbank_url()
    return {"status": "ok", "datenbank": url.split("://", 1)[0]}
