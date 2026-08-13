from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Die Tests legen ihr Schema selbst an. Ohne das hier würde der TestClient
# beim Start Migrationen gegen die Entwicklungsdatenbank fahren.
os.environ["INVENTUR_AUTO_MIGRATION"] = "0"

from app.api.app import app  # noqa: E402
from app.db.sitzung import baue_engine, hole_sitzung, schema_anlegen  # noqa: E402
from app.db.tabellen import Basis, Inventur, Zaehlbereich  # noqa: E402
from app.dienste.import_dienst import importiere  # noqa: E402
from app.domain.werte import InventurStatus  # noqa: E402
from app.quellen.excel import ExcelBestandsQuelle  # noqa: E402

SAMPLES = BACKEND.parent / "samples"
REFERENZ = SAMPLES / "1_sollbestand_referenz.xlsx"
ROHEXPORT = SAMPLES / "2_advarics_export_roh.xlsx"


# Standard sind Tests gegen SQLite (schnell, ohne Serverinstallation).
# Fuer die Zielumgebung: TEST_DATABASE_URL=postgresql+psycopg2://... pytest
TEST_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


@pytest.fixture
def test_engine():
    engine = baue_engine(TEST_URL)
    Basis.metadata.drop_all(engine)
    schema_anlegen(engine)
    yield engine
    if not TEST_URL.startswith("sqlite"):
        Basis.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def sitzung(test_engine):
    fabrik = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    with fabrik() as s:
        yield s


@pytest.fixture
def inventur(sitzung):
    i = Inventur(filial_nr="12", filiale="Bad Krozingen",
                 bezeichnung="Testinventur", status=InventurStatus.ANGELEGT.value)
    sitzung.add(i)
    sitzung.commit()
    return i


@pytest.fixture
def inventur_mit_bestand(sitzung, inventur):
    importiere(sitzung, inventur, ExcelBestandsQuelle(REFERENZ), REFERENZ.name)
    return inventur


@pytest.fixture
def bereich(sitzung, inventur):
    b = Zaehlbereich(inventur_id=inventur.id, name="Verkaufsfläche",
                     zugewiesen_an="Anna")
    sitzung.add(b)
    sitzung.commit()
    return b


def _angemeldet(c: TestClient, name: str, pin: str, rolle: str = "zaehler",
                token: str | None = None) -> str:
    """Legt einen Benutzer an und meldet ihn an; gibt den Token zurück."""
    kopf = {"X-Token": token} if token else {}
    antwort = c.post("/api/benutzer",
                     json={"name": name, "pin": pin, "rolle": rolle}, headers=kopf)
    assert antwort.status_code == 201, antwort.text
    anmeldung = c.post("/api/anmeldung", json={"name": name, "pin": pin})
    assert anmeldung.status_code == 200, anmeldung.text
    return anmeldung.json()["token"]


@pytest.fixture
def roh_client(test_engine):
    """Ohne Anmeldung – für die Tests der Anmeldung selbst."""
    fabrik = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def sitzung_override():
        s = fabrik()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[hole_sitzung] = sitzung_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client(roh_client):
    """Angemeldet als Administratorin – der erste Benutzer ist immer Admin."""
    token = _angemeldet(roh_client, "Chefin", "1234")
    roh_client.headers.update({"X-Token": token})
    roh_client.admin_token = token
    return roh_client


@pytest.fixture
def zaehler_token(client):
    return _angemeldet(client, "Anna", "5678", "zaehler", client.admin_token)
