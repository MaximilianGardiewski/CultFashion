"""Zonen der Ladenskizze: Bereiche, Ständer, Vorzählung und Fortschritt.

Der Zweck der Vorzaehlung ist Vollstaendigkeit, nicht Genauigkeit. Ohne sie
sieht ein vergessener Staender in der Auswertung exakt aus wie Schwund - mit
ihr steht dort "47 von 62 erfasst" und jemand geht nochmal hin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tabellen import Inventur, ScanEvent, Zaehlbereich
from app.domain.werte import BereichStatus, Ebene


class BereichFehler(RuntimeError):
    pass


@dataclass(slots=True)
class Fortschritt:
    bereich: Zaehlbereich
    gezaehlt: int
    soll_teile: int | None
    kinder: list["Fortschritt"] = field(default_factory=list)

    @property
    def offen(self) -> int | None:
        if self.soll_teile is None:
            return None
        return max(0, self.soll_teile - self.gezaehlt)

    @property
    def anteil(self) -> float | None:
        """0..1 – None, wenn nicht vorgezählt wurde."""
        if not self.soll_teile:
            return None
        return min(1.0, self.gezaehlt / self.soll_teile)


def _mengen(sitzung: Session, inventur_id: int) -> dict[int, int]:
    zeilen = sitzung.execute(
        select(ScanEvent.zaehlbereich_id, func.sum(ScanEvent.menge))
        .where(ScanEvent.inventur_id == inventur_id,
               ScanEvent.zaehlbereich_id.is_not(None))
        .group_by(ScanEvent.zaehlbereich_id)
    ).all()
    return {bid: int(menge or 0) for bid, menge in zeilen}


def baum(sitzung: Session, inventur: Inventur) -> list[Fortschritt]:
    """Bereiche mit ihren Ständern, jeweils mit gezählter Menge."""
    alle = list(sitzung.scalars(
        select(Zaehlbereich)
        .where(Zaehlbereich.inventur_id == inventur.id)
        .order_by(Zaehlbereich.name)
    ))
    mengen = _mengen(sitzung, inventur.id)

    knoten = {
        b.id: Fortschritt(bereich=b, gezaehlt=mengen.get(b.id, 0),
                          soll_teile=b.soll_teile)
        for b in alle
    }

    wurzeln: list[Fortschritt] = []
    for b in alle:
        if b.eltern_id and b.eltern_id in knoten:
            knoten[b.eltern_id].kinder.append(knoten[b.id])
        else:
            wurzeln.append(knoten[b.id])

    # Ein Bereich erbt Menge und Vorzählung seiner Ständer, falls er selbst
    # keine hat - sonst müsste dieselbe Zahl zweimal gepflegt werden.
    for wurzel in wurzeln:
        if wurzel.kinder:
            wurzel.gezaehlt += sum(k.gezaehlt for k in wurzel.kinder)
            teilsummen = [k.soll_teile for k in wurzel.kinder if k.soll_teile is not None]
            if wurzel.soll_teile is None and teilsummen:
                wurzel.soll_teile = sum(teilsummen)

    return wurzeln


def lege_an(sitzung: Session, inventur: Inventur, name: str, *,
            eltern_id: int | None = None, ebene: Ebene = Ebene.STAENDER,
            soll_teile: int | None = None, karte_x: float | None = None,
            karte_y: float | None = None, notiz: str | None = None) -> Zaehlbereich:
    name = (name or "").strip()
    if not name:
        raise BereichFehler("Name fehlt.")

    vorhanden = sitzung.scalar(
        select(Zaehlbereich).where(Zaehlbereich.inventur_id == inventur.id,
                                   Zaehlbereich.name == name))
    if vorhanden:
        raise BereichFehler(f"„{name}“ gibt es in dieser Inventur schon.")

    if eltern_id is not None:
        eltern = sitzung.get(Zaehlbereich, eltern_id)
        if eltern is None or eltern.inventur_id != inventur.id:
            raise BereichFehler("Der übergeordnete Bereich gehört nicht zu dieser Inventur.")
        if eltern.ebene != Ebene.BEREICH.value:
            raise BereichFehler("Ständer können nur unter einem Bereich liegen.")

    if soll_teile is not None and soll_teile < 0:
        raise BereichFehler("Die Vorzählung kann nicht negativ sein.")

    bereich = Zaehlbereich(
        inventur_id=inventur.id, eltern_id=eltern_id, name=name, ebene=ebene.value,
        soll_teile=soll_teile, karte_x=karte_x, karte_y=karte_y, notiz=notiz,
        status=BereichStatus.OFFEN.value,
    )
    sitzung.add(bereich)
    sitzung.commit()
    return bereich


def aendere(sitzung: Session, inventur: Inventur, bereich_id: int, **felder) -> Zaehlbereich:
    bereich = sitzung.get(Zaehlbereich, bereich_id)
    if bereich is None or bereich.inventur_id != inventur.id:
        raise BereichFehler("Bereich gehört nicht zu dieser Inventur.")

    for feld in ("name", "soll_teile", "karte_x", "karte_y", "notiz", "bild_pfad"):
        if feld in felder and felder[feld] is not None:
            setattr(bereich, feld, felder[feld])

    sitzung.commit()
    return bereich


def setze_status(sitzung: Session, inventur: Inventur, bereich_id: int,
                 status: BereichStatus, bearbeiter: str | None) -> Zaehlbereich:
    """Wer einen Bereich übernimmt, trägt sich ein – damit auf der Karte
    sichtbar ist, dass dort schon jemand zählt."""
    bereich = sitzung.get(Zaehlbereich, bereich_id)
    if bereich is None or bereich.inventur_id != inventur.id:
        raise BereichFehler("Bereich gehört nicht zu dieser Inventur.")

    if (status is BereichStatus.LAEUFT
            and bereich.status == BereichStatus.LAEUFT.value
            and bereich.zugewiesen_an
            and bereich.zugewiesen_an != bearbeiter):
        raise BereichFehler(
            f"„{bereich.name}“ wird gerade von {bereich.zugewiesen_an} gezählt.")

    bereich.status = status.value
    if status is BereichStatus.LAEUFT:
        bereich.zugewiesen_an = bearbeiter
        bereich.begonnen_am = bereich.begonnen_am or datetime.now()
        bereich.fertig_am = None
    elif status is BereichStatus.FERTIG:
        bereich.fertig_am = datetime.now()
    else:
        bereich.zugewiesen_an = None
        bereich.begonnen_am = None
        bereich.fertig_am = None

    sitzung.commit()
    return bereich
