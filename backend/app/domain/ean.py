"""EAN-13: Normalisierung und Pruefziffer.

Die Codes kommen aus zwei Richtungen mit unterschiedlichen Macken:
Excel macht aus einer EAN gern eine Zahl (fuehrende Null weg, teils ".0" dran),
Scanner liefern manchmal Leerzeichen oder einen UPC-A mit 12 Stellen.
Beides muss auf dieselbe 13-stellige Form kommen, sonst findet die Suche nichts.
"""

from __future__ import annotations

import re

EAN_LAENGE = 13

_NUR_ZIFFERN = re.compile(r"\D")


def pruefziffer(basis12: str) -> str:
    """EAN-13 Pruefziffer nach GS1 (Gewichtung 1/3 von links)."""
    if len(basis12) != 12 or not basis12.isdigit():
        raise ValueError(f"12 Ziffern erwartet, bekommen: {basis12!r}")
    summe = sum(int(z) * (3 if i % 2 else 1) for i, z in enumerate(basis12))
    return str((10 - summe % 10) % 10)


def ist_gueltig(ean: str | None) -> bool:
    if not ean or len(ean) != EAN_LAENGE or not ean.isdigit():
        return False
    return pruefziffer(ean[:12]) == ean[12]


def normalisiere(roh: object) -> str | None:
    """Bringt einen Rohwert auf 13 Stellen. None, wenn nichts Zaehlbares drin steht.

    Prueft die Pruefziffer NICHT - das ist Aufgabe des Aufrufers, damit
    Importfehler und Scanfehler unterschiedlich behandelt werden koennen.
    """
    if roh is None:
        return None

    if isinstance(roh, float):
        # Excel liefert Zahlen als float: 4053121000035.0
        if roh != roh or roh in (float("inf"), float("-inf")):
            return None
        text = f"{roh:.0f}"
    elif isinstance(roh, int):
        text = str(roh)
    else:
        text = str(roh).strip().lstrip("'")
        if text.endswith(".0"):
            text = text[:-2]

    ziffern = _NUR_ZIFFERN.sub("", text)
    if not ziffern:
        return None

    if len(ziffern) < EAN_LAENGE:
        # Fuehrende Nullen sind unterwegs verloren gegangen. Das deckt auch
        # UPC-A (12 Stellen) ab - als GTIN-13 ist das dieselbe Nummer mit 0 davor.
        ziffern = ziffern.zfill(EAN_LAENGE)

    return ziffern
