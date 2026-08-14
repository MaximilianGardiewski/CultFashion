"""EAN-Normalisierung und Pruefziffer."""

from __future__ import annotations

import pytest

from app.domain.ean import ist_gueltig, normalisiere, pruefziffer


@pytest.mark.parametrize("basis,erwartet", [
    ("405312100003", "5"),
    ("053120100167", "6"),
    ("401481907250", "5"),
])
def test_pruefziffer(basis, erwartet):
    assert pruefziffer(basis) == erwartet


def test_gueltig_und_ungueltig():
    assert ist_gueltig("4053121000035")
    assert not ist_gueltig("4012345678902")   # Pruefziffer absichtlich falsch
    assert not ist_gueltig("405312100003")    # zu kurz
    assert not ist_gueltig("40531210000AB")
    assert not ist_gueltig(None)
    assert not ist_gueltig("")


@pytest.mark.parametrize("roh,erwartet", [
    ("4053121000035", "4053121000035"),
    (4053121000035, "4053121000035"),
    (4053121000035.0, "4053121000035"),          # Excel liefert float
    ("4053121000035.0", "4053121000035"),
    ("'4053121000035", "4053121000035"),         # Textmarker aus Excel
    ("  4053121000035  ", "4053121000035"),
    ("4053 1210 00035", "4053121000035"),        # Scanner mit Trennzeichen
    (531201001676, "0531201001676"),             # fuehrende Null verloren
    ("531201001676", "0531201001676"),
    ("", None),
    (None, None),
    ("   ", None),
    ("keine zahl", None),
])
def test_normalisiere(roh, erwartet):
    assert normalisiere(roh) == erwartet


def test_fuehrende_null_wird_wiederhergestellt():
    """Der haeufigste Importfehler: Excel macht aus der EAN eine Zahl."""
    aus_excel = 531201001676
    ean = normalisiere(aus_excel)
    assert ean == "0531201001676"
    assert ist_gueltig(ean)


def test_upc_a_wird_zu_gtin13():
    """12-stelliger UPC-A ist als GTIN-13 dieselbe Nummer mit Null davor."""
    assert normalisiere("036000291452") == "0036000291452"
