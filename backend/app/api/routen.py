"""REST-Endpunkte der Inventur-App."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas as s
from app.api.sicherheit import admin_pflicht, aktueller_benutzer
from app.db.sitzung import hole_sitzung
from app.db.tabellen import Benutzer, Inventur, ScanEvent, Sollposition
from app.dienste import auswertung as auswertung_modul
from app.dienste import benutzer_dienst, bereiche, markierungen, medien
from app.dienste import export as export_modul
from app.dienste import scan_dienst
from app.dienste.import_dienst import ImportGesperrt, importiere
from app.domain.werte import BereichStatus, Ebene, Erfassungsart, InventurStatus, Rolle
from app.quellen.excel import ExcelBestandsQuelle

# Ohne Anmeldung erreichbar: die Anmeldung selbst und das Anlegen des ersten
# Benutzers - sonst käme man in ein frisches System nicht hinein.
offen = APIRouter(prefix="/api")

# Alles Übrige verlangt einen gültigen Token.
router = APIRouter(prefix="/api", dependencies=[Depends(aktueller_benutzer)])


@offen.post("/anmeldung", response_model=s.AnmeldungAus)
def anmelden(daten: s.AnmeldungAn, sitzung: Session = Depends(hole_sitzung)):
    try:
        angemeldet = benutzer_dienst.melde_an(sitzung, daten.name, daten.pin,
                                              daten.geraet)
    except benutzer_dienst.AnmeldeFehler as fehler:
        raise HTTPException(401, str(fehler)) from fehler
    return s.AnmeldungAus(token=angemeldet.token, name=angemeldet.benutzer.name,
                          rolle=angemeldet.benutzer.rolle)


@offen.post("/benutzer", response_model=s.BenutzerAus, status_code=201)
def lege_benutzer_an(daten: s.BenutzerAn,
                     x_token: str | None = Header(default=None, alias="X-Token"),
                     sitzung: Session = Depends(hole_sitzung)):
    """Der erste Benutzer wird ohne Anmeldung angelegt und ist Administratorin.
    Danach dürfen nur Administratorinnen weitere Benutzer anlegen."""
    erster = benutzer_dienst.anzahl_benutzer(sitzung) == 0

    if erster:
        rolle = Rolle.ADMIN
    else:
        anmelder = benutzer_dienst.zu_token(sitzung, x_token)
        if anmelder is None:
            raise HTTPException(401, "Nicht angemeldet.")
        if anmelder.rolle != Rolle.ADMIN.value:
            raise HTTPException(403, "Nur Administratorinnen legen Benutzer an.")
        try:
            rolle = Rolle(daten.rolle)
        except ValueError:
            rolle = Rolle.ZAEHLER

    try:
        benutzer = benutzer_dienst.lege_an(sitzung, daten.name, daten.pin, rolle)
    except benutzer_dienst.AnmeldeFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return s.BenutzerAus(id=benutzer.id, name=benutzer.name, rolle=benutzer.rolle)


@offen.get("/einrichtung")
def einrichtung(sitzung: Session = Depends(hole_sitzung)):
    """Sagt der App, ob überhaupt schon jemand angelegt ist."""
    return {"benutzer_vorhanden": benutzer_dienst.anzahl_benutzer(sitzung) > 0,
            "anmeldung_noetig": benutzer_dienst.auth_erforderlich()}


@router.post("/abmeldung", status_code=204)
def abmelden(x_token: str | None = Header(default=None, alias="X-Token"),
             sitzung: Session = Depends(hole_sitzung)):
    if x_token:
        benutzer_dienst.melde_ab(sitzung, x_token)


@router.get("/ich", response_model=s.BenutzerAus)
def ich(benutzer: Benutzer = Depends(aktueller_benutzer)):
    return s.BenutzerAus(id=benutzer.id, name=benutzer.name, rolle=benutzer.rolle)


def _inventur(sitzung: Session, inventur_id: int) -> Inventur:
    inventur = sitzung.get(Inventur, inventur_id)
    if inventur is None:
        raise HTTPException(404, "Inventur nicht gefunden.")
    return inventur


def _bereich_aus(sitzung: Session, inventur: Inventur, bereich_id: int) -> s.BereichAus:
    """Antwort inklusive Fortschritt – dafür wird der Baum neu berechnet."""
    def suche(knoten):
        for k in knoten:
            if k.bereich.id == bereich_id:
                return k
            treffer = suche(k.kinder)
            if treffer:
                return treffer
        return None

    gefunden = suche(bereiche.baum(sitzung, inventur))
    if gefunden is None:
        raise HTTPException(404, "Bereich nicht gefunden.")
    return s.BereichAus.aus(gefunden)


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


# -- Zonen der Ladenskizze ----------------------------------------------

@router.post("/inventuren/{inventur_id}/bereiche", response_model=s.BereichAus,
             status_code=201)
def lege_bereich_an(inventur_id: int, daten: s.BereichAn,
                    _: Benutzer = Depends(admin_pflicht),
                    sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        ebene = Ebene(daten.ebene)
    except ValueError:
        ebene = Ebene.STAENDER
    try:
        bereich = bereiche.lege_an(
            sitzung, inventur, daten.name, eltern_id=daten.eltern_id, ebene=ebene,
            soll_teile=daten.soll_teile, karte_x=daten.karte_x,
            karte_y=daten.karte_y, notiz=daten.notiz)
    except bereiche.BereichFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler

    return s.BereichAus.aus(bereiche.Fortschritt(bereich=bereich, gezaehlt=0,
                                                 soll_teile=bereich.soll_teile))


@router.get("/inventuren/{inventur_id}/bereiche", response_model=list[s.BereichAus])
def liste_bereiche(inventur_id: int, sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    return [s.BereichAus.aus(f) for f in bereiche.baum(sitzung, inventur)]


@router.patch("/inventuren/{inventur_id}/bereiche/{bereich_id}",
              response_model=s.BereichAus)
def aendere_bereich(inventur_id: int, bereich_id: int, daten: s.BereichAendernAn,
                    _: Benutzer = Depends(admin_pflicht),
                    sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        bereich = bereiche.aendere(sitzung, inventur, bereich_id,
                                   **daten.model_dump(exclude_none=True))
    except bereiche.BereichFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return _bereich_aus(sitzung, inventur, bereich.id)


@router.post("/inventuren/{inventur_id}/bereiche/{bereich_id}/status",
             response_model=s.BereichAus)
def setze_bereich_status(inventur_id: int, bereich_id: int, daten: s.StatusAn,
                         benutzer: Benutzer = Depends(aktueller_benutzer),
                         sitzung: Session = Depends(hole_sitzung)):
    """Bereich übernehmen oder abschließen – das ist die Zuteilung auf der Karte."""
    inventur = _inventur(sitzung, inventur_id)
    try:
        status = BereichStatus(daten.status)
    except ValueError as fehler:
        raise HTTPException(400, "Status muss offen, laeuft oder fertig sein.") from fehler

    try:
        bereiche.setze_status(sitzung, inventur, bereich_id, status, benutzer.name)
    except bereiche.BereichFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return _bereich_aus(sitzung, inventur, bereich_id)


@router.post("/inventuren/{inventur_id}/bereiche/{bereich_id}/bild",
             response_model=s.BereichAus)
async def lade_bereichsbild(inventur_id: int, bereich_id: int,
                            datei: UploadFile = File(...),
                            _: Benutzer = Depends(admin_pflicht),
                            sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        name = medien.speichere(await datei.read(), datei.content_type,
                                f"bereich{bereich_id}")
        bereiche.aendere(sitzung, inventur, bereich_id, bild_pfad=name)
    except (medien.MedienFehler, bereiche.BereichFehler) as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    return _bereich_aus(sitzung, inventur, bereich_id)


@router.post("/inventuren/{inventur_id}/karte")
async def lade_karte(inventur_id: int, datei: UploadFile = File(...),
                     _: Benutzer = Depends(admin_pflicht),
                     sitzung: Session = Depends(hole_sitzung)):
    """Die abfotografierte Grundrissskizze, auf der die Bereiche liegen."""
    inventur = _inventur(sitzung, inventur_id)
    try:
        inventur.karte_bild = medien.speichere(await datei.read(), datei.content_type,
                                               f"karte{inventur_id}")
    except medien.MedienFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    sitzung.commit()
    return {"karte": inventur.karte_bild}


@offen.get("/bilder/{name}")
def hole_bild(name: str):
    try:
        ziel = medien.pfad(name)
    except medien.MedienFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    if not ziel.is_file():
        raise HTTPException(404, "Bild nicht gefunden.")
    return FileResponse(ziel)


# -- Markierungen -------------------------------------------------------

@router.post("/inventuren/{inventur_id}/markierungen", response_model=s.MarkierungAus,
             status_code=201)
def melde_markierung(inventur_id: int, daten: s.MarkierungAn,
                     benutzer: Benutzer = Depends(aktueller_benutzer),
                     sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        markierung = markierungen.melde(
            sitzung, inventur, grund=daten.grund, dringlichkeit=daten.dringlichkeit,
            gemeldet_von=benutzer.name, zaehlbereich_id=daten.zaehlbereich_id,
            scan_event_id=daten.scan_event_id, sollposition_id=daten.sollposition_id)
    except markierungen.MarkierungFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    return s.MarkierungAus.aus(markierung)


@router.get("/inventuren/{inventur_id}/markierungen", response_model=list[s.MarkierungAus])
def liste_markierungen(inventur_id: int, nur_offene: bool = Query(True),
                       sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    return [s.MarkierungAus.aus(m)
            for m in markierungen.liste(sitzung, inventur, nur_offene)]


@router.get("/inventuren/{inventur_id}/markierungen/anzahl")
def offene_markierungen(inventur_id: int, sitzung: Session = Depends(hole_sitzung)):
    """Für den Zähler im Admin-Bereich – wird regelmäßig abgefragt."""
    inventur = _inventur(sitzung, inventur_id)
    return markierungen.offene_anzahl(sitzung, inventur)


@router.post("/inventuren/{inventur_id}/markierungen/{markierung_id}/erledigt",
             response_model=s.MarkierungAus)
def erledige_markierung(inventur_id: int, markierung_id: int, daten: s.ErledigtAn,
                        benutzer: Benutzer = Depends(admin_pflicht),
                        sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        markierung = markierungen.erledige(sitzung, inventur, markierung_id,
                                           benutzer.name, daten.antwort)
    except markierungen.MarkierungFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return s.MarkierungAus.aus(markierung)


# -- Scannen -------------------------------------------------------------

@router.post("/inventuren/{inventur_id}/scan", response_model=s.ScanAus)
def scanne(inventur_id: int, daten: s.ScanAn,
           benutzer: Benutzer = Depends(aktueller_benutzer),
           sitzung: Session = Depends(hole_sitzung)):
    inventur = _inventur(sitzung, inventur_id)
    try:
        antwort = scan_dienst.scanne(
            sitzung, inventur, daten.code, erfasst_von=benutzer.name,
            zaehlbereich_id=daten.zaehlbereich_id, geraet=daten.geraet,
            menge=daten.menge)
    except scan_dienst.ScanFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return s.ScanAus.aus(antwort)


@router.post("/inventuren/{inventur_id}/buchung", response_model=s.ScanAus)
def buche(inventur_id: int, daten: s.BuchungAn,
          benutzer: Benutzer = Depends(aktueller_benutzer),
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
            erfassungsart=art, erfasst_von=benutzer.name,
            zaehlbereich_id=daten.zaehlbereich_id, geraet=daten.geraet,
            roh_code=daten.roh_code)
    except scan_dienst.ScanFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return s.ScanAus.aus(antwort)


@router.post("/inventuren/{inventur_id}/scans/{event_id}/storno",
             response_model=s.ScanAus)
def storniere(inventur_id: int, event_id: int,
              benutzer: Benutzer = Depends(admin_pflicht),
              sitzung: Session = Depends(hole_sitzung)):
    """Nur Administratorinnen. Zählerinnen markieren stattdessen."""
    inventur = _inventur(sitzung, inventur_id)
    try:
        antwort = scan_dienst.storniere(sitzung, inventur, event_id, benutzer.name)
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
