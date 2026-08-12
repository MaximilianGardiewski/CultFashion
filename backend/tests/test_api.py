"""Durchstich über die API: anlegen, importieren, zählen, auswerten, exportieren."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.app import app
from app.db.sitzung import hole_sitzung
from tests.conftest import REFERENZ, ROHEXPORT

EAN_NORMAL = "4053121000035"
EAN_TASCHE = "4184711001658"
EAN_KAPUTT = "4012345678902"


@pytest.fixture
def client(test_engine):
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
def inventur_id(client):
    antwort = client.post("/api/inventuren", json={
        "filial_nr": "12", "filiale": "Bad Krozingen", "bezeichnung": "Test"})
    assert antwort.status_code == 201
    return antwort.json()["id"]


def _importiere(client, inventur_id, pfad=REFERENZ, **params):
    with open(pfad, "rb") as f:
        return client.post(
            f"/api/inventuren/{inventur_id}/import",
            files={"datei": (pfad.name, f,
                             "application/vnd.openxmlformats-officedocument."
                             "spreadsheetml.sheet")},
            params=params)


def test_import_referenz(client, inventur_id):
    antwort = _importiere(client, inventur_id)
    assert antwort.status_code == 200
    assert antwort.json()["zeilen_importiert"] == 173


def test_import_rohexport(client, inventur_id):
    antwort = _importiere(client, inventur_id, pfad=ROHEXPORT)
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["zeilen_importiert"] == 173
    assert daten["spaltenzuordnung"]["artikelnummer"] == "Art.-Nr."


def test_zweiter_import_ohne_ersetzen_wird_abgelehnt(client, inventur_id):
    _importiere(client, inventur_id)
    assert _importiere(client, inventur_id).status_code == 409


def test_import_nach_erstem_scan_gesperrt(client, inventur_id):
    _importiere(client, inventur_id)
    client.post(f"/api/inventuren/{inventur_id}/scan", json={"code": EAN_NORMAL})

    antwort = _importiere(client, inventur_id, ersetzen=True)
    assert antwort.status_code == 409
    assert "gezählt" in antwort.json()["detail"]


def test_durchstich_zaehlen_und_auswerten(client, inventur_id):
    _importiere(client, inventur_id)

    bereich = client.post(f"/api/inventuren/{inventur_id}/bereiche",
                          json={"name": "Fläche", "zugewiesen_an": "Anna"}).json()

    # eindeutig
    scan = client.post(f"/api/inventuren/{inventur_id}/scan", json={
        "code": EAN_NORMAL, "zaehlbereich_id": bereich["id"], "erfasst_von": "Anna",
    }).json()
    assert scan["ergebnis"] == "eindeutig"
    assert scan["artikel"]["artikelname"] == "Bluse Falia"
    assert scan["gezaehlt"] == 1

    # mehrdeutig -> Auswahl
    mehrdeutig = client.post(f"/api/inventuren/{inventur_id}/scan",
                             json={"code": EAN_TASCHE}).json()
    assert mehrdeutig["ergebnis"] == "mehrdeutig"
    assert len(mehrdeutig["kandidaten"]) == 4

    gewaehlt = mehrdeutig["kandidaten"][0]["id"]
    gebucht = client.post(f"/api/inventuren/{inventur_id}/buchung", json={
        "position_id": gewaehlt, "zaehlbereich_id": bereich["id"],
        "erfasst_von": "Anna", "roh_code": EAN_TASCHE}).json()
    assert gebucht["gezaehlt"] == 1

    # ungueltig
    kaputt = client.post(f"/api/inventuren/{inventur_id}/scan",
                         json={"code": EAN_KAPUTT}).json()
    assert kaputt["ergebnis"] == "ungueltig"
    assert kaputt["event_id"] is None

    # Storno
    storno = client.post(
        f"/api/inventuren/{inventur_id}/scans/{scan['event_id']}/storno").json()
    assert storno["gezaehlt"] == 0

    # Log
    log = client.get(f"/api/inventuren/{inventur_id}/log").json()
    assert len(log) == 3          # Scan, Auswahl, Storno – ungültig ist kein Event
    assert log[0]["erfassungsart"] == "storno"

    # Auswertung
    auswertung = client.get(f"/api/inventuren/{inventur_id}/auswertung").json()
    assert auswertung["kennzahlen"]["positionen_gesamt"] == 173
    assert auswertung["kennzahlen"]["scans_gesamt"] == 3

    # Export
    export = client.get(f"/api/inventuren/{inventur_id}/export.xlsx")
    assert export.status_code == 200
    assert export.content[:2] == b"PK"      # xlsx ist ein ZIP
    assert len(export.content) > 5000


def test_suche_ueber_api(client, inventur_id):
    _importiere(client, inventur_id)
    treffer = client.get(f"/api/inventuren/{inventur_id}/suche",
                         params={"q": "Wilana"}).json()
    assert treffer
    assert any(t["ean"] is None for t in treffer)


def test_unbekannte_inventur_gibt_404(client):
    assert client.get("/api/inventuren/999").status_code == 404
