"""Klärfälle: was eine Zählerin meldet, statt selbst zu korrigieren.

Eine Markierung ändert die Zählung nicht. Sie hält fest, dass an einer Stelle
etwas nicht stimmt, wer das gesehen hat und wie eilig es ist - und bleibt
stehen, bis eine Administratorin sie auflöst. Dadurch bleibt die Zählung eine
Beobachtung und wird nicht unterwegs von jemandem umgeschrieben.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tabellen import Inventur, Markierung, ScanEvent, Sollposition, Zaehlbereich
from app.domain.werte import Dringlichkeit, MarkierungStatus


class MarkierungFehler(RuntimeError):
    pass


def melde(sitzung: Session, inventur: Inventur, *, grund: str,
          dringlichkeit: int, gemeldet_von: str,
          zaehlbereich_id: int | None = None, scan_event_id: int | None = None,
          sollposition_id: int | None = None) -> Markierung:
    grund = (grund or "").strip()
    if len(grund) < 3:
        # Eine Markierung ohne Begründung ist für den Admin wertlos - er sieht
        # dann nur, dass irgendwo etwas war.
        raise MarkierungFehler("Bitte kurz angeben, worum es geht.")

    if dringlichkeit not in (d.value for d in Dringlichkeit):
        raise MarkierungFehler("Dringlichkeit muss 1, 2 oder 3 sein.")

    for wert, klasse, bezeichnung in (
        (zaehlbereich_id, Zaehlbereich, "Bereich"),
        (scan_event_id, ScanEvent, "Scan"),
        (sollposition_id, Sollposition, "Artikel"),
    ):
        if wert is None:
            continue
        eintrag = sitzung.get(klasse, wert)
        if eintrag is None or eintrag.inventur_id != inventur.id:
            raise MarkierungFehler(f"{bezeichnung} gehört nicht zu dieser Inventur.")

    markierung = Markierung(
        inventur_id=inventur.id, zaehlbereich_id=zaehlbereich_id,
        scan_event_id=scan_event_id, sollposition_id=sollposition_id,
        grund=grund, dringlichkeit=dringlichkeit, gemeldet_von=gemeldet_von,
        status=MarkierungStatus.OFFEN.value,
    )
    sitzung.add(markierung)
    sitzung.commit()
    return markierung


def liste(sitzung: Session, inventur: Inventur, nur_offene: bool = True
          ) -> list[Markierung]:
    abfrage = select(Markierung).where(Markierung.inventur_id == inventur.id)
    if nur_offene:
        abfrage = abfrage.where(Markierung.status == MarkierungStatus.OFFEN.value)
    # Dringendstes zuerst, danach das Älteste - so arbeitet man eine Liste ab.
    return list(sitzung.scalars(
        abfrage.order_by(Markierung.dringlichkeit.desc(), Markierung.id)))


def offene_anzahl(sitzung: Session, inventur: Inventur) -> dict[str, int]:
    zeilen = sitzung.execute(
        select(Markierung.dringlichkeit, func.count(Markierung.id))
        .where(Markierung.inventur_id == inventur.id,
               Markierung.status == MarkierungStatus.OFFEN.value)
        .group_by(Markierung.dringlichkeit)
    ).all()
    nach_stufe = {int(stufe): int(anzahl) for stufe, anzahl in zeilen}
    return {
        "gesamt": sum(nach_stufe.values()),
        "sofort": nach_stufe.get(Dringlichkeit.SOFORT.value, 0),
        "bald": nach_stufe.get(Dringlichkeit.BALD.value, 0),
        "spaeter": nach_stufe.get(Dringlichkeit.SPAETER.value, 0),
    }


def erledige(sitzung: Session, inventur: Inventur, markierung_id: int,
             erledigt_von: str, antwort: str | None = None) -> Markierung:
    markierung = sitzung.get(Markierung, markierung_id)
    if markierung is None or markierung.inventur_id != inventur.id:
        raise MarkierungFehler("Markierung gehört nicht zu dieser Inventur.")
    if markierung.status == MarkierungStatus.ERLEDIGT.value:
        raise MarkierungFehler("Diese Markierung ist bereits erledigt.")

    markierung.status = MarkierungStatus.ERLEDIGT.value
    markierung.erledigt_von = erledigt_von
    markierung.erledigt_am = datetime.now()
    markierung.antwort = (antwort or "").strip() or None
    sitzung.commit()
    return markierung
