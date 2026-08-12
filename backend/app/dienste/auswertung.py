"""Differenzen aus dem Scan-Log ableiten.

Es wird nichts fortgeschrieben: die gezaehlte Menge ist immer die Summe der
Events. Dieselbe Auswertung zweimal aufgerufen liefert dasselbe Ergebnis,
und ein nachtraeglich eingetroffener Scan aendert sie automatisch mit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tabellen import Inventur, ScanEvent, Sollposition


@dataclass(slots=True)
class Differenz:
    position: Sollposition
    buchbestand: int
    gezaehlt: int

    @property
    def differenz(self) -> int:
        return self.gezaehlt - self.buchbestand

    @property
    def wert(self) -> float:
        return round(self.differenz * float(self.position.vk_preis or 0), 2)


@dataclass(slots=True)
class UnbekannterCode:
    ean: str | None
    roh_code: str | None
    menge: int


@dataclass(slots=True)
class Kennzahlen:
    positionen_gesamt: int = 0
    positionen_gezaehlt: int = 0
    scans_gesamt: int = 0
    buchbestand_gesamt: int = 0
    gezaehlt_gesamt: int = 0
    fehlmenge: int = 0          # Summe der negativen Abweichungen (Schwund)
    ueberbestand: int = 0       # Summe der positiven Abweichungen
    differenz_wert: float = 0.0
    unbekannte_teile: int = 0


@dataclass(slots=True)
class Auswertung:
    kennzahlen: Kennzahlen = field(default_factory=Kennzahlen)
    differenzen: list[Differenz] = field(default_factory=list)
    unbekannte: list[UnbekannterCode] = field(default_factory=list)


def _mengen_je_position(sitzung: Session, inventur_id: int) -> dict[int, int]:
    zeilen = sitzung.execute(
        select(ScanEvent.sollposition_id, func.sum(ScanEvent.menge))
        .where(ScanEvent.inventur_id == inventur_id,
               ScanEvent.sollposition_id.is_not(None))
        .group_by(ScanEvent.sollposition_id)
    ).all()
    return {pid: int(menge or 0) for pid, menge in zeilen}


def erstelle(sitzung: Session, inventur: Inventur, nur_abweichungen: bool = True
             ) -> Auswertung:
    positionen = list(sitzung.scalars(
        select(Sollposition)
        .where(Sollposition.inventur_id == inventur.id)
        .order_by(Sollposition.marke, Sollposition.artikelname,
                  Sollposition.farbnummer, Sollposition.groesse)
    ))
    mengen = _mengen_je_position(sitzung, inventur.id)

    auswertung = Auswertung()
    k = auswertung.kennzahlen
    k.positionen_gesamt = len(positionen)

    for position in positionen:
        gezaehlt = mengen.get(position.id, 0)
        d = Differenz(position=position, buchbestand=position.buchbestand,
                      gezaehlt=gezaehlt)

        k.buchbestand_gesamt += position.buchbestand
        k.gezaehlt_gesamt += gezaehlt
        if position.id in mengen:
            k.positionen_gezaehlt += 1

        if d.differenz < 0:
            k.fehlmenge += -d.differenz
        elif d.differenz > 0:
            k.ueberbestand += d.differenz
        k.differenz_wert += d.wert

        if not nur_abweichungen or d.differenz != 0:
            auswertung.differenzen.append(d)

    auswertung.differenzen.sort(key=lambda d: (d.wert, d.differenz))
    k.differenz_wert = round(k.differenz_wert, 2)

    unbekannt = sitzung.execute(
        select(ScanEvent.ean, func.min(ScanEvent.roh_code), func.sum(ScanEvent.menge))
        .where(ScanEvent.inventur_id == inventur.id,
               ScanEvent.sollposition_id.is_(None))
        .group_by(ScanEvent.ean)
        .order_by(func.sum(ScanEvent.menge).desc())
    ).all()
    auswertung.unbekannte = [
        UnbekannterCode(ean=ean, roh_code=roh, menge=int(menge or 0))
        for ean, roh, menge in unbekannt if (menge or 0) != 0
    ]
    k.unbekannte_teile = sum(u.menge for u in auswertung.unbekannte)

    k.scans_gesamt = int(sitzung.scalar(
        select(func.count(ScanEvent.id))
        .where(ScanEvent.inventur_id == inventur.id)) or 0)

    return auswertung
