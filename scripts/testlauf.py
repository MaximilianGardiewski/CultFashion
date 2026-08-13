"""Startet die Inventur-App fuer einen Scan-Test mit dem Handy.

Warum ueberhaupt HTTPS: Chrome gibt die Kamera nur in einem "secure context"
frei - also HTTPS oder localhost. Ueber http://192.168.x.x bleibt die Kamera
schwarz, ohne dass die Seite etwas dagegen tun koennte. Deshalb erzeugt dieses
Skript ein selbstsigniertes Zertifikat auf die LAN-Adresse des Rechners und
startet uvicorn damit.

Das Zertifikat wird mit der Python-Bibliothek cryptography erzeugt, nicht mit
dem openssl-Kommando - unter Windows ist openssl normalerweise nicht
installiert.

Aufruf aus dem Projektverzeichnis:

    python scripts/testlauf.py

Dann:
  Laptop  ->  https://localhost:8443/test.html      Barcodes zum Abscannen
  Handy   ->  https://<LAN-IP>:8443/                die App

Die Zertifikatswarnung auf dem Handy einmal ueber "Erweitert -> Weiter"
bestaetigen. Danach ist die Herkunft fuer Chrome sicher und die Kamera geht.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import socket
import sys
from pathlib import Path

BASIS = Path(__file__).resolve().parent.parent
BACKEND = BASIS / "backend"
ZERT_ORDNER = BACKEND / ".certs"
ZERT = ZERT_ORDNER / "cert.pem"
SCHLUESSEL = ZERT_ORDNER / "key.pem"
NOTIZ = ZERT_ORDNER / "adresse.txt"
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


def zertifikat_vorhanden(ip: str) -> bool:
    return (ZERT.exists() and SCHLUESSEL.exists() and NOTIZ.exists()
            and NOTIZ.read_text(encoding="utf-8").strip() == ip)


def erzeuge_zertifikat(ip: str) -> bool:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("FEHLER: Paket 'cryptography' fehlt.")
        print("        pip install -r backend/requirements.txt")
        return False

    ZERT_ORDNER.mkdir(exist_ok=True)
    (ZERT_ORDNER / ".gitignore").write_text("*\n", encoding="utf-8")

    schluessel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Inventur Testserver"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Cult Fashion (nur Tests)"),
    ])

    alternativen = [x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    try:
        adresse = ipaddress.ip_address(ip)
        if adresse != ipaddress.ip_address("127.0.0.1"):
            alternativen.append(x509.IPAddress(adresse))
    except ValueError:
        pass

    jetzt = datetime.datetime.now(datetime.timezone.utc)
    zertifikat = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(schluessel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(jetzt - datetime.timedelta(days=1))
        .not_valid_after(jetzt + datetime.timedelta(days=365))
        # Chrome prueft ausschliesslich den SubjectAltName, nicht den CN.
        # Fehlt die IP hier, wird die Seite auch mit HTTPS abgelehnt.
        .add_extension(x509.SubjectAlternativeName(alternativen), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(schluessel, hashes.SHA256())
    )

    ZERT.write_bytes(zertifikat.public_bytes(serialization.Encoding.PEM))
    SCHLUESSEL.write_bytes(schluessel.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    NOTIZ.write_text(ip, encoding="utf-8")

    print(f"· Zertifikat für {ip} erzeugt (365 Tage, nur für Tests).")
    return True


def main() -> None:
    ip = lan_adresse()

    print()
    print("  Inventur – Scan-Testlauf")
    print("  " + "-" * 52)

    if not zertifikat_vorhanden(ip) and not erzeuge_zertifikat(ip):
        sys.exit(1)

    print()
    print(f"  Laptop   https://localhost:{PORT}/test.html")
    print("           Barcodes einzeln anzeigen, mit -> durchblättern")
    print()
    print(f"  Handy    https://{ip}:{PORT}/")
    print("           gleiches WLAN · Zertifikatswarnung mit")
    print("           „Erweitert -> Weiter“ bestätigen")
    print()
    if ip == "127.0.0.1":
        print("  ACHTUNG  Keine Netzwerkadresse gefunden – das Handy kann sich")
        print("           so nicht verbinden. WLAN prüfen.")
        print()
    print("  Ablauf   Setup -> Neue Inventur -> Excel hochladen")
    print("           (samples/1_sollbestand_referenz.xlsx, am einfachsten")
    print("           am Laptop) -> Zählbereich anlegen -> Kamera starten")
    print()
    print("  Ohne HTTPS bleibt die Kamera schwarz – Chrome gibt sie nur in")
    print("  einem secure context frei. Deshalb der Zertifikatsumweg.")
    print("  " + "-" * 52)
    print()

    # Windows kennt kein brauchbares execvp, deshalb uvicorn direkt aufrufen.
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    import uvicorn

    uvicorn.run(
        "app.api.app:app",
        host="0.0.0.0",
        port=PORT,
        ssl_keyfile=str(SCHLUESSEL),
        ssl_certfile=str(ZERT),
    )


if __name__ == "__main__":
    main()
