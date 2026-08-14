"""Erzeugt einen druckbaren Barcode-Bogen (PDF) zum Testen der Scan-Erkennung.

Quelle ist samples/1_sollbestand_referenz.xlsx. Jeder Barcode wird nach dem
Rendern gegen die EAN aus der Datei geprueft - ein Bogen mit falschen Codes
waere schlimmer als gar keiner.

Seite 1  Scan-Testfaelle T1-T12 mit Erklaerung
Ab S. 2  Das komplette Sortiment, nach Marke gruppiert

Aufruf:  python scripts/generate_barcode_sheet.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.eanbc import Ean13BarcodeWidget
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_sample_data import (  # noqa: E402
    EAN_PRUEFZIFFER_FALSCH,
    EAN_UNBEKANNT,
    FILIALE,
    ean13_gueltig,
)

BASIS = Path(__file__).resolve().parent.parent
QUELLE = BASIS / "samples" / "1_sollbestand_referenz.xlsx"
ZIEL = BASIS / "samples" / "4_barcode_bogen.pdf"

SEITE_B, SEITE_H = A4
RAND = 12 * mm
SPALTEN = 3
KACHEL_B = 62 * mm
KACHEL_H = 40 * mm

BALKEN_BREITE = 0.36 * mm      # entspricht etwa SC2, gut fuer Kamera-Scans
BALKEN_HOEHE = 14 * mm

DUNKEL = HexColor("#1F3864")
GRAU = HexColor("#666666")
HELLGRAU = HexColor("#CCCCCC")
ROT = HexColor("#B03030")


# --------------------------------------------------------------------------

def lade_zeilen() -> list[dict]:
    ws = load_workbook(QUELLE)["Sollbestand"]
    kopf = [c.value for c in ws[1]]
    return [dict(zip(kopf, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]


def ean_zeichnung(ean13: str) -> Drawing:
    """EAN-13 als Drawing. Prueft, dass wirklich unsere EAN gedruckt wird.

    reportlab kuerzt einen 13-stelligen Wert auf 12 und berechnet die
    Pruefziffer selbst - deshalb die Kontrolle der tatsaechlich gesetzten
    Ziffern statt blindem Vertrauen.
    """
    widget = Ean13BarcodeWidget(
        value=ean13[:12],
        barHeight=BALKEN_HOEHE,
        barWidth=BALKEN_BREITE,
        humanReadable=1,
        fontSize=6.5,
    )
    gruppe = widget.draw()
    gedruckt = "".join(s.text for s in gruppe.contents if isinstance(s, String))
    if gedruckt != ean13:
        raise AssertionError(f"Barcode druckt {gedruckt!r}, erwartet {ean13!r}")

    x0, y0, x1, y1 = widget.getBounds()
    d = Drawing(x1 - x0, y1 - y0)
    d.add(widget)
    return d


def kachel(c, x: float, y: float, ean: str | None, zeile1: str, zeile2: str,
           marke: str | None = None, warnung: bool = False) -> None:
    """Zeichnet eine Kachel; (x, y) ist die linke untere Ecke."""
    c.setStrokeColor(HELLGRAU)
    c.setLineWidth(0.4)
    c.rect(x, y, KACHEL_B, KACHEL_H)

    if marke:
        c.setFont("Helvetica-Bold", 6)
        c.setFillColor(ROT if warnung else DUNKEL)
        c.drawString(x + 3 * mm, y + KACHEL_H - 6 * mm, marke.upper())

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(ROT if warnung else HexColor("#000000"))
    c.drawString(x + 3 * mm, y + KACHEL_H - 10 * mm, zeile1[:44])

    c.setFont("Helvetica", 6.5)
    c.setFillColor(GRAU)
    c.drawString(x + 3 * mm, y + KACHEL_H - 13.5 * mm, zeile2[:52])

    if ean is None:
        return

    if warnung:
        # Ungueltige Pruefziffer laesst sich nicht als EAN-13 drucken -
        # deshalb Code128, damit der Scanner die Ziffern trotzdem liefert.
        bc = code128.Code128(ean, barHeight=BALKEN_HOEHE,
                             barWidth=0.33 * mm, humanReadable=True)
        breite = bc.width
        bc.drawOn(c, x + (KACHEL_B - breite) / 2, y + 4 * mm)
    else:
        d = ean_zeichnung(ean)
        renderPDF.draw(d, c, x + (KACHEL_B - d.width) / 2, y + 4 * mm)


def seitenfuss(c, seite: int) -> None:
    c.setFont("Helvetica", 7)
    c.setFillColor(GRAU)
    c.drawString(RAND, 8 * mm,
                 f"Cult Fashion {FILIALE} – Barcode-Testbogen – "
                 f"in Originalgröße (100 %) drucken")
    c.drawRightString(SEITE_B - RAND, 8 * mm, f"Seite {seite}")


def raster(c, eintraege: list[dict], start_y: float, seite: int) -> int:
    """Setzt Kacheln ab start_y; legt bei Bedarf neue Seiten an."""
    y = start_y
    spalte = 0

    for e in eintraege:
        if y - KACHEL_H < 16 * mm:
            seitenfuss(c, seite)
            c.showPage()
            seite += 1
            y = SEITE_H - RAND - 6 * mm
            spalte = 0

        x = RAND + spalte * KACHEL_B
        kachel(c, x, y - KACHEL_H, e["ean"], e["zeile1"], e["zeile2"],
               marke=e.get("marke"), warnung=e.get("warnung", False))

        spalte += 1
        if spalte >= SPALTEN:
            spalte = 0
            y -= KACHEL_H

    if spalte:
        y -= KACHEL_H
    seitenfuss(c, seite)
    return seite


# --------------------------------------------------------------------------

def testfall_eintraege(zeilen: list[dict]) -> list[dict]:
    nach_ean: dict[str, list[dict]] = defaultdict(list)
    for z in zeilen:
        if z["EAN"]:
            nach_ean[z["EAN"]].append(z)

    def ean_von(**kriterien) -> str:
        for z in zeilen:
            if all(z[k] == v for k, v in kriterien.items()) and z["EAN"]:
                return z["EAN"]
        raise LookupError(kriterien)

    normal = ean_von(Artikelnummer="6620-1234", Größe="38", Farbnummer="101")
    tasche = ean_von(Artikelnummer="3011990", Farbnummer="900")
    loop = ean_von(Artikelnummer="3014477", Farbnummer="055")
    guertel = ean_von(Artikelnummer="6300-5511", Farbnummer="900")
    doppelt = ean_von(Artikelnummer="15195681", Größe="M", Farbnummer="101")
    negativ = ean_von(Artikelnummer="332-1200", Größe="40/32", Farbnummer="610")

    def beschr(ean: str) -> str:
        treffer = nach_ean[ean]
        z = treffer[0]
        if len(treffer) > 1:
            return f"{len(treffer)} Farben · {z['Größe']}"
        return f"{z['Farbe']} ({z['Farbnummer']}) · Gr. {z['Größe']}"

    def name(ean: str) -> str:
        return nach_ean[ean][0]["Artikelname"]

    def marke(ean: str) -> str:
        return nach_ean[ean][0]["Marke"]

    return [
        {"ean": normal, "marke": f"T1 · {marke(normal)}",
         "zeile1": name(normal), "zeile2": f"{beschr(normal)} – eindeutig, sofort +1"},
        {"ean": tasche, "marke": f"T2 · {marke(tasche)}",
         "zeile1": name(tasche), "zeile2": f"{beschr(tasche)} – Farbauswahl nötig"},
        {"ean": loop, "marke": f"T3 · {marke(loop)}",
         "zeile1": name(loop), "zeile2": f"{beschr(loop)} – Farbauswahl nötig"},
        {"ean": guertel, "marke": f"T4 · {marke(guertel)}",
         "zeile1": name(guertel), "zeile2": f"{beschr(guertel)} – EAN mit führender Null"},
        {"ean": doppelt, "marke": f"T5 · {marke(doppelt)}",
         "zeile1": name(doppelt),
         "zeile2": "Datenfehler – gleiche EAN auch auf: " + ", ".join(
             sorted({f"{t['Artikelname']} ({t['Marke']})"
                     for t in nach_ean[doppelt]
                     if t["Artikelname"] != name(doppelt)}))},
        {"ean": None, "marke": "T6 · ohne EAN",
         "zeile1": "Kleid Wilana · Gr. 38",
         "zeile2": "kein Barcode vorhanden – nur über Suche zählbar"},
        {"ean": EAN_UNBEKANNT, "marke": "T7 · unbekannt",
         "zeile1": "Nicht im Sortiment",
         "zeile2": "gültige EAN, steht nicht in der Importdatei"},
        {"ean": negativ, "marke": f"T8 · {marke(negativ)}",
         "zeile1": name(negativ), "zeile2": f"{beschr(negativ)} – Buchbestand −2"},
        {"ean": normal, "marke": "T10/T11 · Serie",
         "zeile1": name(normal),
         "zeile2": "zweimal schnell scannen, dann Storno testen"},
        {"ean": EAN_PRUEFZIFFER_FALSCH, "marke": "T12 · ungültig", "warnung": True,
         "zeile1": "Prüfziffer falsch",
         "zeile2": "muss abgewiesen werden (Code 128, kein EAN-13)"},
    ]


def sortiment_eintraege(zeilen: list[dict]) -> list[dict]:
    nach_ean: dict[str, list[dict]] = defaultdict(list)
    for z in zeilen:
        if z["EAN"]:
            nach_ean[z["EAN"]].append(z)

    eintraege = []
    for ean, treffer in nach_ean.items():
        z = treffer[0]
        if len(treffer) > 1 and len({t["Farbe"] for t in treffer}) > 1:
            zeile2 = f"{len(treffer)} Farben · {z['Größe']}"
        else:
            zeile2 = f"{z['Farbe']} ({z['Farbnummer']}) · Gr. {z['Größe']}"
        eintraege.append({
            "ean": ean,
            "marke": z["Marke"],
            "zeile1": z["Artikelname"],
            "zeile2": f"{zeile2} · {z['VK-Preis']:.2f} €".replace(".", ","),
            "_sort": (z["Marke"], z["Artikelnummer"], z["Farbnummer"], z["Größe"]),
        })

    eintraege.sort(key=lambda e: e["_sort"])
    return eintraege


def deckblatt_text(c, zeilen: list[dict]) -> float:
    ohne_ean = sum(1 for z in zeilen if not z["EAN"])

    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(DUNKEL)
    c.drawString(RAND, SEITE_H - RAND - 6 * mm, "Inventur-Scanner – Barcode-Testbogen")

    c.setFont("Helvetica", 8.5)
    c.setFillColor(GRAU)
    zeilen_text = [
        f"Cult Fashion {FILIALE} · Testdaten aus 1_sollbestand_referenz.xlsx",
        "Alle Codes sind gültige EAN-13 mit korrekter Prüfziffer – außer T12, der ist absichtlich kaputt.",
        "Wichtig: in Originalgröße (100 %) drucken, nicht „an Seite anpassen“. Sonst stimmt die Modulbreite nicht.",
        f"Vom Bildschirm scannen geht auch – Helligkeit hoch. {ohne_ean} Artikel haben bewusst keine EAN.",
    ]
    y = SEITE_H - RAND - 12 * mm
    for t in zeilen_text:
        c.drawString(RAND, y, t)
        y -= 4.2 * mm

    y -= 3 * mm
    c.setFont("Helvetica-Bold", 9.5)
    c.setFillColor(DUNKEL)
    c.drawString(RAND, y, "Seite 1 – Testfälle")
    return y - 4 * mm


def main() -> None:
    zeilen = lade_zeilen()

    for z in zeilen:
        if z["EAN"]:
            assert ean13_gueltig(z["EAN"]), f"ungültige EAN in der Quelle: {z['EAN']}"

    c = pdfcanvas.Canvas(str(ZIEL), pagesize=A4)
    c.setTitle("Inventur-Scanner – Barcode-Testbogen")

    seite = raster(c, testfall_eintraege(zeilen), deckblatt_text(c, zeilen), seite=1)

    c.showPage()
    seite += 1
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(DUNKEL)
    c.drawString(RAND, SEITE_H - RAND - 4 * mm, "Sortiment – alle EANs")
    sortiment = sortiment_eintraege(zeilen)
    seite = raster(c, sortiment, SEITE_H - RAND - 10 * mm, seite)

    c.save()
    print(f"{len(sortiment)} Barcodes auf {seite} Seiten -> {ZIEL}")


if __name__ == "__main__":
    main()
