"""Anmeldung mit Name und PIN.

Die PIN schuetzt nicht gegen einen Angreifer im Netz - sie trennt
Zustaendigkeiten unter Kolleginnen, damit "Admin" nicht bloss ein Eintrag im
Menue ist. Trotzdem wird sie gehasht gespeichert: PINs werden wiederverwendet,
und eine gestohlene Datenbank soll keine fremden Zugaenge preisgeben.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tabellen import Benutzer, Sitzung
from app.domain.werte import Rolle

RUNDEN = 120_000
MIN_PIN = 4


class AnmeldeFehler(RuntimeError):
    pass


def hashe_pin(pin: str, salz: str | None = None) -> str:
    salz = salz or secrets.token_hex(16)
    abdruck = hashlib.pbkdf2_hmac("sha256", pin.encode(), salz.encode(), RUNDEN)
    return f"pbkdf2${RUNDEN}${salz}${abdruck.hex()}"


def pin_stimmt(pin: str, gespeichert: str) -> bool:
    try:
        _, runden, salz, abdruck = gespeichert.split("$")
        neu = hashlib.pbkdf2_hmac("sha256", pin.encode(), salz.encode(), int(runden))
    except (ValueError, TypeError):
        return False
    # Zeitkonstanter Vergleich, damit die Laufzeit nichts über die PIN verrät.
    return hmac.compare_digest(neu.hex(), abdruck)


def anzahl_benutzer(sitzung: Session) -> int:
    return int(sitzung.scalar(select(func.count(Benutzer.id))) or 0)


def lege_an(sitzung: Session, name: str, pin: str, rolle: Rolle) -> Benutzer:
    name = (name or "").strip()
    if not name:
        raise AnmeldeFehler("Name fehlt.")
    if len(pin or "") < MIN_PIN:
        raise AnmeldeFehler(f"Die PIN braucht mindestens {MIN_PIN} Zeichen.")

    vorhanden = sitzung.scalar(
        select(Benutzer).where(func.lower(Benutzer.name) == name.lower()))
    if vorhanden:
        raise AnmeldeFehler(f"„{name}“ gibt es schon.")

    benutzer = Benutzer(name=name, pin_hash=hashe_pin(pin), rolle=rolle.value)
    sitzung.add(benutzer)
    sitzung.commit()
    return benutzer


def melde_an(sitzung: Session, name: str, pin: str, geraet: str | None = None) -> Sitzung:
    benutzer = sitzung.scalar(
        select(Benutzer).where(func.lower(Benutzer.name) == (name or "").strip().lower()))

    # Bewusst dieselbe Meldung für "kein solcher Name" und "falsche PIN":
    # sonst liesse sich durchprobieren, wer überhaupt angelegt ist.
    if benutzer is None or not pin_stimmt(pin or "", benutzer.pin_hash):
        raise AnmeldeFehler("Name oder PIN stimmt nicht.")

    angemeldet = Sitzung(token=secrets.token_urlsafe(32), benutzer_id=benutzer.id,
                         geraet=(geraet or "")[:120] or None)
    sitzung.add(angemeldet)
    sitzung.commit()
    return angemeldet


def zu_token(sitzung: Session, token: str | None) -> Benutzer | None:
    if not token:
        return None
    eintrag = sitzung.get(Sitzung, token)
    return eintrag.benutzer if eintrag else None


def melde_ab(sitzung: Session, token: str) -> None:
    eintrag = sitzung.get(Sitzung, token)
    if eintrag:
        sitzung.delete(eintrag)
        sitzung.commit()


def auth_erforderlich() -> bool:
    """Abschaltbar für Tests und lokale Entwicklung."""
    return os.environ.get("INVENTUR_AUTH", "1") != "0"
