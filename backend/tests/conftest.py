from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.db.sitzung import baue_engine, schema_anlegen  # noqa: E402
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
