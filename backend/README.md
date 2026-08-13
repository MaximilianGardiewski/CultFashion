# Inventur-Backend

Smartphone-Inventur für die Filiale Bad Krozingen. Liest den Sollbestand aus
einer advarics-Excel, nimmt Scans entgegen und liefert die Differenzliste zurück.

## Starten

    pip install -r requirements.txt
    uvicorn app.api.app:app --reload        # Swagger auf /docs

Ohne `DATABASE_URL` läuft es gegen SQLite (`./inventur.db`). Für PostgreSQL:

    export DATABASE_URL="postgresql+psycopg2://inventur:...@localhost/inventur"

## Tests

    pytest                                                    # SQLite, schnell
    TEST_DATABASE_URL="postgresql+psycopg2://inventur:...@localhost/inventur_test" pytest

Beide Läufe sind grün (61 Tests). Die Testfälle T1–T12 aus
`../samples/3_scan_testfaelle.xlsx` sind in `tests/test_scan_dienst.py` abgebildet.

## Aufbau

    app/domain/      EAN-Regeln und Aufzählungen, ohne DB- und API-Bezug
    app/quellen/     Grenze zum Vorsystem: heute Excel, später advarics-REST
    app/db/          Tabellen und Verbindung
    app/dienste/     Import, Scan-Auflösung, Auswertung, Export
    app/api/         FastAPI-Endpunkte und eigene Antwort-Schemas

Die gezählte Menge wird nie fortgeschrieben, sondern immer als Summe der
Scan-Events berechnet. Deshalb können mehrere Geräte gleichzeitig zählen,
und ein Storno ist eine Gegenbuchung statt einer Löschung.

## Offen

- Alembic-Migrationen (aktuell `create_all` beim Start)
- Authentifizierung
- PWA-Frontend

## Scan-Test mit dem Handy

    python scripts/testlauf.py

Startet den Server mit HTTPS und selbstsigniertem Zertifikat auf die LAN-Adresse.
Chrome gibt die Kamera nur in einem secure context frei — über `http://192.168.x.x`
bleibt sie schwarz. Deshalb der Zertifikatsumweg.

    Laptop   https://localhost:8443/test.html    Barcodes einzeln, mit → durchblättern
    Handy    https://<LAN-IP>:8443/              die App

Zertifikatswarnung auf dem Handy einmal über „Erweitert → Weiter" bestätigen.
