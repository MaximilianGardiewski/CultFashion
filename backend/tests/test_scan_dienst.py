"""Die Scan-Testfaelle T1-T12 aus samples/3_scan_testfaelle.xlsx als Tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.tabellen import ScanEvent, Sollposition
from app.dienste import auswertung as auswertung_modul
from app.dienste import scan_dienst
from app.domain.werte import Erfassungsart, InventurStatus, ScanErgebnis

EAN_NORMAL = "4053121000035"          # Opus Bluse Falia, offwhite, Gr. 38
EAN_TASCHE = "4184711001658"          # eine EAN fuer vier Farben
EAN_GUERTEL = "0531201001676"         # fuehrende Null
EAN_DOPPELT = "5733551001282"         # zwei verschiedene Artikel
EAN_UNBEKANNT = "4014819072505"       # gueltig, nicht im Sortiment
EAN_KAPUTT = "4012345678902"          # Pruefziffer falsch


def _position(sitzung, inventur, **kriterien) -> Sollposition:
    abfrage = select(Sollposition).where(Sollposition.inventur_id == inventur.id)
    for feld, wert in kriterien.items():
        abfrage = abfrage.where(getattr(Sollposition, feld) == wert)
    treffer = sitzung.scalars(abfrage).first()
    assert treffer is not None, f"Position nicht gefunden: {kriterien}"
    return treffer


# -- T1 ------------------------------------------------------------------

def test_t1_eindeutiger_scan_bucht_sofort(sitzung, inventur_mit_bestand, bereich):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL,
                                 erfasst_von="Anna", zaehlbereich_id=bereich.id)

    assert antwort.ergebnis is ScanErgebnis.EINDEUTIG
    assert antwort.position.artikelname == "Bluse Falia"
    assert antwort.position.groesse == "38"
    assert antwort.gezaehlt == 1
    assert antwort.event_id is not None


def test_t1_zweiter_scan_zaehlt_hoch(sitzung, inventur_mit_bestand, bereich):
    for _ in range(3):
        antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL,
                                     zaehlbereich_id=bereich.id)
    assert antwort.gezaehlt == 3


def test_scan_setzt_inventur_auf_laufend(sitzung, inventur_mit_bestand):
    assert inventur_mit_bestand.status == InventurStatus.BEREIT.value
    scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)
    assert inventur_mit_bestand.status == InventurStatus.LAEUFT.value


# -- T2 / T3 -------------------------------------------------------------

def test_t2_mehrdeutige_ean_bucht_noch_nicht(sitzung, inventur_mit_bestand, bereich):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_TASCHE,
                                 zaehlbereich_id=bereich.id)

    assert antwort.ergebnis is ScanErgebnis.MEHRDEUTIG
    assert len(antwort.kandidaten) == 4
    assert {k.farbe for k in antwort.kandidaten} == {"black", "camel", "navy", "bordeaux"}
    assert antwort.event_id is None

    # nichts gebucht, solange nicht klar ist, welche Farbe gemeint war
    assert sitzung.scalar(select(ScanEvent).where(
        ScanEvent.inventur_id == inventur_mit_bestand.id)) is None


def test_t2_auswahl_bucht_die_gewaehlte_farbe(sitzung, inventur_mit_bestand, bereich):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_TASCHE)
    camel = next(k for k in antwort.kandidaten if k.farbe == "camel")

    gebucht = scan_dienst.buche_position(
        sitzung, inventur_mit_bestand, camel.id, zaehlbereich_id=bereich.id,
        erfasst_von="Anna", roh_code=EAN_TASCHE)

    assert gebucht.ergebnis is ScanErgebnis.EINDEUTIG
    assert gebucht.position.farbe == "camel"
    assert gebucht.gezaehlt == 1

    andere = [k for k in antwort.kandidaten if k.farbe != "camel"]
    for k in andere:
        assert scan_dienst.gezaehlte_menge(sitzung, k.id) == 0


# -- T4 ------------------------------------------------------------------

def test_t4_ean_mit_fuehrender_null_wird_gefunden(sitzung, inventur_mit_bestand):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_GUERTEL)
    assert antwort.ergebnis is ScanErgebnis.EINDEUTIG
    assert antwort.position.artikelname == "Gürtel Basic"


def test_t4_scanner_ohne_fuehrende_null_findet_trotzdem(sitzung, inventur_mit_bestand):
    """Manche Scanner liefern 12 Stellen - das muss derselbe Artikel sein."""
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, "531201001676")
    assert antwort.ergebnis is ScanErgebnis.EINDEUTIG
    assert antwort.position.artikelname == "Gürtel Basic"


# -- T5 ------------------------------------------------------------------

def test_t5_doppelte_ean_auf_zwei_artikeln(sitzung, inventur_mit_bestand):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_DOPPELT)

    assert antwort.ergebnis is ScanErgebnis.MEHRDEUTIG
    assert {k.artikelname for k in antwort.kandidaten} == \
           {"Top Onlmoster", "Bluse Vmbeauty"}


# -- T6 ------------------------------------------------------------------

def test_t6_artikel_ohne_ean_ueber_suche_zaehlbar(sitzung, inventur_mit_bestand, bereich):
    treffer = scan_dienst.suche(sitzung, inventur_mit_bestand, "Wilana")
    ohne_ean = [p for p in treffer if p.ean is None]
    assert ohne_ean, "Kleid Wilana ohne EAN nicht gefunden"

    position = ohne_ean[0]
    antwort = scan_dienst.buche_position(
        sitzung, inventur_mit_bestand, position.id,
        erfassungsart=Erfassungsart.MANUELL, erfasst_von="Anna",
        zaehlbereich_id=bereich.id)

    assert antwort.gezaehlt == 1
    event = sitzung.get(ScanEvent, antwort.event_id)
    assert event.erfassungsart == Erfassungsart.MANUELL.value


def test_suche_findet_ueber_marke_und_farbe(sitzung, inventur_mit_bestand):
    assert scan_dienst.suche(sitzung, inventur_mit_bestand, "angels")
    assert scan_dienst.suche(sitzung, inventur_mit_bestand, "bordeaux")
    assert scan_dienst.suche(sitzung, inventur_mit_bestand, "a") == []   # zu kurz


# -- T7 ------------------------------------------------------------------

def test_t7_unbekannte_ean_wird_trotzdem_erfasst(sitzung, inventur_mit_bestand, bereich):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_UNBEKANNT,
                                 zaehlbereich_id=bereich.id)

    assert antwort.ergebnis is ScanErgebnis.UNBEKANNT
    assert antwort.event_id is not None          # Zaehlung wird NICHT blockiert

    event = sitzung.get(ScanEvent, antwort.event_id)
    assert event.sollposition_id is None
    assert event.ean == EAN_UNBEKANNT


def test_t7_unbekannte_tauchen_in_der_auswertung_auf(sitzung, inventur_mit_bestand):
    scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_UNBEKANNT)
    scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_UNBEKANNT)

    a = auswertung_modul.erstelle(sitzung, inventur_mit_bestand)
    assert len(a.unbekannte) == 1
    assert a.unbekannte[0].ean == EAN_UNBEKANNT
    assert a.unbekannte[0].menge == 2
    assert a.kennzahlen.unbekannte_teile == 2


# -- T8 ------------------------------------------------------------------

def test_t8_negativer_buchbestand(sitzung, inventur_mit_bestand):
    position = _position(sitzung, inventur_mit_bestand,
                         artikelnummer="332-1200", groesse="40/32", farbnummer="610")
    assert position.buchbestand == -2

    scan_dienst.buche_position(sitzung, inventur_mit_bestand, position.id)

    a = auswertung_modul.erstelle(sitzung, inventur_mit_bestand)
    d = next(d for d in a.differenzen if d.position.id == position.id)
    assert d.gezaehlt == 1
    assert d.differenz == 3          # 1 gezaehlt - (-2) gebucht


# -- T9 ------------------------------------------------------------------

def test_t9_buchbestand_null_ergibt_ueberbestand(sitzung, inventur_mit_bestand):
    position = sitzung.scalars(
        select(Sollposition)
        .where(Sollposition.inventur_id == inventur_mit_bestand.id,
               Sollposition.buchbestand == 0)).first()
    assert position is not None

    scan_dienst.buche_position(sitzung, inventur_mit_bestand, position.id)

    a = auswertung_modul.erstelle(sitzung, inventur_mit_bestand)
    d = next(d for d in a.differenzen if d.position.id == position.id)
    assert d.differenz == 1
    assert a.kennzahlen.ueberbestand >= 1


# -- T10 / T11 -----------------------------------------------------------

def test_t10_doppelscan_zaehlt_zweimal(sitzung, inventur_mit_bestand):
    """Zwei Scans sind zwei Teile. Entprellung gehoert in die Kamera, nicht hierher."""
    a1 = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)
    a2 = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)

    assert a1.gezaehlt == 1
    assert a2.gezaehlt == 2


def test_t11_storno_bucht_gegen_statt_zu_loeschen(sitzung, inventur_mit_bestand):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)
    position_id = antwort.position.id

    storno = scan_dienst.storniere(sitzung, inventur_mit_bestand, antwort.event_id)

    assert storno.gezaehlt == 0
    events = list(sitzung.scalars(
        select(ScanEvent).where(ScanEvent.sollposition_id == position_id)))
    assert len(events) == 2, "Das Log muss beide Buchungen behalten"
    assert sorted(e.menge for e in events) == [-1, 1]
    assert storno.event_id != antwort.event_id


def test_t11_doppeltes_storno_wird_abgewiesen(sitzung, inventur_mit_bestand):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)
    scan_dienst.storniere(sitzung, inventur_mit_bestand, antwort.event_id)

    with pytest.raises(scan_dienst.ScanFehler, match="bereits storniert"):
        scan_dienst.storniere(sitzung, inventur_mit_bestand, antwort.event_id)


def test_t11_storno_eines_stornos_wird_abgewiesen(sitzung, inventur_mit_bestand):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)
    storno = scan_dienst.storniere(sitzung, inventur_mit_bestand, antwort.event_id)

    with pytest.raises(scan_dienst.ScanFehler):
        scan_dienst.storniere(sitzung, inventur_mit_bestand, storno.event_id)


# -- T12 -----------------------------------------------------------------

def test_t12_falsche_pruefziffer_wird_abgewiesen(sitzung, inventur_mit_bestand):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_KAPUTT)

    assert antwort.ergebnis is ScanErgebnis.UNGUELTIG
    assert antwort.event_id is None

    # Entscheidend: NICHT als unbekannter Artikel verbucht
    assert sitzung.scalar(select(ScanEvent).where(
        ScanEvent.inventur_id == inventur_mit_bestand.id)) is None


def test_t12_muell_wird_abgewiesen(sitzung, inventur_mit_bestand):
    for muell in ("", "   ", "abc", "12"):
        antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, muell)
        assert antwort.ergebnis is ScanErgebnis.UNGUELTIG


# -- Mehrere Zaehler -----------------------------------------------------

def test_zwei_bereiche_zaehlen_denselben_artikel(sitzung, inventur_mit_bestand):
    """Kein verlorenes Update: die Mengen addieren sich sauber."""
    from app.db.tabellen import Zaehlbereich

    flaeche = Zaehlbereich(inventur_id=inventur_mit_bestand.id, name="Fläche")
    lager = Zaehlbereich(inventur_id=inventur_mit_bestand.id, name="Lager")
    sitzung.add_all([flaeche, lager])
    sitzung.commit()

    scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL,
                       zaehlbereich_id=flaeche.id, erfasst_von="Anna")
    scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL,
                       zaehlbereich_id=lager.id, erfasst_von="Bea")
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL,
                                 zaehlbereich_id=flaeche.id, erfasst_von="Anna")

    assert antwort.gezaehlt == 3


def test_buchung_fremder_inventur_wird_abgewiesen(sitzung, inventur_mit_bestand):
    from app.db.tabellen import Inventur

    andere = Inventur(filial_nr="13", filiale="Woanders", bezeichnung="Andere")
    sitzung.add(andere)
    sitzung.commit()

    position = _position(sitzung, inventur_mit_bestand, artikelnummer="6620-1234")
    with pytest.raises(scan_dienst.ScanFehler):
        scan_dienst.buche_position(sitzung, andere, position.id)


# -- Vorbedingungen einer Buchung (aus dem PR-Review) --------------------

def test_scan_ohne_importierten_sollbestand_wird_abgewiesen(sitzung, inventur):
    """Sonst haenge die Inventur: der Import verweigert danach dauerhaft,
    weil er bereits Scans sieht."""
    with pytest.raises(scan_dienst.ScanFehler, match="kein Sollbestand"):
        scan_dienst.scanne(sitzung, inventur, EAN_NORMAL)

    assert sitzung.scalar(select(ScanEvent)) is None


def test_import_bleibt_nach_abgewiesenem_scan_moeglich(sitzung, inventur):
    from app.dienste.import_dienst import importiere
    from app.quellen.excel import ExcelBestandsQuelle
    from tests.conftest import REFERENZ

    with pytest.raises(scan_dienst.ScanFehler):
        scan_dienst.scanne(sitzung, inventur, EAN_NORMAL)

    ergebnis, _ = importiere(sitzung, inventur, ExcelBestandsQuelle(REFERENZ), "x.xlsx")
    assert len(ergebnis.positionen) == 173


def test_scan_in_abgeschlossene_inventur_wird_abgewiesen(sitzung, inventur_mit_bestand):
    inventur_mit_bestand.status = InventurStatus.ABGESCHLOSSEN.value
    sitzung.commit()

    with pytest.raises(scan_dienst.ScanFehler, match="abgeschlossen"):
        scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)


def test_storno_in_abgeschlossener_inventur_wird_abgewiesen(sitzung, inventur_mit_bestand):
    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)
    inventur_mit_bestand.status = InventurStatus.ABGESCHLOSSEN.value
    sitzung.commit()

    with pytest.raises(scan_dienst.ScanFehler, match="abgeschlossen"):
        scan_dienst.storniere(sitzung, inventur_mit_bestand, antwort.event_id)


@pytest.mark.parametrize("menge", [0, -1, -5])
def test_nicht_positive_menge_wird_abgewiesen(sitzung, inventur_mit_bestand, menge):
    """Negative Mengen wuerden am Storno vorbei den Bestand druecken."""
    with pytest.raises(scan_dienst.ScanFehler, match="größer als 0"):
        scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL, menge=menge)

    position = _position(sitzung, inventur_mit_bestand, artikelnummer="6620-1234")
    with pytest.raises(scan_dienst.ScanFehler, match="größer als 0"):
        scan_dienst.buche_position(sitzung, inventur_mit_bestand, position.id, menge=menge)


def test_fremder_zaehlbereich_wird_abgewiesen(sitzung, inventur_mit_bestand):
    """Sonst faellt die Zaehlung aus beiden Bereichsuebersichten heraus."""
    from app.db.tabellen import Inventur, Zaehlbereich

    andere = Inventur(filial_nr="13", filiale="Woanders", bezeichnung="Andere")
    sitzung.add(andere)
    sitzung.commit()
    fremd = Zaehlbereich(inventur_id=andere.id, name="Fremdfläche")
    sitzung.add(fremd)
    sitzung.commit()

    with pytest.raises(scan_dienst.ScanFehler, match="Zählbereich"):
        scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL,
                           zaehlbereich_id=fremd.id)

    with pytest.raises(scan_dienst.ScanFehler, match="Zählbereich"):
        scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL,
                           zaehlbereich_id=999999)


def test_gleichzeitiges_storno_zieht_nur_einmal_ab(sitzung, inventur_mit_bestand):
    """Zwei Geraete stornieren denselben Scan - die Datenbank laesst nur eines durch."""
    from sqlalchemy.exc import IntegrityError

    from app.db.tabellen import ScanEvent as Event

    antwort = scan_dienst.scanne(sitzung, inventur_mit_bestand, EAN_NORMAL)
    scan_dienst.storniere(sitzung, inventur_mit_bestand, antwort.event_id)

    # Das zweite Geraet hatte die Pruefung schon passiert und schreibt direkt.
    sitzung.add(Event(inventur_id=inventur_mit_bestand.id,
                      sollposition_id=antwort.position.id, menge=-1,
                      erfassungsart=Erfassungsart.STORNO.value,
                      storniert_event_id=antwort.event_id))
    with pytest.raises(IntegrityError):
        sitzung.commit()
    sitzung.rollback()

    assert scan_dienst.gezaehlte_menge(sitzung, antwort.position.id) == 0
