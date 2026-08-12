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

    @classmethod
    def aus(cls, i, positionen: int = 0) -> "InventurAus":
        return cls(id=i.id, filial_nr=i.filial_nr, filiale=i.filiale,
                   bezeichnung=i.bezeichnung, status=i.status,
                   angelegt_am=i.angelegt_am, positionen=positionen)


class BereichAn(BaseModel):
    name: str
    zugewiesen_an: str | None = None


class BereichAus(BaseModel):
    id: int
    name: str
    zugewiesen_an: str | None
    status: str
    scans: int = 0
    teile: int = 0


class ScanAn(BaseModel):
    code: str
    zaehlbereich_id: int | None = None
    erfasst_von: str = "unbekannt"
    geraet: str | None = None
    menge: int = 1


class BuchungAn(BaseModel):
    position_id: int
    zaehlbereich_id: int | None = None
    erfasst_von: str = "unbekannt"
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
