"""Startet die Inventur-App fuer einen Scan-Test mit dem Handy.

Warum ueberhaupt HTTPS: Chrome gibt die Kamera nur in einem "secure context"
frei - also HTTPS oder localhost. Ueber http://192.168.x.x bleibt die Kamera
schwarz, ohne dass die Seite etwas dagegen tun koennte. Deshalb erzeugt dieses
Skript ein selbstsigniertes Zertifikat auf die LAN-Adresse des Rechners und
startet uvicorn damit.

Aufruf aus dem Projektverzeichnis:

    python scripts/testlauf.py

Dann:
  Laptop  ->  https://localhost:8443/test.html      Barcodes zum Abscannen
  Handy   ->  https://<LAN-IP>:8443/                die App

Die Zertifikatswarnung auf dem Handy einmal ueber "Erweitert -> Weiter"
bestaetigen. Danach ist die Herkunft fuer Chrome sicher und die Kamera geht.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

BASIS = Path(__file__).resolve().parent.parent
BACKEND = BASIS / "backend"
ZERT_ORDNER = BACKEND / ".certs"
ZERT = ZERT_ORDNER / "cert.pem"
SCHLUESSEL = ZERT_ORDNER / "key.pem"
PORT = 8443


def lan_adresse() -> str:
    """Die IP, unter der der Rechner im WLAN erreichbar ist."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Es wird nichts gesendet - der Kernel waehlt nur die passende Route.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def erzeuge_zertifikat(ip: str) -> bool:
    if ZERT.exists() and SCHLUESSEL.exists():
        if ip in ZERT.read_text(errors="ignore") or _ip_im_zertifikat(ip):
            return True
        print("· Zertifikat passt nicht mehr zur aktuellen IP – wird neu erzeugt.")

    if not shutil.which("openssl"):
        print("FEHLER: openssl nicht gefunden. Bitte installieren – ohne "
              "Zertifikat gibt Chrome die Kamera nicht frei.")
        return False

    ZERT_ORDNER.mkdir(exist_ok=True)
    (ZERT_ORDNER / ".gitignore").write_text("*\n")

    befehl = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(SCHLUESSEL), "-out", str(ZERT),
        "-days", "365", "-subj", "/CN=Inventur Testserver",
        "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost",
    ]
    ergebnis = subprocess.run(befehl, capture_output=True, text=True)
    if ergebnis.returncode != 0:
        print("FEHLER beim Erzeugen des Zertifikats:\n" + ergebnis.stderr)
        return False

    print(f"· Zertifikat für {ip} erzeugt (365 Tage, nur für Tests).")
    return True


def _ip_im_zertifikat(ip: str) -> bool:
    if not shutil.which("openssl"):
        return False
    ergebnis = subprocess.run(
        ["openssl", "x509", "-in", str(ZERT), "-noout", "-text"],
        capture_output=True, text=True)
    return f"IP Address:{ip}" in ergebnis.stdout


def main() -> None:
    ip = lan_adresse()
    print()
    print("  Inventur – Scan-Testlauf")
    print("  " + "─" * 52)

    if not erzeuge_zertifikat(ip):
        sys.exit(1)

    print()
    print(f"  Laptop   https://localhost:{PORT}/test.html")
    print("           Barcodes einzeln anzeigen, mit → durchblättern")
    print()
    print(f"  Handy    https://{ip}:{PORT}/")
    print("           gleiches WLAN · Zertifikatswarnung mit")
    print("           „Erweitert → Weiter“ bestätigen")
    print()
    print("  Ablauf   Setup → Neue Inventur → samples/1_sollbestand_referenz.xlsx")
    print("           hochladen → Zählbereich anlegen → Kamera starten")
    print()
    print("  Ohne HTTPS bleibt die Kamera schwarz – Chrome gibt sie nur in")
    print("  einem secure context frei. Deshalb der Zertifikatsumweg.")
    print("  " + "─" * 52)
    print()

    os.chdir(BACKEND)
    os.execvp("uvicorn", [
        "uvicorn", "app.api.app:app",
        "--host", "0.0.0.0", "--port", str(PORT),
        "--ssl-keyfile", str(SCHLUESSEL), "--ssl-certfile", str(ZERT),
    ])


if __name__ == "__main__":
    main()
