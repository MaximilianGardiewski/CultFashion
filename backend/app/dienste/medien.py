"""Bilder auf der Platte ablegen: Ladenskizze und Fotos je Bereich.

Bewusst als Dateien mit Pfad in der Datenbank, nicht als Blobs: Fotos aus dem
Laden sind schnell einige Megabyte gross, und eine Datenbank, die man noch
sichern und kopieren koennen muss, soll davon frei bleiben.
"""

from __future__ import annotations

import secrets
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent
MEDIEN = BACKEND / "uploads"

ERLAUBT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_BYTES = 12 * 1024 * 1024


class MedienFehler(RuntimeError):
    pass


def speichere(inhalt: bytes, mime: str | None, praefix: str) -> str:
    """Legt das Bild ab und gibt den Dateinamen zurueck."""
    endung = ERLAUBT.get((mime or "").lower())
    if endung is None:
        raise MedienFehler(
            "Nur JPEG, PNG oder WebP – bitte ein Foto statt einer anderen Datei.")
    if not inhalt:
        raise MedienFehler("Die Datei ist leer.")
    if len(inhalt) > MAX_BYTES:
        raise MedienFehler(
            f"Das Bild ist zu groß ({len(inhalt) // 1024 // 1024} MB, erlaubt sind "
            f"{MAX_BYTES // 1024 // 1024} MB).")

    MEDIEN.mkdir(exist_ok=True)
    name = f"{praefix}_{secrets.token_hex(8)}{endung}"
    (MEDIEN / name).write_bytes(inhalt)
    return name


def pfad(name: str) -> Path:
    """Pfad zu einem abgelegten Bild – schuetzt gegen Ausbrueche aus dem Ordner."""
    ziel = (MEDIEN / name).resolve()
    if not str(ziel).startswith(str(MEDIEN.resolve())):
        raise MedienFehler("Ungültiger Dateiname.")
    return ziel
