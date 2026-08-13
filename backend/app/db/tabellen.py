"""Datenbankschema.

Kernentscheidung: ScanEvent ist ein reines Anhaenge-Log. Es gibt keinen
Zaehler, der hochgesetzt wird - die gezaehlte Menge ist immer die Summe der
Events. Dadurch koennen mehrere Geraete gleichzeitig zaehlen, ohne sich
gegenseitig zu ueberschreiben, und eine Differenz laesst sich hinterher bis
auf den einzelnen Scan zurueckverfolgen. Ein Storno loescht nichts, sondern
bucht gegen.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.werte import BereichStatus, Erfassungsart, InventurStatus


class Basis(DeclarativeBase):
    pass


class Inventur(Basis):
    __tablename__ = "inventur"

    id: Mapped[int] = mapped_column(primary_key=True)
    filial_nr: Mapped[str] = mapped_column(String(10))
    filiale: Mapped[str] = mapped_column(String(120))
    bezeichnung: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=InventurStatus.ANGELEGT.value)
    angelegt_am: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    abgeschlossen_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    positionen: Mapped[list["Sollposition"]] = relationship(
        back_populates="inventur", cascade="all, delete-orphan")
    bereiche: Mapped[list["Zaehlbereich"]] = relationship(
        back_populates="inventur", cascade="all, delete-orphan")


class Sollposition(Basis):
    """Eine Zeile aus dem advarics-Export: Artikel in einer Farbe in einer Groesse.

    Fachliche Identitaet ist (artikelnummer, farbnummer, groesse) - NICHT die EAN.
    Die EAN ist nur der Scan-Schluessel: sie darf fehlen und sie darf auf
    mehrere Positionen zeigen (z. B. eine Tasche in vier Farben).
    """

    __tablename__ = "sollposition"
    __table_args__ = (
        UniqueConstraint("inventur_id", "artikelnummer", "farbnummer", "groesse",
                         name="uq_sollposition_sku"),
        Index("ix_sollposition_ean", "inventur_id", "ean"),
        Index("ix_sollposition_suche", "inventur_id", "artikelnummer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inventur_id: Mapped[int] = mapped_column(ForeignKey("inventur.id", ondelete="CASCADE"))

    ean: Mapped[str | None] = mapped_column(String(13), nullable=True)
    artikelnummer: Mapped[str] = mapped_column(String(40))
    artikelname: Mapped[str] = mapped_column(String(160))
    marke: Mapped[str] = mapped_column(String(60))
    warengruppe: Mapped[str | None] = mapped_column(String(60), nullable=True)
    farbnummer: Mapped[str] = mapped_column(String(20))
    farbe: Mapped[str] = mapped_column(String(60))
    groesse: Mapped[str] = mapped_column(String(20))
    vk_preis: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    buchbestand: Mapped[int] = mapped_column(Integer, default=0)
    saison: Mapped[str | None] = mapped_column(String(20), nullable=True)

    inventur: Mapped[Inventur] = relationship(back_populates="positionen")

    @property
    def bezeichnung(self) -> str:
        return f"{self.marke} {self.artikelname} · {self.farbe} · Gr. {self.groesse}"


class Zaehlbereich(Basis):
    """Abgegrenzte Flaeche (Verkauf, Lager, Schaufenster ...).

    Ein Bereich wird von einer Person gezaehlt - das ist die einzige wirksame
    Massnahme gegen Doppelzaehlung, wenn mehrere gleichzeitig unterwegs sind.
    """

    __tablename__ = "zaehlbereich"
    __table_args__ = (
        UniqueConstraint("inventur_id", "name", name="uq_bereich_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inventur_id: Mapped[int] = mapped_column(ForeignKey("inventur.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    zugewiesen_an: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=BereichStatus.OFFEN.value)

    inventur: Mapped[Inventur] = relationship(back_populates="bereiche")


class ScanEvent(Basis):
    """Anhaenge-Log. Wird nie geaendert und nie geloescht."""

    __tablename__ = "scan_event"
    __table_args__ = (
        Index("ix_scan_inventur", "inventur_id", "id"),
        Index("ix_scan_position", "sollposition_id"),
        # Ohne diese Zusicherung koennten zwei Geraete denselben Scan
        # gleichzeitig stornieren und die Menge doppelt abziehen. NULL ist
        # mehrfach erlaubt, betrifft also nur echte Stornobuchungen.
        UniqueConstraint("storniert_event_id", name="uq_scan_storno_einmalig"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inventur_id: Mapped[int] = mapped_column(ForeignKey("inventur.id", ondelete="CASCADE"))
    zaehlbereich_id: Mapped[int | None] = mapped_column(
        ForeignKey("zaehlbereich.id", ondelete="SET NULL"), nullable=True)

    # NULL = gescannt, aber im Sollbestand nicht gefunden. Der Scan wird
    # trotzdem festgehalten, damit die Zaehlung nie blockiert.
    sollposition_id: Mapped[int | None] = mapped_column(
        ForeignKey("sollposition.id", ondelete="SET NULL"), nullable=True)

    roh_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ean: Mapped[str | None] = mapped_column(String(13), nullable=True)
    menge: Mapped[int] = mapped_column(Integer, default=1)
    erfassungsart: Mapped[str] = mapped_column(String(20), default=Erfassungsart.SCAN.value)
    erfasst_von: Mapped[str] = mapped_column(String(80), default="unbekannt")
    geraet: Mapped[str | None] = mapped_column(String(80), nullable=True)
    erfasst_am: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    storniert_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_event.id", ondelete="SET NULL"), nullable=True)

    position: Mapped[Sollposition | None] = relationship()
    bereich: Mapped[Zaehlbereich | None] = relationship()


class ImportProtokoll(Basis):
    """Was beim Excel-Import passiert ist - inklusive der uebersprungenen Zeilen."""

    __tablename__ = "import_protokoll"

    id: Mapped[int] = mapped_column(primary_key=True)
    inventur_id: Mapped[int] = mapped_column(ForeignKey("inventur.id", ondelete="CASCADE"))
    dateiname: Mapped[str] = mapped_column(String(200))
    zeilen_gelesen: Mapped[int] = mapped_column(Integer, default=0)
    zeilen_importiert: Mapped[int] = mapped_column(Integer, default=0)
    zeilen_uebersprungen: Mapped[int] = mapped_column(Integer, default=0)
    spaltenzuordnung: Mapped[str] = mapped_column(Text, default="")
    hinweise: Mapped[str] = mapped_column(Text, default="")
    importiert_am: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
