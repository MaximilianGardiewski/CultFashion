"""Anmeldung, Rollen, Zonenhierarchie mit Vorzählung, Markierungen."""

from __future__ import annotations

import pytest

from tests.conftest import _angemeldet
from tests.test_api import _importiere

EAN_NORMAL = "4053121000035"


# -- Anmeldung -----------------------------------------------------------

def test_erster_benutzer_wird_admin(roh_client):
    antwort = roh_client.post("/api/benutzer",
                              json={"name": "Chefin", "pin": "1234", "rolle": "zaehler"})
    assert antwort.status_code == 201
    # Rolle im Antrag wird für den ersten Benutzer bewusst übergangen
    assert antwort.json()["rolle"] == "admin"


def test_weitere_benutzer_nur_durch_admin(roh_client):
    admin = _angemeldet(roh_client, "Chefin", "1234")

    ohne = roh_client.post("/api/benutzer", json={"name": "Fremd", "pin": "1111"})
    assert ohne.status_code == 401

    mit = roh_client.post("/api/benutzer", json={"name": "Anna", "pin": "5678"},
                          headers={"X-Token": admin})
    assert mit.status_code == 201
    assert mit.json()["rolle"] == "zaehler"


def test_zaehler_darf_keine_benutzer_anlegen(roh_client):
    admin = _angemeldet(roh_client, "Chefin", "1234")
    anna = _angemeldet(roh_client, "Anna", "5678", "zaehler", admin)

    antwort = roh_client.post("/api/benutzer", json={"name": "Neu", "pin": "9999"},
                              headers={"X-Token": anna})
    assert antwort.status_code == 403


def test_falsche_pin_verraet_nicht_ob_der_name_existiert(roh_client):
    _angemeldet(roh_client, "Chefin", "1234")

    falsch = roh_client.post("/api/anmeldung", json={"name": "Chefin", "pin": "0000"})
    unbekannt = roh_client.post("/api/anmeldung", json={"name": "Gibtsnicht", "pin": "0000"})

    assert falsch.status_code == unbekannt.status_code == 401
    assert falsch.json()["detail"] == unbekannt.json()["detail"]


def test_ohne_token_kein_zugriff(roh_client):
    _angemeldet(roh_client, "Chefin", "1234")
    assert roh_client.get("/api/inventuren").status_code == 401


def test_kurze_pin_wird_abgelehnt(roh_client):
    assert roh_client.post("/api/benutzer",
                           json={"name": "Chefin", "pin": "12"}).status_code == 409


def test_abmelden_macht_den_token_ungueltig(roh_client):
    token = _angemeldet(roh_client, "Chefin", "1234")
    kopf = {"X-Token": token}

    assert roh_client.get("/api/inventuren", headers=kopf).status_code == 200
    assert roh_client.post("/api/abmeldung", headers=kopf).status_code == 204
    assert roh_client.get("/api/inventuren", headers=kopf).status_code == 401


# -- Zonen ---------------------------------------------------------------

@pytest.fixture
def inventur_id(client):
    antwort = client.post("/api/inventuren", json={"bezeichnung": "Zonen"})
    return antwort.json()["id"]


def test_bereich_mit_staendern_und_vorzaehlung(client, inventur_id):
    bereich = client.post(f"/api/inventuren/{inventur_id}/bereiche", json={
        "name": "100", "ebene": "bereich", "karte_x": 0.35, "karte_y": 0.72}).json()

    for name, soll in (("101", 62), ("102", 48)):
        antwort = client.post(f"/api/inventuren/{inventur_id}/bereiche", json={
            "name": name, "ebene": "staender", "eltern_id": bereich["id"],
            "soll_teile": soll})
        assert antwort.status_code == 201

    baum = client.get(f"/api/inventuren/{inventur_id}/bereiche").json()
    assert len(baum) == 1
    wurzel = baum[0]
    assert wurzel["name"] == "100"
    assert [k["name"] for k in wurzel["kinder"]] == ["101", "102"]
    # Der Bereich erbt die Summe seiner Ständer, damit dieselbe Zahl nicht
    # zweimal gepflegt werden muss.
    assert wurzel["soll_teile"] == 110
    assert wurzel["karte_x"] == 0.35


