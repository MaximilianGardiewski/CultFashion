"""REST-Endpunkte der Inventur-App."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas as s
from app.db.sitzung import hole_sitzung
from app.db.tabellen import Inventur, ScanEvent, Sollposition, Zaehlbereich
from app.dienste import auswertung as auswertung_modul
from app.dienste import export as export_modul
from app.dienste import scan_dienst
from app.dienste.import_dienst import ImportGesperrt, importiere
from app.domain.werte import BereichStatus, Erfassungsart, InventurStatus
from app.quellen.excel import ExcelBestandsQuelle

router = APIRouter(prefix="/api")


def _inventur(sitzung: Session, inventur_id: int) -> Inventur:
    inventur = sitzung.get(Inventur, inventur_id)
    if inventur is None:
        raise HTTPException(404, "Inventur nicht gefunden.")
    return inventur


def _positionen_anzahl(sitzung: Session, inventur_id: int) -> int:
    return int(sitzung.scalar(
        select(func.count(Sollposition.id))
        .where(Sollposition.inventur_id == inventur_id)) or 0)


# -- Inventuren ----------------------------------------------------------

@router.post("/inventuren", response_model=s.InventurAus, status_code=201)
def lege_inventur_an(daten: s.InventurAn, sitzung: Session = Depends(hole_sitzung)):
    inventur = Inventur(filial_nr=daten.filial_nr, filiale=daten.filiale,
                        bezeichnung=daten.bezeichnung,
                        status=InventurStatus.ANGELEGT.value)
    sitzung.add(inventur)
    sitzung.commit()
    return s.InventurAus.aus(inventur)


@router.get("/inventuren", response_model=list[s.InventurAus])
def liste_inventuren(sitzung: Session = Depends(hole_sitzung)):
    inventuren = list(sitzung.scalars(
        select(Inventur).order_by(Inventur.id.desc())))
    return [s.InventurAus.aus(i, _positionen_anzahl(sitzung, i.id)) for i in inventuren]


@router.get("/inventuren/{inventur_id}", response_model=s.InventurAus)
def hole_inventur(inventur_id: int, sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    return s.InventurAus.aus(inventur, _positionen_anzahl(sitzung, inventur.id))


@router.post("/inventuren/{inventur_id}/abschluss", response_model=s.InventurAus)
def schliesse_ab(inventur_id: int, sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    inventur.status = InventurStatus.ABGESCHLOSSEN.value
    inventur.abgeschlossen_am = datetime.now()
    sitzung.commit()
    return s.InventurAus.aus(inventur, _positionen_anzahl(sitzung, inventur.id))


# -- Import --------------------------------------------------------------

@router.post("/inventuren/{inventur_id}/import", response_model=s.ImportAus)
async def importiere_sollbestand(
    inventur_id: int,
    datei: UploadFile = File(...),
    ersetzen: bool = Query(False),
    blatt: str | None = Query(None),
    sitzung: Session = Depends(hole_sitzung),
):
    inventur = _inventur(sitzung, inventur_id)
    name = datei.filename or "upload.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Bitte eine Excel-Datei (.xlsx) hochladen.")

    inhalt = await datei.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(inhalt)
        pfad = Path(tmp.name)

    try:
        quelle = ExcelBestandsQuelle(pfad, blatt=blatt)
        ergebnis, _ = importiere(sitzung, inventur, quelle, name, ersetzen=ersetzen)
    except ImportGesperrt as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    except ValueError as fehler:
        raise HTTPException(422, str(fehler)) from fehler
    finally:
        pfad.unlink(missing_ok=True)

    return s.ImportAus(
        zeilen_gelesen=ergebnis.zeilen_gelesen,
        zeilen_importiert=len(ergebnis.positionen),
        zeilen_uebersprungen=ergebnis.zeilen_uebersprungen,
        spaltenzuordnung={k: str(v) for k, v in ergebnis.spaltenzuordnung.items()},
        hinweise=ergebnis.hinweise[:100],
    )


# -- Zaehlbereiche -------------------------------------------------------

@router.post("/inventuren/{inventur_id}/bereiche", response_model=s.BereichAus,
             status_code=201)
def lege_bereich_an(inventur_id: int, daten: s.BereichAn,
                    sitzung: Session = Depends(hole_sitzung)):
    _inventur(sitzung, inventur_id)
    vorhanden = sitzung.scalar(
        select(Zaehlbereich).where(Zaehlbereich.inventur_id == inventur_id,
                                   Zaehlbereich.name == daten.name))
    if vorhanden:
        raise HTTPException(409, f"Zählbereich '{daten.name}' gibt es schon.")

    bereich = Zaehlbereich(inventur_id=inventur_id, name=daten.name,
                           zugewiesen_an=daten.zugewiesen_an,
                           status=BereichStatus.OFFEN.value)
    sitzung.add(bereich)
    sitzung.commit()
    return s.BereichAus(id=bereich.id, name=bereich.name,
                        zugewiesen_an=bereich.zugewiesen_an, status=bereich.status)


@router.get("/inventuren/{inventur_id}/bereiche", response_model=list[s.BereichAus])
def liste_bereiche(inventur_id: int, sitzung: Session = Depends(hole_sitzung)):
    _inventur(sitzung, inventur_id)
    bereiche = list(sitzung.scalars(
        select(Zaehlbereich).where(Zaehlbereich.inventur_id == inventur_id)
        .order_by(Zaehlbereich.name)))

    zahlen = {
        bid: (int(anzahl or 0), int(teile or 0))
        for bid, anzahl, teile in sitzung.execute(
            select(ScanEvent.zaehlbereich_id, func.count(ScanEvent.id),
                   func.sum(ScanEvent.menge))
            .where(ScanEvent.inventur_id == inventur_id)
            .group_by(ScanEvent.zaehlbereich_id)
        ).all()
    }

    return [
        s.BereichAus(id=b.id, name=b.name, zugewiesen_an=b.zugewiesen_an,
                     status=b.status, scans=zahlen.get(b.id, (0, 0))[0],
                     teile=zahlen.get(b.id, (0, 0))[1])
        for b in bereiche
    ]


# -- Scannen -------------------------------------------------------------

@router.post("/inventuren/{inventur_id}/scan", response_model=s.ScanAus)
def scanne(inventur_id: int, daten: s.ScanAn,
           sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        antwort = scan_dienst.scanne(
            sitzung, inventur, daten.code, erfasst_von=daten.erfasst_von,
            zaehlbereich_id=daten.zaehlbereich_id, geraet=daten.geraet,
            menge=daten.menge)
    except scan_dienst.ScanFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return s.ScanAus.aus(antwort)


@router.post("/inventuren/{inventur_id}/buchung", response_model=s.ScanAus)
def buche(inventur_id: int, daten: s.BuchungAn,
          sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        art = Erfassungsart(daten.erfassungsart)
    except ValueError:
        art = Erfassungsart.AUSWAHL
    if art is Erfassungsart.STORNO:
        raise HTTPException(400, "Storno bitte über den Storno-Endpunkt.")

    try:
        antwort = scan_dienst.buche_position(
            sitzung, inventur, daten.position_id, menge=daten.menge,
            erfassungsart=art, erfasst_von=daten.erfasst_von,
            zaehlbereich_id=daten.zaehlbereich_id, geraet=daten.geraet,
            roh_code=daten.roh_code)
    except scan_dienst.ScanFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return s.ScanAus.aus(antwort)


@router.post("/inventuren/{inventur_id}/scans/{event_id}/storno",
             response_model=s.ScanAus)
def storniere(inventur_id: int, event_id: int, erfasst_von: str = Query("unbekannt"),
              sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        antwort = scan_dienst.storniere(sitzung, inventur, event_id, erfasst_von)
    except scan_dienst.ScanFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return s.ScanAus.aus(antwort)


@router.get("/inventuren/{inventur_id}/suche", response_model=list[s.ArtikelAus])
def suche(inventur_id: int, q: str = Query(..., min_length=2),
          sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    return [s.ArtikelAus.aus(p) for p in scan_dienst.suche(sitzung, inventur, q)]


@router.get("/inventuren/{inventur_id}/log", response_model=list[s.LogEintragAus])
def log(inventur_id: int, grenze: int = Query(25, le=200),
        zaehlbereich_id: int | None = Query(None),
        sitzung: Session = Depends(hole_sitzung)):
    _inventur(sitzung, inventur_id)

    bedingungen = [ScanEvent.inventur_id == inventur_id]
    if zaehlbereich_id is not None:
        bedingungen.append(ScanEvent.zaehlbereich_id == zaehlbereich_id)

    zeilen = sitzung.execute(
        select(ScanEvent, Sollposition)
        .outerjoin(Sollposition, ScanEvent.sollposition_id == Sollposition.id)
        .where(*bedingungen)
        .order_by(ScanEvent.id.desc())
        .limit(grenze)
    ).all()

    storniert = {
        eid for (eid,) in sitzung.execute(
            select(ScanEvent.storniert_event_id)
            .where(ScanEvent.inventur_id == inventur_id,
                   ScanEvent.storniert_event_id.is_not(None))
        ).all()
    }

    return [
        s.LogEintragAus(
            id=ev.id, erfasst_am=ev.erfasst_am, erfasst_von=ev.erfasst_von,
            erfassungsart=ev.erfassungsart, menge=ev.menge,
            ean=ev.ean, artikel=pos.bezeichnung if pos else "— unbekannt —",
            stornierbar=(ev.erfassungsart != Erfassungsart.STORNO.value
                         and ev.id not in storniert),
        )
        for ev, pos in zeilen
    ]


# -- Auswertung ----------------------------------------------------------

@router.get("/inventuren/{inventur_id}/auswertung", response_model=s.AuswertungAus)
def auswertung(inventur_id: int, nur_abweichungen: bool = Query(True),
               sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    a = auswertung_modul.erstelle(sitzung, inventur, nur_abweichungen=nur_abweichungen)
    return s.AuswertungAus(
        kennzahlen=s.KennzahlenAus(**asdict(a.kennzahlen)),
        differenzen=[
            s.DifferenzAus(artikel=s.ArtikelAus.aus(d.position),
                           buchbestand=d.buchbestand, gezaehlt=d.gezaehlt,
                           differenz=d.differenz, wert=d.wert)
            for d in a.differenzen
        ],
        unbekannte=[s.UnbekanntAus(ean=u.ean, roh_code=u.roh_code, menge=u.menge)
                    for u in a.unbekannte],
    )


@router.get("/inventuren/{inventur_id}/export.xlsx")
def export(inventur_id: int, sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    puffer = export_modul.baue(sitzung, inventur)
    name = f"inventur_{inventur.filial_nr}_{inventur.id}.xlsx"
    return StreamingResponse(
        puffer,
        media_type=("application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/inventuren/{inventur_id}/importprotokoll")
def importprotokoll(inventur_id: int, sitzung: Session = Depends(hole_sitzung)):
    from app.db.tabellen import ImportProtokoll

    _inventur(sitzung, inventur_id)
    eintraege = list(sitzung.scalars(
        select(ImportProtokoll).where(ImportProtokoll.inventur_id == inventur_id)
        .order_by(ImportProtokoll.id.desc())))
    return [
        {
            "dateiname": e.dateiname,
            "zeilen_gelesen": e.zeilen_gelesen,
            "zeilen_importiert": e.zeilen_importiert,
            "zeilen_uebersprungen": e.zeilen_uebersprungen,
            "spaltenzuordnung": json.loads(e.spaltenzuordnung or "{}"),
            "hinweise": json.loads(e.hinweise or "[]"),
            "importiert_am": e.importiert_am,
        }
        for e in eintraege
    ]
