"""Sollbestand in eine Inventur laden."""

from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.tabellen import ImportProtokoll, Inventur, ScanEvent, Sollposition
from app.domain.werte import InventurStatus
from app.quellen.protokoll import BestandsQuelle, Ladeergebnis


class ImportGesperrt(RuntimeError):
    """Der Sollbestand darf nicht ausgetauscht werden, wenn schon gezaehlt wurde."""


def importiere(sitzung: Session, inventur: Inventur, quelle: BestandsQuelle,
               dateiname: str, ersetzen: bool = False) -> tuple[Ladeergebnis, ImportProtokoll]:
    bereits_gezaehlt = sitzung.scalar(
        select(ScanEvent.id).where(ScanEvent.inventur_id == inventur.id).limit(1))

    vorhanden = sitzung.scalar(
        select(Sollposition.id).where(Sollposition.inventur_id == inventur.id).limit(1))

    if vorhanden and not ersetzen:
        raise ImportGesperrt(
            "Für diese Inventur ist bereits ein Sollbestand importiert. "
            "Zum Überschreiben 'ersetzen' setzen.")

    if bereits_gezaehlt:
        # Sonst zeigen bestehende Scans ins Leere und die Zaehlung waere verloren.
        raise ImportGesperrt(
            "Es wurden bereits Artikel gezählt. Der Sollbestand kann nicht mehr "
            "ausgetauscht werden – dafür eine neue Inventur anlegen.")

    ergebnis = quelle.lade()

    if vorhanden:
        sitzung.execute(
            delete(Sollposition).where(Sollposition.inventur_id == inventur.id))

    sitzung.add_all([
        Sollposition(
            inventur_id=inventur.id,
            ean=p.ean,
            artikelnummer=p.artikelnummer,
            artikelname=p.artikelname,
            marke=p.marke,
            warengruppe=p.warengruppe,
            farbnummer=p.farbnummer,
            farbe=p.farbe,
            groesse=p.groesse,
            vk_preis=p.vk_preis,
            buchbestand=p.buchbestand,
            saison=p.saison,
        )
        for p in ergebnis.positionen
    ])

    protokoll = ImportProtokoll(
        inventur_id=inventur.id,
        dateiname=dateiname,
        zeilen_gelesen=ergebnis.zeilen_gelesen,
        zeilen_importiert=len(ergebnis.positionen),
        zeilen_uebersprungen=ergebnis.zeilen_uebersprungen,
        spaltenzuordnung=json.dumps(ergebnis.spaltenzuordnung, ensure_ascii=False),
        hinweise=json.dumps(ergebnis.hinweise[:200], ensure_ascii=False),
    )
    sitzung.add(protokoll)

    if ergebnis.positionen:
        inventur.status = InventurStatus.BEREIT.value

    sitzung.commit()
    return ergebnis, protokoll
