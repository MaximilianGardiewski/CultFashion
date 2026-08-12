"""Gescannten Code aufloesen und buchen.

Vier Ausgaenge, und alle vier muessen sauber unterschieden werden:
eindeutig, mehrdeutig, unbekannt, ungueltig. Der haeufigste Fehler in solchen
Apps ist, unbekannt und ungueltig in einen Topf zu werfen - dann verschwindet
ein falsch gedrucktes Etikett stumm in der Liste der Fremdartikel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tabellen import Inventur, ScanEvent, Sollposition
from app.domain.ean import ist_gueltig, normalisiere
from app.domain.werte import Erfassungsart, InventurStatus, ScanErgebnis


@dataclass(slots=True)
class ScanAntwort:
    ergebnis: ScanErgebnis
    meldung: str
    roh_code: str
    ean: str | None = None
    event_id: int | None = None
    position: Sollposition | None = None
    kandidaten: list[Sollposition] = field(default_factory=list)
    gezaehlt: int | None = None


class ScanFehler(RuntimeError):
    pass


def gezaehlte_menge(sitzung: Session, position_id: int) -> int:
    return int(sitzung.scalar(
        select(func.coalesce(func.sum(ScanEvent.menge), 0))
        .where(ScanEvent.sollposition_id == position_id)
    ) or 0)


def _markiere_laufend(sitzung: Session, inventur: Inventur) -> None:
    if inventur.status in (InventurStatus.ANGELEGT.value, InventurStatus.BEREIT.value):
        inventur.status = InventurStatus.LAEUFT.value
        sitzung.add(inventur)


def _buche(sitzung: Session, inventur: Inventur, position: Sollposition | None,
           roh_code: str | None, ean: str | None, menge: int,
           erfassungsart: Erfassungsart, erfasst_von: str,
           zaehlbereich_id: int | None, geraet: str | None) -> ScanEvent:
    event = ScanEvent(
        inventur_id=inventur.id,
        zaehlbereich_id=zaehlbereich_id,
        sollposition_id=position.id if position else None,
        roh_code=roh_code,
        ean=ean,
        menge=menge,
        erfassungsart=erfassungsart.value,
        erfasst_von=erfasst_von,
        geraet=geraet,
    )
    sitzung.add(event)
    _markiere_laufend(sitzung, inventur)
    sitzung.commit()
    return event


def scanne(sitzung: Session, inventur: Inventur, roh_code: str, *,
           erfasst_von: str = "unbekannt", zaehlbereich_id: int | None = None,
           geraet: str | None = None, menge: int = 1) -> ScanAntwort:
    roh_code = (roh_code or "").strip()
    ean = normalisiere(roh_code)

    if not ean or not ist_gueltig(ean):
        # Bewusst kein Event: ein Lesefehler ist keine Zaehlung. Der Nutzer
        # bekommt ein Fehlsignal und scannt neu.
        return ScanAntwort(
            ergebnis=ScanErgebnis.UNGUELTIG,
            meldung="Code ungültig – bitte erneut scannen.",
            roh_code=roh_code,
            ean=ean,
        )

    treffer = list(sitzung.scalars(
        select(Sollposition)
        .where(Sollposition.inventur_id == inventur.id, Sollposition.ean == ean)
        .order_by(Sollposition.farbnummer, Sollposition.groesse)
    ))

    if not treffer:
        event = _buche(sitzung, inventur, None, roh_code, ean, menge,
                       Erfassungsart.SCAN, erfasst_von, zaehlbereich_id, geraet)
        return ScanAntwort(
            ergebnis=ScanErgebnis.UNBEKANNT,
            meldung="Artikel nicht im Sollbestand – als unbekannt erfasst.",
            roh_code=roh_code, ean=ean, event_id=event.id,
        )

    if len(treffer) > 1:
        # Noch nichts buchen: erst muss klar sein, welcher Artikel gemeint ist.
        return ScanAntwort(
            ergebnis=ScanErgebnis.MEHRDEUTIG,
            meldung=f"{len(treffer)} Artikel teilen diese EAN – bitte auswählen.",
            roh_code=roh_code, ean=ean, kandidaten=treffer,
        )

    position = treffer[0]
    event = _buche(sitzung, inventur, position, roh_code, ean, menge,
                   Erfassungsart.SCAN, erfasst_von, zaehlbereich_id, geraet)
    return ScanAntwort(
        ergebnis=ScanErgebnis.EINDEUTIG,
        meldung=position.bezeichnung,
        roh_code=roh_code, ean=ean, event_id=event.id, position=position,
        gezaehlt=gezaehlte_menge(sitzung, position.id),
    )


def buche_position(sitzung: Session, inventur: Inventur, position_id: int, *,
                   menge: int = 1, erfassungsart: Erfassungsart = Erfassungsart.AUSWAHL,
                   erfasst_von: str = "unbekannt", zaehlbereich_id: int | None = None,
                   geraet: str | None = None, roh_code: str | None = None) -> ScanAntwort:
    """Direkte Buchung: nach mehrdeutigem Scan oder aus der Suche (Artikel ohne EAN)."""
    position = sitzung.get(Sollposition, position_id)
    if position is None or position.inventur_id != inventur.id:
        raise ScanFehler("Artikel gehört nicht zu dieser Inventur.")

    event = _buche(sitzung, inventur, position, roh_code, position.ean, menge,
                   erfassungsart, erfasst_von, zaehlbereich_id, geraet)
    return ScanAntwort(
        ergebnis=ScanErgebnis.EINDEUTIG,
        meldung=position.bezeichnung,
        roh_code=roh_code or "", ean=position.ean, event_id=event.id,
        position=position, gezaehlt=gezaehlte_menge(sitzung, position.id),
    )


def storniere(sitzung: Session, inventur: Inventur, event_id: int,
              erfasst_von: str = "unbekannt") -> ScanAntwort:
    """Gegenbuchung. Loescht nichts - das Log bleibt vollstaendig."""
    original = sitzung.get(ScanEvent, event_id)
    if original is None or original.inventur_id != inventur.id:
        raise ScanFehler("Scan gehört nicht zu dieser Inventur.")
    if original.erfassungsart == Erfassungsart.STORNO.value:
        raise ScanFehler("Eine Stornobuchung kann nicht storniert werden.")

    schon_storniert = sitzung.scalar(
        select(ScanEvent.id).where(ScanEvent.storniert_event_id == original.id).limit(1))
    if schon_storniert:
        raise ScanFehler("Dieser Scan wurde bereits storniert.")

    gegen = ScanEvent(
        inventur_id=inventur.id,
        zaehlbereich_id=original.zaehlbereich_id,
        sollposition_id=original.sollposition_id,
        roh_code=original.roh_code,
        ean=original.ean,
        menge=-original.menge,
        erfassungsart=Erfassungsart.STORNO.value,
        erfasst_von=erfasst_von,
        geraet=original.geraet,
        storniert_event_id=original.id,
    )
    sitzung.add(gegen)
    sitzung.commit()

    return ScanAntwort(
        ergebnis=ScanErgebnis.EINDEUTIG,
        meldung="Storniert.",
        roh_code=original.roh_code or "",
        ean=original.ean,
        event_id=gegen.id,
        position=original.position,
        gezaehlt=(gezaehlte_menge(sitzung, original.sollposition_id)
                  if original.sollposition_id else None),
    )


def suche(sitzung: Session, inventur: Inventur, text: str, grenze: int = 30
          ) -> list[Sollposition]:
    """Fuer Artikel ohne Etikett: nach Nummer, Name, Marke oder Farbe suchen."""
    text = (text or "").strip()
    if len(text) < 2:
        return []

    muster = f"%{text.lower()}%"
    return list(sitzung.scalars(
        select(Sollposition)
        .where(
            Sollposition.inventur_id == inventur.id,
            func.lower(Sollposition.artikelnummer).like(muster)
            | func.lower(Sollposition.artikelname).like(muster)
            | func.lower(Sollposition.marke).like(muster)
            | func.lower(Sollposition.farbe).like(muster),
        )
        .order_by(Sollposition.marke, Sollposition.artikelname,
                  Sollposition.farbnummer, Sollposition.groesse)
        .limit(grenze)
    ))
