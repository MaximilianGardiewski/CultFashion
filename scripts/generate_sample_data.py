"""Erzeugt Probe-Excel-Dateien fuer die Inventur-App (Filiale Bad Krozingen).

Die echten advarics-Exporte liegen noch nicht vor. Diese Dateien definieren das
Zielformat und decken bewusst die Sonderfaelle ab, an denen ein Inventur-Scanner
in der Praxis scheitert.

Ausgabe nach samples/:
  1_sollbestand_referenz.xlsx   Kanonisches Importformat (Zielbild)
  2_advarics_export_roh.xlsx    Simulierter Rohexport, absichtlich unsauber
  3_scan_testfaelle.xlsx        Scan-Testfaelle mit erwartetem App-Verhalten

Aufruf:  python scripts/generate_sample_data.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

SEED = 20260812
FILIALE_NR = "12"
FILIALE = "Bad Krozingen"
STICHTAG = "12.08.2026"

OUT_DIR = Path(__file__).resolve().parent.parent / "samples"

FONT = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(name=FONT, size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT, size=10)
TITLE_FONT = Font(name=FONT, size=12, bold=True)
NOTE_FONT = Font(name=FONT, size=9, italic=True, color="666666")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# --------------------------------------------------------------------------
# Groessen- und Farbstammdaten
# --------------------------------------------------------------------------

KONFEKTION = ["34", "36", "38", "40", "42", "44"]
KONFEKTION_KURZ = ["36", "38", "40", "42", "44"]
ALPHA = ["XS", "S", "M", "L", "XL"]
JEANS_WL = ["W27/L32", "W28/L32", "W29/L32", "W30/L32", "W31/L32", "W32/L32"]
ANGELS_WL = ["36/30", "38/30", "40/30", "42/30", "38/32", "40/32", "42/32", "44/32"]
ONESIZE = ["onesize"]

OFFWHITE = ("101", "offwhite")
CREME = ("777", "créme")
CAMEL = ("208", "camel")
KHAKI = ("330", "khaki")
NAVY = ("401", "navy")
DENIM = ("610", "denim blue")
GREY = ("055", "light grey melange")
BORDEAUX = ("512", "bordeaux")
BLACK = ("900", "black")


@dataclass
class Artikel:
    marke: str
    gs1_prefix: str          # Laendercode-Praefix der EAN (DE 40-44, DK 57)
    artikelnummer: str
    artikelname: str
    warengruppe: str
    saison: str
    vk_preis: float
    farben: list[tuple[str, str]]
    groessen: list[str]
    ean_modus: str = "je_sku"   # "je_sku" | "je_artikel"  <- Sonderfall Taschen/Schals
    notiz: str = field(default="")


ARTIKEL: list[Artikel] = [
    Artikel("Opus", "40", "6620-1234", "Bluse Falia", "Blusen", "HW26", 79.99,
            [OFFWHITE, NAVY, BLACK], KONFEKTION),
    Artikel("Opus", "40", "6710-0088", "Hose Melina", "Hosen", "HW26", 89.99,
            [BLACK, KHAKI], KONFEKTION),
    Artikel("Opus", "40", "6805-4411", "Strickjacke Wanni", "Strick", "HW26", 99.99,
            [GREY, BORDEAUX], KONFEKTION_KURZ),
    Artikel("Opus", "40", "6901-2233", "Kleid Wilana", "Kleider", "HW26", 109.99,
            [NAVY], KONFEKTION),
    Artikel("Opus", "40", "6955-7788", "Shirt Sarina", "Shirts", "HW26", 39.99,
            [CREME, BLACK], KONFEKTION),
    Artikel("Tom Tailor", "41", "1032145", "T-Shirt Basic Crew", "Shirts", "NOS", 24.99,
            [OFFWHITE, BLACK, DENIM], ALPHA),
    Artikel("Tom Tailor", "41", "1039876", "Chino Travis", "Hosen", "HW26", 59.99,
            [KHAKI, NAVY], JEANS_WL),
    Artikel("Tom Tailor", "41", "1041122", "Sweatjacke Ben", "Sweat", "HW26", 69.99,
            [GREY, BLACK], ALPHA),
    Artikel("Vero Moda", "57", "10289456", "Kleid Vmharlow", "Kleider", "HW26", 39.99,
            [BLACK, BORDEAUX], ALPHA),
    Artikel("Vero Moda", "57", "10301188", "Bluse Vmbeauty", "Blusen", "HW26", 29.99,
            [OFFWHITE, NAVY], ALPHA),
    Artikel("Only", "57", "15077791", "Jeans Onlroyal", "Jeans", "NOS", 34.99,
            [DENIM, BLACK], ALPHA),
    Artikel("Only", "57", "15195681", "Top Onlmoster", "Shirts", "NOS", 14.99,
            [OFFWHITE, BLACK, BORDEAUX], ALPHA),
    Artikel("Angels", "40", "332-1200", "Jeans Cici", "Jeans", "NOS", 99.95,
            [DENIM, BLACK], ANGELS_WL),
    Artikel("Angels", "40", "519-1234", "Jeans Skinny Button", "Jeans", "HW26", 109.95,
            [DENIM], ANGELS_WL),
    # --- Sonderfall 1: eine EAN fuer das ganze Modell, ueber alle Farben ---
    Artikel("Tom Tailor", "41", "3011990", "Tasche Shopper Lea", "Taschen", "HW26", 49.99,
            [BLACK, CAMEL, NAVY, BORDEAUX], ONESIZE, ean_modus="je_artikel",
            notiz="Sonderfall: identische EAN fuer alle Farben"),
    Artikel("Tom Tailor", "41", "3014477", "Loop Basic", "Accessoires", "HW26", 19.99,
            [GREY, BLACK, BORDEAUX], ONESIZE, ean_modus="je_artikel",
            notiz="Sonderfall: identische EAN fuer alle Farben"),
    # --- Sonderfall 2: EAN mit fuehrender Null (Excel macht daraus gern eine Zahl) ---
    Artikel("Opus", "0", "6300-5511", "Gürtel Basic", "Accessoires", "HW26", 29.99,
            [BLACK, CAMEL], ONESIZE,
            notiz="Sonderfall: EAN mit fuehrender Null"),
]


# --------------------------------------------------------------------------
# EAN-13
# --------------------------------------------------------------------------

def ean13_pruefziffer(basis12: str) -> str:
    """Standard EAN-13 Pruefziffer (Gewichtung 1/3 von links)."""
    summe = sum(int(z) * (3 if i % 2 else 1) for i, z in enumerate(basis12))
    return str((10 - summe % 10) % 10)


# Fiktive Betriebsnummern, damit die EANs je Marke zusammengehoerig aussehen
BETRIEBSNUMMER = {
    "Opus": "5312",
    "Tom Tailor": "8471",
    "Vero Moda": "1290",
    "Only": "3355",
    "Angels": "6042",
}


def ean13_gueltig(ean: str) -> bool:
    return (len(ean) == 13 and ean.isdigit()
            and ean13_pruefziffer(ean[:12]) == ean[12])


# T7: gueltige EAN-13, die bewusst NICHT im Sortiment steht
EAN_UNBEKANNT = "401481907250" + ean13_pruefziffer("401481907250")
# T12: absichtlich falsche Pruefziffer (korrekt waere eine andere Endziffer)
_BASIS_FALSCH = "401234567890"
EAN_PRUEFZIFFER_FALSCH = _BASIS_FALSCH + str(
    (int(ean13_pruefziffer(_BASIS_FALSCH)) + 1) % 10)


def baue_ean(prefix: str, marke: str, lauf: int) -> str:
    betrieb = BETRIEBSNUMMER[marke]
    basis = prefix + betrieb + str(lauf).zfill(12 - len(prefix) - len(betrieb))
    assert len(basis) == 12, basis
    return basis + ean13_pruefziffer(basis)


# --------------------------------------------------------------------------
# Zeilen erzeugen
# --------------------------------------------------------------------------

SPALTEN = [
    ("ean", "EAN", 16),
    ("artikelnummer", "Artikelnummer", 15),
    ("artikelname", "Artikelname", 24),
    ("marke", "Marke", 13),
    ("warengruppe", "Warengruppe", 14),
    ("farbnummer", "Farbnummer", 12),
    ("farbe", "Farbe", 20),
    ("groesse", "Größe", 10),
    ("vk_preis", "VK-Preis", 11),
    ("buchbestand", "Buchbestand", 12),
    ("saison", "Saison", 9),
    ("filial_nr", "Filial-Nr.", 10),
    ("filiale", "Filiale", 16),
]


def erzeuge_zeilen() -> list[dict]:
    rng = random.Random(SEED)
    zeilen: list[dict] = []
    lauf = 100001

    for art in ARTIKEL:
        artikel_ean = None
        if art.ean_modus == "je_artikel":
            artikel_ean = baue_ean(art.gs1_prefix, art.marke, lauf)
            lauf += 1

        for farbnr, farbe in art.farben:
            for groesse in art.groessen:
                if artikel_ean is not None:
                    ean = artikel_ean
                else:
                    ean = baue_ean(art.gs1_prefix, art.marke, lauf)
                    lauf += 1

                # Bestandsverteilung wie im Laden: viel 1-3, einiges 0, selten mehr
                bestand = rng.choices(
                    [0, 1, 2, 3, 4, 5, 8],
                    weights=[18, 30, 22, 14, 8, 5, 3],
                )[0]

                zeilen.append({
                    "ean": ean,
                    "artikelnummer": art.artikelnummer,
                    "artikelname": art.artikelname,
                    "marke": art.marke,
                    "warengruppe": art.warengruppe,
                    "farbnummer": farbnr,
                    "farbe": farbe,
                    "groesse": groesse,
                    "vk_preis": art.vk_preis,
                    "buchbestand": bestand,
                    "saison": art.saison,
                    "filial_nr": FILIALE_NR,
                    "filiale": FILIALE,
                })

    _sonderfaelle_einbauen(zeilen)
    _pruefe(zeilen)
    return zeilen


def _pruefe(zeilen: list[dict]) -> None:
    """Zusicherungen, damit die Testfaelle wirklich das testen, was draufsteht."""
    vorhanden = {z["ean"] for z in zeilen if z["ean"]}

    for ean in vorhanden:
        assert ean13_gueltig(ean), f"ungueltige EAN im Stamm: {ean}"

    assert ean13_gueltig(EAN_UNBEKANNT), "T7 muss eine gueltige EAN sein"
    assert EAN_UNBEKANNT not in vorhanden, "T7 darf nicht im Sortiment stehen"
    assert not ean13_gueltig(EAN_PRUEFZIFFER_FALSCH), "T12 muss ungueltig sein"


def _finde(zeilen: list[dict], **kriterien) -> list[dict]:
    return [z for z in zeilen
            if all(z.get(k) == v for k, v in kriterien.items())]


def _sonderfaelle_einbauen(zeilen: list[dict]) -> None:
    """Bewusst platzierte Datenfehler und Randfaelle."""

    # (a) Artikel ohne EAN im Stamm -> muss ueber Suche zaehlbar sein
    for treffer in (
        _finde(zeilen, artikelnummer="6901-2233", groesse="38"),
        _finde(zeilen, artikelnummer="1041122", groesse="L", farbnummer="900"),
        _finde(zeilen, artikelnummer="15195681", groesse="S", farbnummer="512"),
    ):
        if treffer:
            treffer[0]["ean"] = None

    # (b) Negativer Buchbestand - kommt durch Fehlbuchungen real vor
    treffer = _finde(zeilen, artikelnummer="332-1200", groesse="40/32", farbnummer="610")
    if treffer:
        treffer[0]["buchbestand"] = -2

    # (c) Dieselbe EAN auf zwei fachlich verschiedenen Artikeln (Datenfehler)
    quelle = _finde(zeilen, artikelnummer="15195681", groesse="M", farbnummer="101")
    ziel = _finde(zeilen, artikelnummer="10301188", groesse="M", farbnummer="101")
    if quelle and ziel:
        ziel[0]["ean"] = quelle[0]["ean"]

    # (d) Hoher Bestand auf einem NOS-Artikel - typischer Zaehlaufwand
    for z in _finde(zeilen, artikelnummer="1032145", farbnummer="900"):
        z["buchbestand"] = 12


# --------------------------------------------------------------------------
# Formatierungshilfen
# --------------------------------------------------------------------------

def schreibe_kopf(ws, spalten, zeile: int = 1) -> None:
    for idx, (_, ueberschrift, breite) in enumerate(spalten, start=1):
        zelle = ws.cell(row=zeile, column=idx, value=ueberschrift)
        zelle.font = HEADER_FONT
        zelle.fill = HEADER_FILL
        zelle.alignment = Alignment(horizontal="left", vertical="center")
        zelle.border = BORDER
        ws.column_dimensions[get_column_letter(idx)].width = breite
    ws.row_dimensions[zeile].height = 22


# --------------------------------------------------------------------------
# Datei 1: kanonisches Referenzformat
# --------------------------------------------------------------------------

def datei_referenz(zeilen: list[dict], pfad: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sollbestand"

    schreibe_kopf(ws, SPALTEN)

    for r, daten in enumerate(zeilen, start=2):
        for c, (schluessel, _, _) in enumerate(SPALTEN, start=1):
            zelle = ws.cell(row=r, column=c, value=daten[schluessel])
            zelle.font = BODY_FONT
            zelle.border = BORDER
            if schluessel in ("ean", "farbnummer", "artikelnummer", "groesse", "filial_nr"):
                zelle.number_format = "@"      # Text: fuehrende Nullen bleiben erhalten
                zelle.alignment = Alignment(horizontal="left")
            elif schluessel == "vk_preis":
                zelle.number_format = '#,##0.00 "€"'
            elif schluessel == "buchbestand":
                zelle.number_format = "0"

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(SPALTEN))}{len(zeilen) + 1}"

    _blatt_feldbeschreibung(wb)
    wb.save(pfad)


FELDER_DOKU = [
    ("ean", "Text", "Nein",
     "Scan-Schlüssel. NICHT die Identität: kann leer sein und kann auf mehrere Zeilen zeigen."),
    ("artikelnummer", "Text", "Ja",
     "Teil des fachlichen Schlüssels. Als Text führen, es kommen Bindestriche vor."),
    ("artikelname", "Text", "Ja",
     "Klartext für die Anzeige beim Scannen und für die manuelle Suche."),
    ("marke", "Text", "Ja",
     "Opus, Tom Tailor, Vero Moda, Only, Angels …"),
    ("warengruppe", "Text", "Nein",
     "Für Auswertung und Zählbereichs-Zuschnitt. Für die Zählung selbst nicht nötig."),
    ("farbnummer", "Text", "Ja",
     "Teil des fachlichen Schlüssels. Als Text führen (führende Nullen, z. B. 055)."),
    ("farbe", "Text", "Ja",
     "Klartext, wird bei mehrdeutiger EAN zur Auswahl angezeigt."),
    ("groesse", "Text", "Ja",
     "Teil des fachlichen Schlüssels. Immer Text: 38, XL, W30/L32, 40/32, onesize."),
    ("vk_preis", "Zahl", "Ja",
     "Verkaufspreis brutto in Euro. Bewertet die Inventurdifferenz."),
    ("buchbestand", "Ganzzahl", "Ja",
     "Bestand laut advarics. Darf 0 und (durch Fehlbuchungen) negativ sein."),
    ("saison", "Text", "Nein",
     "HW26, FS27, NOS. Nur informativ."),
    ("filial_nr", "Text", "Ja",
     "Konstante je Export. Jetzt nur 12, später mehrere Filialen."),
    ("filiale", "Text", "Nein",
     "Klartext zur Kontrolle beim Import."),
]


def _blatt_feldbeschreibung(wb: Workbook) -> None:
    ws = wb.create_sheet("Feldbeschreibung")

    ws["A1"] = "Importformat Inventur – Feldbeschreibung"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (
        "Identität einer Zeile = Artikelnummer + Farbnummer + Größe. "
        "Die EAN ist ausschließlich der Scan-Schlüssel."
    )
    ws["A2"].font = NOTE_FONT

    spalten = [("feld", "Feld", 16), ("typ", "Typ", 11),
               ("pflicht", "Pflicht", 9), ("bedeutung", "Bedeutung", 82)]
    schreibe_kopf(ws, spalten, zeile=4)

    for r, (feld, typ, pflicht, bedeutung) in enumerate(FELDER_DOKU, start=5):
        for c, wert in enumerate((feld, typ, pflicht, bedeutung), start=1):
            zelle = ws.cell(row=r, column=c, value=wert)
            zelle.font = BODY_FONT
            zelle.border = BORDER
            zelle.alignment = Alignment(vertical="top", wrap_text=(c == 4))

    hinweis = ws.cell(row=len(FELDER_DOKU) + 6, column=1, value=(
        "Spaltenreihenfolge und Schreibweise der Überschriften sind egal – der Import "
        "arbeitet mit einer Spaltenzuordnung. Entscheidend ist, dass die Pflichtfelder "
        "vorhanden sind."
    ))
    hinweis.font = NOTE_FONT


# --------------------------------------------------------------------------
# Datei 2: simulierter Rohexport (absichtlich unsauber)
# --------------------------------------------------------------------------

ROH_SPALTEN = [
    ("marke", "Marke", 13),
    ("artikelnummer", "Art.-Nr.", 14),
    ("artikelname", "Bezeichnung", 24),
    ("farbnummer", "Farb-Nr.", 10),
    ("farbe", "Farbe", 20),
    ("groesse", "Gr.", 10),
    ("ean", "EAN-Code", 16),
    ("vk_preis", "VK Brutto", 12),
    ("buchbestand", "Bestand", 10),
]


def datei_rohexport(zeilen: list[dict], pfad: Path) -> None:
    """Bildet nach, wie ein Report-Export typischerweise aussieht:
    Titelzeilen, andere Spaltennamen, andere Reihenfolge, Preis als Text,
    EAN teils als Zahl, Zwischensummen und Leerzeilen."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Bestandsliste"

    ws["A1"] = "advarics Warenwirtschaft"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Bestandsliste per {STICHTAG}"
    ws["A2"].font = BODY_FONT
    ws["A3"] = f"Filiale {FILIALE_NR} – Cult Fashion {FILIALE}"
    ws["A3"].font = BODY_FONT

    kopfzeile = 5
    schreibe_kopf(ws, ROH_SPALTEN, zeile=kopfzeile)

    reihenfolge = ["Opus", "Tom Tailor", "Vero Moda", "Only", "Angels"]
    nach_marke: dict[str, list[dict]] = {m: [] for m in reihenfolge}
    for z in zeilen:
        nach_marke.setdefault(z["marke"], []).append(z)

    r = kopfzeile + 1
    for idx, marke in enumerate(reihenfolge):
        gruppe = nach_marke.get(marke, [])
        if not gruppe:
            continue

        for daten in gruppe:
            for c, (schluessel, _, _) in enumerate(ROH_SPALTEN, start=1):
                wert = daten[schluessel]
                zelle = ws.cell(row=r, column=c)

                if schluessel == "vk_preis":
                    # Preis als deutscher Text mit Waehrungszeichen
                    zelle.value = f"{wert:.2f} €".replace(".", ",")
                elif schluessel == "ean":
                    if wert is None:
                        zelle.value = ""
                    elif idx % 2 == 0:
                        # Haelfte der Marken: EAN als Zahl -> fuehrende Null geht verloren
                        zelle.value = int(wert)
                        zelle.number_format = "0"
                    else:
                        zelle.value = str(wert)
                        zelle.number_format = "@"
                elif schluessel in ("farbnummer", "artikelnummer", "groesse"):
                    zelle.value = str(wert)
                    zelle.number_format = "@"
                else:
                    zelle.value = wert

                zelle.font = BODY_FONT
            r += 1

        summe = sum(z["buchbestand"] for z in gruppe)
        ws.cell(row=r, column=3, value=f"Summe {marke}").font = Font(
            name=FONT, size=10, bold=True)
        ws.cell(row=r, column=9, value=summe).font = Font(name=FONT, size=10, bold=True)
        r += 2   # Zwischensumme + Leerzeile

    gesamt = sum(z["buchbestand"] for z in zeilen)
    ws.cell(row=r, column=3, value="Gesamtsumme").font = Font(name=FONT, size=10, bold=True)
    ws.cell(row=r, column=9, value=gesamt).font = Font(name=FONT, size=10, bold=True)
    ws.cell(row=r + 2, column=1,
            value=f"Erstellt am {STICHTAG} – advarics Report 4711").font = NOTE_FONT

    wb.save(pfad)


