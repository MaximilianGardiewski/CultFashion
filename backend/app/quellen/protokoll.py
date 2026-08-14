"""Die eine Grenze zum Vorsystem.

Heute liefert advarics eine Excel-Datei, spaeter vielleicht die REST-API.
Alles, was danach kommt, kennt nur dieses Protokoll und die Klasse
RohPosition - kein Modul oberhalb dieser Datei weiss, woher die Daten stammen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class RohPosition:
    """Eine Sollbestandszeile, bereits normalisiert, noch nicht gespeichert."""

    artikelnummer: str
    artikelname: str
    marke: str
    farbnummer: str
    farbe: str
    groesse: str
    buchbestand: int
    vk_preis: float = 0.0
    ean: str | None = None
    warengruppe: str | None = None
    saison: str | None = None
    quellzeile: int = 0


@dataclass(slots=True)
class Ladeergebnis:
    positionen: list[RohPosition] = field(default_factory=list)
    zeilen_gelesen: int = 0
    zeilen_uebersprungen: int = 0
    spaltenzuordnung: dict[str, str] = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)


class BestandsQuelle(Protocol):
    """Liefert den Sollbestand einer Filiale."""

    def lade(self) -> Ladeergebnis: ...
