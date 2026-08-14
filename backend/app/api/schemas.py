"""API-Datenklassen.

Bewusst eigene Klassen statt der ORM-Objekte: das Frontend soll nicht an
Tabellenspalten haengen. Wenn sich die Datenbank aendert, aendert sich hier
das Mapping und nicht das Frontend.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ArtikelAus(BaseModel):
    id: int
    ean: str | None
    artikelnummer: str
    artikelname: str
    marke: str
    farbnummer: str
    farbe: str
    groesse: str
    vk_preis: float
    buchbestand: int
    bezeichnung: str

    @classmethod
    def aus(cls, p) -> "ArtikelAus":
        return cls(
            id=p.id, ean=p.ean, artikelnummer=p.artikelnummer,
            artikelname=p.artikelname, marke=p.marke, farbnummer=p.farbnummer,
            farbe=p.farbe, groesse=p.groesse, vk_preis=float(p.vk_preis or 0),
            buchbestand=p.buchbestand, bezeichnung=p.bezeichnung,
        )


class InventurAn(BaseModel):
    filial_nr: str = "12"
    filiale: str = "Bad Krozingen"
    bezeichnung: str = Field(default="Inventur")


class InventurAus(BaseModel):
    id: int
    filial_nr: str
    filiale: str
    bezeichnung: str
    status: str
    angelegt_am: datetime | None = None
    positionen: int = 0
    karte_bild: str | None = None

    @classmethod
    def aus(cls, i, positionen: int = 0) -> "InventurAus":
        return cls(id=i.id, filial_nr=i.filial_nr, filiale=i.filiale,
                   bezeichnung=i.bezeichnung, status=i.status,
                   angelegt_am=i.angelegt_am, positionen=positionen,
                   karte_bild=i.karte_bild)


class BereichAn(BaseModel):
    name: str
    eltern_id: int | None = None
    ebene: str = "staender"
    soll_teile: int | None = None
    karte_x: float | None = None
    karte_y: float | None = None
    notiz: str | None = None


class BereichAendernAn(BaseModel):
    name: str | None = None
    soll_teile: int | None = None
    karte_x: float | None = None
    karte_y: float | None = None
    notiz: str | None = None


class StatusAn(BaseModel):
    status: str


class BereichAus(BaseModel):
    id: int
    name: str
    ebene: str
    eltern_id: int | None = None
    zugewiesen_an: str | None = None
    status: str
    soll_teile: int | None = None
    gezaehlt: int = 0
    offen: int | None = None
    anteil: float | None = None
    notiz: str | None = None
    bild: str | None = None
    karte_x: float | None = None
    karte_y: float | None = None
    kinder: list["BereichAus"] = Field(default_factory=list)

    @classmethod
    def aus(cls, f) -> "BereichAus":
        b = f.bereich
        return cls(
            id=b.id, name=b.name, ebene=b.ebene, eltern_id=b.eltern_id,
            zugewiesen_an=b.zugewiesen_an, status=b.status,
            soll_teile=f.soll_teile, gezaehlt=f.gezaehlt, offen=f.offen,
            anteil=f.anteil, notiz=b.notiz, bild=b.bild_pfad,
            karte_x=float(b.karte_x) if b.karte_x is not None else None,
            karte_y=float(b.karte_y) if b.karte_y is not None else None,
            kinder=[cls.aus(k) for k in f.kinder],
        )


class AnmeldungAn(BaseModel):
    name: str
    pin: str
    geraet: str | None = None


class BenutzerAn(BaseModel):
    name: str
    pin: str
    rolle: str = "zaehler"


class AnmeldungAus(BaseModel):
    token: str
    name: str
    rolle: str


class BenutzerAus(BaseModel):
    id: int
    name: str
    rolle: str


class MarkierungAn(BaseModel):
    grund: str
    dringlichkeit: int = 1
    zaehlbereich_id: int | None = None
    scan_event_id: int | None = None
    sollposition_id: int | None = None


class ErledigtAn(BaseModel):
    antwort: str | None = None


class MarkierungAus(BaseModel):
    id: int
    grund: str
    dringlichkeit: int
    status: str
    gemeldet_von: str
    gemeldet_am: datetime | None = None
    bereich: str | None = None
    artikel: str | None = None
    scan_event_id: int | None = None
    erledigt_von: str | None = None
    erledigt_am: datetime | None = None
    antwort: str | None = None

    @classmethod
    def aus(cls, m) -> "MarkierungAus":
        return cls(
            id=m.id, grund=m.grund, dringlichkeit=m.dringlichkeit, status=m.status,
            gemeldet_von=m.gemeldet_von, gemeldet_am=m.gemeldet_am,
            bereich=m.bereich.name if m.bereich else None,
            artikel=m.position.bezeichnung if m.position else None,
            scan_event_id=m.scan_event_id,
            erledigt_von=m.erledigt_von, erledigt_am=m.erledigt_am, antwort=m.antwort,
        )


class ScanAn(BaseModel):
    code: str
    zaehlbereich_id: int | None = None
    geraet: str | None = None
    menge: int = 1


class BuchungAn(BaseModel):
    position_id: int
    zaehlbereich_id: int | None = None
    geraet: str | None = None
    menge: int = 1
    roh_code: str | None = None
    erfassungsart: str = "auswahl"


class ScanAus(BaseModel):
    ergebnis: str
    meldung: str
    roh_code: str
    ean: str | None = None
    event_id: int | None = None
    artikel: ArtikelAus | None = None
    kandidaten: list[ArtikelAus] = Field(default_factory=list)
    gezaehlt: int | None = None

    @classmethod
    def aus(cls, a) -> "ScanAus":
        return cls(
            ergebnis=a.ergebnis.value, meldung=a.meldung, roh_code=a.roh_code,
            ean=a.ean, event_id=a.event_id,
            artikel=ArtikelAus.aus(a.position) if a.position else None,
            kandidaten=[ArtikelAus.aus(k) for k in a.kandidaten],
            gezaehlt=a.gezaehlt,
        )


class ImportAus(BaseModel):
    zeilen_gelesen: int
    zeilen_importiert: int
    zeilen_uebersprungen: int
    spaltenzuordnung: dict[str, str]
    hinweise: list[str]


class DifferenzAus(BaseModel):
    artikel: ArtikelAus
    buchbestand: int
    gezaehlt: int
    differenz: int
    wert: float


class UnbekanntAus(BaseModel):
    ean: str | None
    roh_code: str | None
    menge: int


class KennzahlenAus(BaseModel):
    positionen_gesamt: int
    positionen_gezaehlt: int
    scans_gesamt: int
    buchbestand_gesamt: int
    gezaehlt_gesamt: int
    fehlmenge: int
    ueberbestand: int
    differenz_wert: float
    unbekannte_teile: int


class AuswertungAus(BaseModel):
    kennzahlen: KennzahlenAus
    differenzen: list[DifferenzAus]
    unbekannte: list[UnbekanntAus]


class LogEintragAus(BaseModel):
    id: int
    erfasst_am: datetime | None
    erfasst_von: str
    erfassungsart: str
    menge: int
    ean: str | None
    artikel: str
    stornierbar: bool