def test_fortschritt_zeigt_was_noch_fehlt(client, inventur_id):
    _importiere(client, inventur_id)
    bereich = client.post(f"/api/inventuren/{inventur_id}/bereiche", json={
        "name": "101", "soll_teile": 3}).json()

    client.post(f"/api/inventuren/{inventur_id}/scan",
                json={"code": EAN_NORMAL, "zaehlbereich_id": bereich["id"]})

    stand = client.get(f"/api/inventuren/{inventur_id}/bereiche").json()[0]
    assert stand["gezaehlt"] == 1
    assert stand["soll_teile"] == 3
    assert stand["offen"] == 2          # genau das, was ein vergessener Ständer wäre
    assert stand["anteil"] == pytest.approx(1 / 3)


def test_ohne_vorzaehlung_kein_erfundener_fortschritt(client, inventur_id):
    client.post(f"/api/inventuren/{inventur_id}/bereiche", json={"name": "Umkleide"})
    stand = client.get(f"/api/inventuren/{inventur_id}/bereiche").json()[0]
    assert stand["soll_teile"] is None
    assert stand["offen"] is None
    assert stand["anteil"] is None


def test_bereich_uebernehmen_und_abschliessen(client, inventur_id):
    bereich = client.post(f"/api/inventuren/{inventur_id}/bereiche",
                          json={"name": "101"}).json()
    pfad = f"/api/inventuren/{inventur_id}/bereiche/{bereich['id']}/status"

    laeuft = client.post(pfad, json={"status": "laeuft"}).json()
    assert laeuft["status"] == "laeuft"
    assert laeuft["zugewiesen_an"] == "Chefin"

    fertig = client.post(pfad, json={"status": "fertig"}).json()
    assert fertig["status"] == "fertig"


def test_belegter_bereich_wird_nicht_uebernommen(client, roh_client, inventur_id,
                                                 zaehler_token):
    """Auf der Karte muss sichtbar bleiben, dass dort schon jemand zählt."""
    bereich = client.post(f"/api/inventuren/{inventur_id}/bereiche",
                          json={"name": "101"}).json()
    pfad = f"/api/inventuren/{inventur_id}/bereiche/{bereich['id']}/status"

    assert client.post(pfad, json={"status": "laeuft"}).status_code == 200

    zweiter = roh_client.post(pfad, json={"status": "laeuft"},
                              headers={"X-Token": zaehler_token})
    assert zweiter.status_code == 409
    assert "Chefin" in zweiter.json()["detail"]


def test_zaehler_darf_keine_bereiche_anlegen(client, roh_client, inventur_id,
                                             zaehler_token):
    antwort = roh_client.post(f"/api/inventuren/{inventur_id}/bereiche",
                              json={"name": "999"},
                              headers={"X-Token": zaehler_token})
    assert antwort.status_code == 403


def test_staender_nur_unter_bereich(client, inventur_id):
    staender = client.post(f"/api/inventuren/{inventur_id}/bereiche",
                           json={"name": "101"}).json()
    antwort = client.post(f"/api/inventuren/{inventur_id}/bereiche", json={
        "name": "101a", "eltern_id": staender["id"]})
    assert antwort.status_code == 409


# -- Markierungen --------------------------------------------------------

