"""Wer darf was.

Zwei Rollen: Zaehler und Admin. Der Unterschied ist bewusst eng gefasst -
Zaehler zaehlen und melden Klaerfaelle, Admins loesen sie auf, richten die
Inventur ein und korrigieren Buchungen.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.sitzung import hole_sitzung
from app.db.tabellen import Benutzer
from app.dienste import benutzer_dienst
from app.domain.werte import Rolle

# Ein Notbenutzer für abgeschaltete Anmeldung (Tests, lokale Entwicklung).
# Er wird nie gespeichert und existiert nur im Speicher.
NOTBENUTZER = Benutzer(id=0, name="ohne Anmeldung", pin_hash="",
                       rolle=Rolle.ADMIN.value)


def aktueller_benutzer(
    x_token: str | None = Header(default=None, alias="X-Token"),
    sitzung: Session = Depends(hole_sitzung),
) -> Benutzer:
    if not benutzer_dienst.auth_erforderlich():
        return NOTBENUTZER

    benutzer = benutzer_dienst.zu_token(sitzung, x_token)
    if benutzer is None:
        raise HTTPException(401, "Nicht angemeldet.")
    return benutzer


def admin_pflicht(benutzer: Benutzer = Depends(aktueller_benutzer)) -> Benutzer:
    if benutzer.rolle != Rolle.ADMIN.value:
        raise HTTPException(
            403, "Das darf nur eine Administratorin. Bitte markieren statt ändern.")
    return benutzer


def ist_admin(benutzer: Benutzer) -> bool:
    return benutzer.rolle == Rolle.ADMIN.value