# --------------------------------------------------------------------------
# Datei 3: Scan-Testfaelle
# --------------------------------------------------------------------------

def datei_testfaelle(zeilen: list[dict], pfad: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Scan-Testfälle"

    def ean_von(**kriterien) -> str:
        treffer = _finde(zeilen, **kriterien)
        return treffer[0]["ean"] if treffer and treffer[0]["ean"] else "—"

    tasche = ean_von(artikelnummer="3011990", farbnummer="900")
    loop = ean_von(artikelnummer="3014477", farbnummer="055")
    guertel = ean_von(artikelnummer="6300-5511", farbnummer="900")
    doppelt = ean_von(artikelnummer="15195681", groesse="M", farbnummer="101")
    normal = ean_von(artikelnummer="6620-1234", groesse="38", farbnummer="101")
    negativ = ean_von(artikelnummer="332-1200", groesse="40/32", farbnummer="610")

    faelle = [
        ("T1", "Normalfall", normal,
         "EAN trifft genau eine Zeile",
         "Sofort +1 buchen, Artikel einblenden, weiter im Dauerscan. Kein Dialog."),
        ("T2", "Mehrdeutige EAN – Farbe", tasche,
         "Eine EAN für 4 Farben (Tasche Shopper Lea, onesize)",
         "Farbauswahl anzeigen (black / camel / navy / bordeaux), dann +1 auf die gewählte Zeile."),
        ("T3", "Mehrdeutige EAN – Farbe", loop,
         "Eine EAN für 3 Farben (Loop Basic)",
         "Wie T2. Zuletzt gewählte Farbe vorschlagen, das beschleunigt Serien spürbar."),
        ("T4", "Führende Null", guertel,
         "EAN beginnt mit 0 – Excel macht daraus gern eine Zahl",
         "Import muss auf 13 Stellen linksseitig mit Null auffüllen, sonst kein Treffer."),
        ("T5", "Doppelte EAN – Datenfehler", doppelt,
         "Gleiche EAN auf zwei fachlich verschiedenen Artikeln",
         "Auswahldialog mit Marke + Artikelname, zusätzlich als Datenfehler im Report melden."),
        ("T6", "Keine EAN im Stamm", "—",
         "Kleid Wilana Gr. 38 / Sweatjacke Ben L schwarz / Top Onlmoster S bordeaux",
         "Nicht scanbar. Muss über Suche (Artikelnummer, Name) manuell zählbar sein, Kennzeichen 'manuell'."),
        ("T7", "Unbekannte EAN", EAN_UNBEKANNT,
         "Gescannter Code steht nicht in der Importdatei",
         "Trotzdem erfassen und als 'unbekannt' melden. Zählung NIE blockieren."),
        ("T8", "Negativer Buchbestand", negativ,
         "Jeans Cici 40/32 denim hat Buchbestand -2",
         "Zählung normal. Differenz = gezählt − (−2). Im Report gesondert ausweisen."),
        ("T9", "Buchbestand 0", "—",
         "Artikel steht mit 0 im Stamm, liegt aber im Laden",
         "Zählung erzeugt Überbestand. Kein Sonderfall in der Bedienung."),
        ("T10", "Doppelscan", normal,
         "Dieselbe EAN zweimal hintereinander in unter einer Sekunde",
         "Beide Scans zählen (zwei Teile!). Entprellung nur gegen den Kamera-Dauerauslöser, nicht gegen den Nutzer."),
        ("T11", "Storno", normal,
         "Rückgängig direkt nach einem Scan",
         "Gegenbuchung −1 als neuer Eintrag im Log, kein Löschen. Log bleibt lückenlos."),
        ("T12", "Prüfziffer falsch", EAN_PRUEFZIFFER_FALSCH,
         "Beschädigtes oder falsch gedrucktes Etikett",
         "Als ungültige EAN abweisen mit hörbarem Fehlsignal, nicht stumm als unbekannt buchen."),
    ]

    spalten = [("nr", "Nr.", 7), ("fall", "Testfall", 26), ("ean", "EAN zum Scannen", 18),
               ("situation", "Situation", 52), ("erwartet", "Erwartetes Verhalten der App", 74)]

    ws["A1"] = "Inventur-Scanner – Testfälle"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("Alle EANs stammen aus 1_sollbestand_referenz.xlsx und sind gültige EAN-13 "
                "mit korrekter Prüfziffer – sie lassen sich als Barcode drucken und scannen.")
    ws["A2"].font = NOTE_FONT

    schreibe_kopf(ws, spalten, zeile=4)

    for r, fall in enumerate(faelle, start=5):
        for c, wert in enumerate(fall, start=1):
            zelle = ws.cell(row=r, column=c, value=wert)
            zelle.font = BODY_FONT
            zelle.border = BORDER
            zelle.alignment = Alignment(vertical="top", wrap_text=(c >= 4))
            if c == 3:
                zelle.number_format = "@"
        ws.row_dimensions[r].height = 30

    ws.freeze_panes = "A5"
    wb.save(pfad)


# --------------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    zeilen = erzeuge_zeilen()

    datei_referenz(zeilen, OUT_DIR / "1_sollbestand_referenz.xlsx")
    datei_rohexport(zeilen, OUT_DIR / "2_advarics_export_roh.xlsx")
    datei_testfaelle(zeilen, OUT_DIR / "3_scan_testfaelle.xlsx")

    ohne_ean = sum(1 for z in zeilen if not z["ean"])
    eans = [z["ean"] for z in zeilen if z["ean"]]
    print(f"{len(zeilen)} Zeilen, {len(set(eans))} verschiedene EANs, "
          f"{ohne_ean} Zeilen ohne EAN")
    print(f"Bestand gesamt: {sum(z['buchbestand'] for z in zeilen)} Teile")
    print(f"Dateien in: {OUT_DIR}")


if __name__ == "__main__":
    main()
