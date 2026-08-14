"""Fachliche Aufzaehlungen. Bewusst ohne Datenbank- oder API-Bezug."""

from __future__ import annotations

from enum import Enum


class InventurStatus(str, Enum):
    ANGELEGT = "angelegt"        # existiert, noch kein Sollbestand importiert
    BEREIT = "bereit"            # Sollbestand da, Zaehlung kann starten
    LAEUFT = "laeuft"            # mindestens ein Scan erfasst
    ABGESCHLOSSEN = "abgeschlossen"


class BereichStatus(str, Enum):
    OFFEN = "offen"
    LAEUFT = "laeuft"
    FERTIG = "fertig"


class Ebene(str, Enum):
    """Die Skizze der Filiale kennt zwei Ebenen.

    Gezaehlt wird auf Staender-Ebene; der Bereich fasst nur zusammen und
    traegt den Punkt auf der Karte.
    """

    BEREICH = "bereich"      # 100, 200, 300, Umkleide
    STAENDER = "staender"    # 101 ... 106


class Rolle(str, Enum):
    ZAEHLER = "zaehler"
    ADMIN = "admin"


class Dringlichkeit(int, Enum):
    SPAETER = 1      # kann bis zum Ende der Inventur warten
    BALD = 2         # sollte heute geklaert werden
    SOFORT = 3       # blockiert das Weiterzaehlen


class MarkierungStatus(str, Enum):
    OFFEN = "offen"
    ERLEDIGT = "erledigt"


class ScanErgebnis(str, Enum):
    """Was beim Aufloesen eines gescannten Codes herauskam."""

    EINDEUTIG = "eindeutig"      # genau ein Artikel -> sofort gebucht
    MEHRDEUTIG = "mehrdeutig"    # mehrere Artikel teilen die EAN -> Auswahl noetig
    UNBEKANNT = "unbekannt"      # gueltige EAN, steht nicht im Sollbestand
    UNGUELTIG = "ungueltig"      # Pruefziffer falsch / keine EAN


class Erfassungsart(str, Enum):
    SCAN = "scan"                # per Kamera erfasst
    AUSWAHL = "auswahl"          # nach mehrdeutigem Scan manuell zugeordnet
    MANUELL = "manuell"          # ueber die Suche erfasst, kein Barcode vorhanden
    STORNO = "storno"            # Gegenbuchung
