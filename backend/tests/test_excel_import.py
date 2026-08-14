"""Import beider Beispieldateien - besonders des unsauberen Rohexports."""

from __future__ import annotations

from app.domain.ean import ist_gueltig
from app.quellen.excel import ExcelBestandsQuelle, lies_menge, lies_preis
from tests.conftest import REFERENZ, ROHEXPORT


def test_referenzdatei_vollstaendig():
    ergebnis = ExcelBestandsQuelle(REFERENZ).lade()

    assert len(ergebnis.positionen) == 173
    assert ergebnis.zeilen_uebersprungen == 0
    assert set(ergebnis.spaltenzuordnung) >= {
        "ean", "artikelnummer", "artikelname", "marke", "farbnummer",
        "farbe", "groesse", "vk_preis", "buchbestand"}


def test_referenzdatei_waehlt_datenblatt_nicht_feldbeschreibung():
    """Die Datei hat zwei Blaetter - das Beschreibungsblatt darf nicht gewinnen."""
    ergebnis = ExcelBestandsQuelle(REFERENZ).lade()
    assert ergebnis.spaltenzuordnung["artikelnummer"] == "Artikelnummer"


def test_rohexport_findet_kopfzeile_unter_titelzeilen():
    """Der Rohexport hat drei Titelzeilen und eine Leerzeile vor dem Kopf."""
    ergebnis = ExcelBestandsQuelle(ROHEXPORT).lade()

    assert ergebnis.spaltenzuordnung["artikelnummer"] == "Art.-Nr."
    assert ergebnis.spaltenzuordnung["groesse"] == "Gr."
    assert ergebnis.spaltenzuordnung["vk_preis"] == "VK Brutto"
    assert ergebnis.spaltenzuordnung["buchbestand"] == "Bestand"


def test_rohexport_liefert_dieselben_artikel_wie_die_referenz():
    referenz = ExcelBestandsQuelle(REFERENZ).lade()
    roh = ExcelBestandsQuelle(ROHEXPORT).lade()

    def schluessel(p):
        return (p.artikelnummer, p.farbnummer, p.groesse)

    assert {schluessel(p) for p in roh.positionen} == \
           {schluessel(p) for p in referenz.positionen}


def test_rohexport_wirft_zwischensummen_weg():
    """'Summe Opus' und 'Gesamtsumme' duerfen keine Artikel werden."""
    ergebnis = ExcelBestandsQuelle(ROHEXPORT).lade()

    namen = {p.artikelname.lower() for p in ergebnis.positionen}
    assert not any(n.startswith(("summe", "gesamt")) for n in namen)
    assert ergebnis.zeilen_uebersprungen >= 6      # 5 Marken + Gesamtsumme


def test_rohexport_stellt_fuehrende_null_wieder_her():
    """Im Rohexport steht die EAN teils als Zahl - die Null muss zurueck."""
    ergebnis = ExcelBestandsQuelle(ROHEXPORT).lade()

    guertel = [p for p in ergebnis.positionen if p.artikelnummer == "6300-5511"]
    assert guertel, "Gürtel Basic fehlt"
    for p in guertel:
        assert p.ean is not None and len(p.ean) == 13
        assert p.ean.startswith("0")
        assert ist_gueltig(p.ean)


def test_rohexport_liest_preise_mit_waehrung_und_komma():
    ergebnis = ExcelBestandsQuelle(ROHEXPORT).lade()

    bluse = next(p for p in ergebnis.positionen if p.artikelnummer == "6620-1234")
    assert bluse.vk_preis == 79.99


def test_rohexport_uebernimmt_negativen_bestand():
    ergebnis = ExcelBestandsQuelle(ROHEXPORT).lade()

    cici = next(p for p in ergebnis.positionen
                if p.artikelnummer == "332-1200" and p.groesse == "40/32"
                and p.farbnummer == "610")
    assert cici.buchbestand == -2


def test_artikel_ohne_ean_werden_importiert():
    """Ohne Etikett bleibt der Artikel zaehlbar - nur eben nicht scanbar."""
    ergebnis = ExcelBestandsQuelle(REFERENZ).lade()
    ohne = [p for p in ergebnis.positionen if not p.ean]
    assert len(ohne) == 3


def test_alle_importierten_eans_sind_gueltig():
    ergebnis = ExcelBestandsQuelle(REFERENZ).lade()
    ungueltig = [p.ean for p in ergebnis.positionen if p.ean and not ist_gueltig(p.ean)]
    assert ungueltig == []


def test_kopfzeile_nicht_gefunden_meldet_klar(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active["A1"] = "irgendwas"
    wb.active["A2"] = "ohne Struktur"
    pfad = tmp_path / "kaputt.xlsx"
    wb.save(pfad)

    try:
        ExcelBestandsQuelle(pfad).lade()
    except ValueError as fehler:
        assert "Kopfzeile" in str(fehler)
    else:
        raise AssertionError("ValueError erwartet")


class TestZahlenLesen:
    def test_preise(self):
        assert lies_preis("79,99 €") == 79.99
        assert lies_preis("1.234,56 €") == 1234.56
        assert lies_preis("79.99") == 79.99
        assert lies_preis(79.99) == 79.99
        assert lies_preis("") == 0.0
        assert lies_preis(None) == 0.0
        assert lies_preis("k.A.") == 0.0

    def test_mengen(self):
        assert lies_menge(3) == 3
        assert lies_menge("3") == 3
        assert lies_menge("-2") == -2
        assert lies_menge(3.0) == 3
        assert lies_menge("") is None
        assert lies_menge(None) is None


class TestZahlenAusTextzellen:
    """Aus dem PR-Review: '3.0' als Text wurde zu 30 - zehnfacher Bestand."""

    def test_dezimalpunkt_multipliziert_nicht(self):
        assert lies_menge("3.0") == 3
        assert lies_menge("12.0") == 12
        assert lies_preis("79.99") == 79.99

    def test_tausendertrenner_bleibt_erkannt(self):
        assert lies_menge("1.234") == 1234
        assert lies_preis("1.234,56") == 1234.56
        assert lies_preis("1.234") == 1234.0

    def test_komma_bleibt_dezimaltrenner(self):
        assert lies_menge("3,0") == 3
        assert lies_preis("79,99 €") == 79.99
