"""Excel-Import des Sollbestands.

Der Export aus advarics ist ein Report, keine saubere Tabelle: Titelzeilen
vorweg, Zwischensummen je Marke, Leerzeilen, Preise als Text und EANs, denen
Excel die fuehrende Null abgeschnitten hat. Der Import sucht sich deshalb die
Kopfzeile selbst, ordnet Spalten ueber Synonyme zu und wirft alles weg, was
keine Artikelzeile ist - statt ein bestimmtes Layout vorauszusetzen.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from openpyxl import load_workbook

from app.domain.ean import ist_gueltig, normalisiere
from app.quellen.protokoll import Ladeergebnis, RohPosition

# Feld -> moegliche Spaltenueberschriften (normalisiert, siehe _schluessel)
SPALTEN_SYNONYME: dict[str, tuple[str, ...]] = {
    "ean": ("ean", "eancode", "eannr", "eannummer", "barcode", "gtin", "ean13",
            "artikelbarcode"),
    "artikelnummer": ("artikelnummer", "artnr", "artikelnr", "artikelnummerlieferant",
                      "modellnummer", "modellnr", "lieferantenartikelnummer"),
    "artikelname": ("artikelname", "bezeichnung", "artikelbezeichnung", "name",
                    "modell", "modellname"),
    "marke": ("marke", "brand", "lieferant", "hersteller"),
    "warengruppe": ("warengruppe", "wgr", "wg", "warengr", "kategorie"),
    "farbnummer": ("farbnummer", "farbnr", "farbcode", "farbschluessel"),
    "farbe": ("farbe", "farbbezeichnung", "color", "farbtext"),
    "groesse": ("groesse", "gr", "size", "groessenbezeichnung"),
    "vk_preis": ("vkpreis", "vkbrutto", "vk", "preis", "verkaufspreis", "vkbrutto1",
                 "endpreis", "ladenpreis"),
    "buchbestand": ("buchbestand", "bestand", "menge", "lagerbestand", "sollbestand",
                    "bestandmenge", "istbestand"),
    "saison": ("saison", "season", "saisoncode"),
}

PFLICHTFELDER = ("artikelnummer", "groesse")

# Zeilen, die zwar in der Artikelspalte etwas stehen haben, aber keine Artikel sind
SUMMEN_MUSTER = re.compile(
    r"^\s*(summe|zwischensumme|gesamtsumme|gesamt|total|anzahl|seite)\b", re.I)

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                          "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def _schluessel(text: object) -> str:
    """Ueberschrift auf eine vergleichbare Form bringen: 'Art.-Nr.' -> 'artnr'."""
    if text is None:
        return ""
    roh = str(text).strip().lower().translate(_UMLAUTE)
    roh = unicodedata.normalize("NFKD", roh)
    return re.sub(r"[^a-z0-9]", "", roh)


def _text(wert: object) -> str:
    if wert is None:
        return ""
    if isinstance(wert, float) and wert.is_integer():
        return str(int(wert))
    return str(wert).strip()


def lies_preis(wert: object) -> float:
    """'79,99 €' / '1.234,56' / 79.99 -> float."""
    if wert is None or wert == "":
        return 0.0
    if isinstance(wert, (int, float)):
        return float(wert)

    text = str(wert).strip()
    text = re.sub(r"[^\d,.\-]", "", text)      # Waehrungszeichen, Leerzeichen weg
    if not text:
        return 0.0

    if "," in text and "." in text:
        # deutsches Format: Punkt ist Tausendertrenner
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return 0.0


def lies_menge(wert: object) -> int | None:
    if wert is None or wert == "":
        return None
    if isinstance(wert, (int, float)):
        return int(wert)
    text = str(wert).strip().replace(".", "").replace(",", ".")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


class ExcelBestandsQuelle:
    """Liest den Sollbestand aus einer Excel-Datei."""

    def __init__(self, pfad: str | Path, blatt: str | None = None,
                 max_kopfsuche: int = 30) -> None:
        self.pfad = Path(pfad)
        self.blatt = blatt
        self.max_kopfsuche = max_kopfsuche

    # -- Kopfzeile finden -------------------------------------------------

    def _finde_kopf(self, ws) -> tuple[int, dict[str, int], list[str]]:
        """Sucht die Zeile, die am meisten wie eine Kopfzeile aussieht."""
        bester: tuple[int, dict[str, int]] = (0, {})
        beste_zeile = 0

        for zeilennr, zeile in enumerate(
                ws.iter_rows(min_row=1, max_row=self.max_kopfsuche), start=1):
            zuordnung: dict[str, int] = {}
            for spaltennr, zelle in enumerate(zeile, start=1):
                schluessel = _schluessel(zelle.value)
                if not schluessel:
                    continue
                for feld, synonyme in SPALTEN_SYNONYME.items():
                    if feld not in zuordnung and schluessel in synonyme:
                        zuordnung[feld] = spaltennr
                        break

            if len(zuordnung) > len(bester[1]):
                bester = (zeilennr, zuordnung)
                beste_zeile = zeilennr

        zeilennr, zuordnung = beste_zeile, bester[1]
        fehlend = [f for f in PFLICHTFELDER if f not in zuordnung]
        if fehlend or len(zuordnung) < 4:
            raise ValueError(
                "Keine brauchbare Kopfzeile gefunden. Erkannt: "
                f"{sorted(zuordnung) or 'nichts'}; fehlende Pflichtspalten: {fehlend}. "
                "Erwartet werden mindestens Artikelnummer und Größe."
            )
        return zeilennr, zuordnung, fehlend

    # -- Laden ------------------------------------------------------------

    def lade(self) -> Ladeergebnis:
        wb = load_workbook(self.pfad, data_only=True)
        ws = wb[self.blatt] if self.blatt else self._waehle_blatt(wb)

        kopfzeile, zuordnung, _ = self._finde_kopf(ws)
        ergebnis = Ladeergebnis(
            spaltenzuordnung={feld: ws.cell(row=kopfzeile, column=nr).value or ""
                              for feld, nr in zuordnung.items()},
        )

        for feld in ("ean", "marke", "farbe", "farbnummer", "vk_preis", "buchbestand"):
            if feld not in zuordnung:
                ergebnis.hinweise.append(
                    f"Spalte '{feld}' nicht gefunden – wird leer übernommen.")

        gesehen: dict[tuple[str, str, str], int] = {}

        def hole(zeile, feld: str):
            nr = zuordnung.get(feld)
            return zeile[nr - 1].value if nr and nr <= len(zeile) else None

        for zeilennr, zeile in enumerate(
                ws.iter_rows(min_row=kopfzeile + 1), start=kopfzeile + 1):
            if all(z.value in (None, "") for z in zeile):
                continue

            ergebnis.zeilen_gelesen += 1
            artikelnummer = _text(hole(zeile, "artikelnummer"))
            artikelname = _text(hole(zeile, "artikelname"))

            if not artikelnummer:
                # Zwischensummen tragen den Text oft in der Bezeichnungsspalte
                if artikelname and SUMMEN_MUSTER.match(artikelname):
                    ergebnis.zeilen_uebersprungen += 1
                    continue
                ergebnis.zeilen_uebersprungen += 1
                continue

            if SUMMEN_MUSTER.match(artikelnummer) or SUMMEN_MUSTER.match(artikelname):
                ergebnis.zeilen_uebersprungen += 1
                continue

            groesse = _text(hole(zeile, "groesse"))
            if not groesse:
                ergebnis.zeilen_uebersprungen += 1
                ergebnis.hinweise.append(f"Zeile {zeilennr}: keine Größe – übersprungen.")
                continue

            menge = lies_menge(hole(zeile, "buchbestand"))
            if menge is None:
                menge = 0
                ergebnis.hinweise.append(
                    f"Zeile {zeilennr}: Bestand nicht lesbar – als 0 übernommen.")

            ean = normalisiere(hole(zeile, "ean"))
            if ean and not ist_gueltig(ean):
                ergebnis.hinweise.append(
                    f"Zeile {zeilennr}: EAN {ean} hat eine falsche Prüfziffer – "
                    "übernommen, aber nicht scanbar.")

            farbnummer = _text(hole(zeile, "farbnummer"))
            schluessel = (artikelnummer, farbnummer, groesse)
            if schluessel in gesehen:
                ergebnis.zeilen_uebersprungen += 1
                ergebnis.hinweise.append(
                    f"Zeile {zeilennr}: Artikel {artikelnummer}/{farbnummer}/{groesse} "
                    f"steht schon in Zeile {gesehen[schluessel]} – zweites Vorkommen "
                    "übersprungen.")
                continue
            gesehen[schluessel] = zeilennr

            ergebnis.positionen.append(RohPosition(
                artikelnummer=artikelnummer,
                artikelname=artikelname or artikelnummer,
                marke=_text(hole(zeile, "marke")) or "—",
                farbnummer=farbnummer,
                farbe=_text(hole(zeile, "farbe")),
                groesse=groesse,
                buchbestand=menge,
                vk_preis=lies_preis(hole(zeile, "vk_preis")),
                ean=ean,
                warengruppe=_text(hole(zeile, "warengruppe")) or None,
                saison=_text(hole(zeile, "saison")) or None,
                quellzeile=zeilennr,
            ))

        return ergebnis

    @staticmethod
    def _waehle_blatt(wb):
        """Nimmt das Blatt mit den meisten Zeilen - Beschreibungsblaetter sind kurz."""
        return max(wb.worksheets, key=lambda ws: ws.max_row or 0)