def test_zaehler_markiert_statt_zu_stornieren(client, roh_client, inventur_id,
                                              zaehler_token):
    _importiere(client, inventur_id)
    kopf = {"X-Token": zaehler_token}

    scan = roh_client.post(f"/api/inventuren/{inventur_id}/scan",
                           json={"code": EAN_NORMAL}, headers=kopf).json()

    # Storno ist der Zählerin verwehrt ...
    storno = roh_client.post(
        f"/api/inventuren/{inventur_id}/scans/{scan['event_id']}/storno", headers=kopf)
    assert storno.status_code == 403

    # ... markieren darf sie
    markierung = roh_client.post(f"/api/inventuren/{inventur_id}/markierungen", json={
        "grund": "Versehentlich doppelt gescannt", "dringlichkeit": 2,
        "scan_event_id": scan["event_id"]}, headers=kopf)
    assert markierung.status_code == 201
    assert markierung.json()["gemeldet_von"] == "Anna"

    # Die Zählung bleibt unverändert stehen
    auswertung = client.get(f"/api/inventuren/{inventur_id}/auswertung").json()
    assert auswertung["kennzahlen"]["gezaehlt_gesamt"] == 1


def test_markierung_braucht_einen_grund(client, inventur_id):
    antwort = client.post(f"/api/inventuren/{inventur_id}/markierungen",
                          json={"grund": "?", "dringlichkeit": 1})
    assert antwort.status_code == 400


def test_dringlichkeit_nur_eins_bis_drei(client, inventur_id):
    for stufe in (0, 4, 9):
        antwort = client.post(f"/api/inventuren/{inventur_id}/markierungen",
                              json={"grund": "Etikett fehlt", "dringlichkeit": stufe})
        assert antwort.status_code == 400


def test_dringendstes_steht_oben(client, inventur_id):
    for stufe, grund in ((1, "kann warten"), (3, "blockiert"), (2, "heute klären")):
        client.post(f"/api/inventuren/{inventur_id}/markierungen",
                    json={"grund": grund, "dringlichkeit": stufe})

    liste = client.get(f"/api/inventuren/{inventur_id}/markierungen").json()
    assert [m["dringlichkeit"] for m in liste] == [3, 2, 1]

    anzahl = client.get(f"/api/inventuren/{inventur_id}/markierungen/anzahl").json()
    assert anzahl == {"gesamt": 3, "sofort": 1, "bald": 1, "spaeter": 1}


def test_nur_admin_erledigt_markierungen(client, roh_client, inventur_id, zaehler_token):
    markierung = client.post(f"/api/inventuren/{inventur_id}/markierungen",
                             json={"grund": "Ware beschädigt", "dringlichkeit": 3}).json()
    pfad = f"/api/inventuren/{inventur_id}/markierungen/{markierung['id']}/erledigt"

    assert roh_client.post(pfad, json={}, headers={"X-Token": zaehler_token}
                           ).status_code == 403

    erledigt = client.post(pfad, json={"antwort": "vor Ort geklärt"}).json()
    assert erledigt["status"] == "erledigt"
    assert erledigt["erledigt_von"] == "Chefin"

    assert client.get(f"/api/inventuren/{inventur_id}/markierungen").json() == []
    assert client.get(
        f"/api/inventuren/{inventur_id}/markierungen/anzahl").json()["gesamt"] == 0


def test_markierung_nicht_zweimal_erledigen(client, inventur_id):
    markierung = client.post(f"/api/inventuren/{inventur_id}/markierungen",
                             json={"grund": "Etikett fehlt", "dringlichkeit": 1}).json()
    pfad = f"/api/inventuren/{inventur_id}/markierungen/{markierung['id']}/erledigt"

    assert client.post(pfad, json={}).status_code == 200
    assert client.post(pfad, json={}).status_code == 409


def test_markierung_fremder_inventur_wird_abgewiesen(client, inventur_id):
    andere = client.post("/api/inventuren", json={"bezeichnung": "Andere"}).json()
    bereich = client.post(f"/api/inventuren/{andere['id']}/bereiche",
                          json={"name": "X"}).json()

    antwort = client.post(f"/api/inventuren/{inventur_id}/markierungen", json={
        "grund": "gehört woanders hin", "dringlichkeit": 1,
        "zaehlbereich_id": bereich["id"]})
    assert antwort.status_code == 400
