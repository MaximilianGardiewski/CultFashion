# CultFashion — Modulare Architektur (Planungsdokument, v1)

> Status: **Entwurf zur Freigabe.** Kein Implementierungscode. Alle Code-Blöcke sind
> Signatur-Skizzen zur Definition von Schnittstellen, keine lauffähige Implementierung.

---

## 1. Kontext & Leitentscheidungen

Zusatzsystem für einen Modeeinzelhändler (14 Filialen, Multi-Brand). Läuft **additiv**
neben advarics (ERP/Kasse) und bindet dessen REST-API an. advarics bleibt das
führende System — unser System ist im MVP **lesend**.

Fünf Entscheidungen, die alles andere bestimmen:

| # | Entscheidung | Begründung |
|---|---|---|
| E1 | **Modularer Monolith** statt echter Microservices | Ein Entwickler, 14 Filialen, Tages-Sync. Microservices kosten hier Deploy-, Netzwerk- und Debug-Aufwand ohne Gegenwert. Der Modulschnitt ist so gezogen, dass jedes Modul später ohne Refactoring als eigener Service extrahierbar ist (eigene Contracts, eigene Tabellen, Kommunikation nur über Interfaces/Events). |
| E2 | **Mirror-First statt Live-API** | Der Sync-Job zieht advarics-Daten in lokales PostgreSQL. Die Business-Logik liest **ausschließlich** aus dem Mirror, nie aus advarics. Das ist die stärkste Entkopplung überhaupt: advarics-Ausfall/Umbau legt die Engine nicht lahm, und die Historie (die advarics evtl. nicht vorhält) gehört uns. |
| E3 | **Anti-Corruption-Layer (ACL)** zwischen advarics und Domain | advarics-Feldnamen, -IDs und -Datentypen erreichen die Domain nie. Übersetzung in `infrastructure/advarics/mappers.py`, eigene interne IDs + `external_refs`-Mapping-Tabelle. |
| E4 | **Pure-Domain-Kern** | Die eigentliche Markdown-Entscheidung ist eine reine Funktion ohne I/O: `(Performance-Fakten, Zielkurve, Policy, Datum) -> Empfehlung`. Damit in Millisekunden testbar, deterministisch und fachlich mit dem Kunden am Tisch validierbar. |
| E5 | **MVP schreibt keine Preise zurück** | Output ist eine geprüfte Reduzierungsliste (Dashboard + CSV/PDF-Export je Filiale). Preis-Writeback über 14 Filialen ist das größte Schadensrisiko und braucht ein eigenes, separat freigegebenes Sicherheitskonzept. |

---

## 2. Architekturüberblick

### 2.1 Schichten (Abhängigkeiten zeigen **immer nach innen**)

```
┌──────────────────────────────────────────────────────────────────┐
│ PRESENTATION      FastAPI (/api/v1)  ·  CLI (typer)  ·  Next.js  │
├──────────────────────────────────────────────────────────────────┤
│ APPLICATION       Use-Cases · Port-Definitionen · DTOs · UoW      │
├──────────────────────────────────────────────────────────────────┤
│ DOMAIN            Entities · Value Objects · Policies · Engine    │
│                   >>> KEIN httpx, KEIN sqlalchemy, KEIN fastapi <<<│
├──────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE    advarics-ACL · Postgres-Repos · Sync · Scheduler│
└──────────────────────────────────────────────────────────────────┘
        Infrastructure implementiert die von Application
        definierten Ports  →  Dependency Inversion
```

Merksatz für Reviews: **Domain und Application dürfen nichts importieren, das ein
Netzwerkkabel oder eine Festplatte braucht.**

### 2.2 Datenfluss (Makro)

```
  advarics REST                Unser System                     Nutzer
 ─────────────────   ───────────────────────────────────   ───────────────
                    ┌──────────────┐
  /articles ──────► │ AdvaricsAdap-│  RetailSystemPort
  /stock    ──────► │ ter  (ACL)   │──────────┐
  /sales    ──────► └──────────────┘          │
  /receipts                                    ▼
                                        ┌─────────────┐
                                        │ Sync-Job    │  nächtlich, idempotent,
                                        │ (Watermark) │  Upsert
                                        └──────┬──────┘
                                               ▼
                                     ┌───────────────────┐
                                     │ Postgres "Mirror" │  raw + normalisiert
                                     └─────────┬─────────┘
                                               ▼
                                     ┌───────────────────┐
                                     │ Fakten-Aggregation│  article_week_facts
                                     └─────────┬─────────┘
                                               ▼
                                     ┌───────────────────┐
                                     │ Markdown-Engine   │  PURE, kein I/O
                                     │ STR vs. Zielkurve │
                                     └─────────┬─────────┘
                                               ▼
                                     ┌───────────────────┐    ┌──────────────┐
                                     │ Empfehlungen +    │───►│ Dashboard    │
                                     │ Begründungscodes  │    │ Accept/Reject│
                                     └───────────────────┘    └──────┬───────┘
                                                                     ▼
                                                              CSV/PDF-Export
                                                              je Filiale
```

---

## 3. Modulschnitt & Schnittstellen zwischen den drei Modulen

### 3.1 Prinzip

Drei Module über einem **Shared Kernel** (`core/`). Der Shared Kernel enthält nur,
was fachlich unstrittig allen gehört: Artikel-, Filial- und SKU-Identität, Money,
Saison/Saisonwoche, Bestandsmenge — plus die Ports nach außen.

**Harte Regel:** Ein Modul darf importieren aus `core/` und aus
`modules/<anderes>/contracts.py`. **Niemals** aus `modules/<anderes>/domain|application|infrastructure`.
Durchgesetzt per `import-linter` in CI (siehe §5, R7).

### 3.2 Port nach außen (Shared Kernel) — austauschbare API-Schicht

```python
# core/ports/retail_system.py   — SIGNATUR-SKIZZE
class RetailSystemPort(Protocol):
    """Alles, was das führende Warenwirtschaftssystem liefern muss.
    Implementierungen: AdvaricsAdapter, FixtureAdapter (CSV, offline), FakeAdapter (Tests)."""

    def fetch_stores(self) -> Iterable[StoreRecord]: ...
    def fetch_articles(self, changed_since: datetime | None) -> Iterable[ArticleRecord]: ...
    def fetch_stock_snapshot(self, at: date, store: StoreId | None = None) -> Iterable[StockRecord]: ...
    def fetch_sales(self, period: DateRange, store: StoreId | None = None) -> Iterable[SalesRecord]: ...
    def fetch_goods_receipts(self, period: DateRange) -> Iterable[ReceiptRecord]: ...
    def fetch_transfers(self, period: DateRange) -> Iterable[TransferRecord]: ...

# Optional, bewusst SEPARAT — schreibende Fähigkeit ist nicht Teil des Lese-Ports:
class PriceWritebackPort(Protocol):
    def apply_price_change(self, change: PriceChangeCommand, *, dry_run: bool = True) -> WritebackResult: ...
```

`StoreRecord`/`ArticleRecord`/… sind **unsere** DTOs (Shared Kernel), nicht advarics-JSON.
Ein Wechsel des Warenwirtschaftssystems bedeutet: eine neue Klasse hinter diesem Protocol.

### 3.3 Contracts zwischen den Modulen

```python
# modules/stocktaking/contracts.py   — von Modul 2 VERÖFFENTLICHT
class StockQueryService(Protocol):
    def current_stock(self, sku: SkuId, stores: Sequence[StoreId]) -> Mapping[StoreId, StockLevel]: ...
    def confidence(self, sku: SkuId, store: StoreId) -> StockConfidence: ...
        # HIGH | MEDIUM | LOW — wie verlässlich ist der Buchbestand?
        # Wird aus Inventurdifferenz-Historie abgeleitet.

# modules/markdown/contracts.py      — von Modul 1 VERÖFFENTLICHT
class PriceStateQuery(Protocol):
    def current_markdown_state(self, sku: SkuId) -> MarkdownState | None: ...
        # aktive Rabattstufe + seit wann + Begründung

# modules/clickcollect/contracts.py  — von Modul 3 VERÖFFENTLICHT (später)
class ReservationService(Protocol):
    def reserve(self, sku: SkuId, source: StoreId, target: StoreId, qty: int) -> ReservationId: ...
    def release(self, reservation: ReservationId) -> None: ...
```

**Wer konsumiert wen:**

| Konsument | Nutzt | Wofür |
|---|---|---|
| Modul 1 (Markdown) | `StockQueryService` | Restbestand + Bestandsvertrauen für die Reichweiten-Berechnung |
| Modul 3 (Click&Collect) | `StockQueryService` | Echtzeit-Bestand der anderen Filialen |
| Modul 3 | `PriceStateQuery` | korrekter aktueller Preis bei filialübergreifender Abholung |
| Modul 2 (Bestand) | — | konsumiert kein anderes Modul (nur `core/`) |

**Wichtig für die MVP-Reihenfolge:** Modul 1 definiert `StockQueryService` als
*benötigten Port* und bekommt im MVP eine triviale Implementierung, die den
Buchbestand aus dem Mirror liest (`confidence = MEDIUM` pauschal). Sobald Modul 2
existiert, wird nur diese eine Implementierung ausgetauscht — Modul 1 ändert sich
nicht. Das ist die geplante Naht.

### 3.4 Events (In-Process-Bus, später ersetzbar durch Queue)

```
markdown      →  MarkdownRecommended · MarkdownDecisionRecorded
stocktaking   →  StockCountCompleted · StockDiscrepancyDetected
clickcollect  →  ReservationCreated · ReservationExpired
core/sync     →  SyncRunCompleted · SyncRunFailed
```

Events sind **Benachrichtigungen, keine Steuerung**: kein Modul darf sich darauf
verlassen, dass ein Handler synchron etwas erledigt hat.

---

## 4. Verzeichnisstruktur

```
cultfashion/
├── pyproject.toml
├── docker-compose.yml                  # postgres + app + scheduler
├── .importlinter                       # erzwungene Schichtgrenzen (CI)
├── alembic/                            # DB-Migrationen
├── docs/
│   └── architecture.md                 # dieses Dokument
│
├── src/cultfashion/
│   │
│   ├── core/                           # ─── SHARED KERNEL ───
│   │   ├── domain/
│   │   │   ├── identifiers.py          # ArticleId, SkuId, StoreId (typisiert, keine nackten str)
│   │   │   ├── article.py              # Article, Sku, Brand, Warengruppe, LifecycleType
│   │   │   ├── store.py
│   │   │   ├── money.py                # Money VO (Währung, Rundung, Prozentrechnung)
│   │   │   ├── season.py               # Season + Saisonwoche = Zeitachse des Systems
│   │   │   └── stock.py                # StockLevel, StockConfidence
│   │   ├── ports/
│   │   │   ├── retail_system.py        # RetailSystemPort (+ PriceWritebackPort)
│   │   │   ├── clock.py                # Clock — macht "heute" injizierbar
│   │   │   ├── unit_of_work.py
│   │   │   └── event_bus.py
│   │   ├── events/base.py
│   │   └── errors.py
│   │
│   ├── modules/
│   │   ├── markdown/                   # ─── MODUL 1 (MVP) ───
│   │   │   ├── contracts.py            # veröffentlichte Schnittstelle für andere Module
│   │   │   ├── domain/                 # PURE
│   │   │   ├── application/            # Use-Cases + Repository-Ports
│   │   │   ├── infrastructure/         # SQLAlchemy-Modelle + Repo-Implementierungen
│   │   │   └── api/                    # FastAPI-Router dieses Moduls
│   │   ├── stocktaking/                # ─── MODUL 2 (Struktur jetzt, Inhalt später) ───
│   │   │   ├── contracts.py            # StockQueryService — JETZT definieren
│   │   │   └── (domain|application|infrastructure|api)/
│   │   └── clickcollect/               # ─── MODUL 3 (später) ───
│   │       ├── contracts.py
│   │       └── (…)/
│   │
│   ├── infrastructure/                 # ─── QUERSCHNITT ───
│   │   ├── advarics/                   # ANTI-CORRUPTION LAYER
│   │   │   ├── client.py               # HTTP: Auth, Retry, Backoff, Rate-Limit, Pagination
│   │   │   ├── dtos.py                 # Pydantic-Spiegel der advarics-Payloads (1:1)
│   │   │   ├── mappers.py              # advarics-DTO  ->  Shared-Kernel-Record
│   │   │   ├── adapter.py              # implementiert RetailSystemPort
│   │   │   └── fixtures_adapter.py     # CSV/JSON offline — Demo ohne Credentials
│   │   ├── persistence/
│   │   │   ├── engine.py, session.py, unit_of_work.py
│   │   │   └── external_refs.py        # interne ID  <->  advarics-ID
│   │   ├── sync/
│   │   │   ├── ingest.py               # Pull -> Mirror, watermark-basiert inkrementell
│   │   │   ├── models.py               # Mirror-Tabellen
│   │   │   ├── facts.py                # Aggregation -> article_week_facts
│   │   │   └── scheduler.py
│   │   ├── events/in_process_bus.py
│   │   └── config.py                   # pydantic-settings, alle Secrets aus ENV
│   │
│   └── presentation/
│       ├── api/                        # FastAPI-App, Router-Registrierung, DI-Container
│       └── cli/main.py                 # sync · recompute · export · doctor
│
├── tests/
│   ├── unit/                           # Domain, ohne DB, ohne Netz
│   ├── integration/                    # Repos gegen echtes Postgres (testcontainers)
│   ├── contract/                       # AdvaricsAdapter gegen aufgezeichnete Responses
│   └── fixtures/                       # Beispiel-Sortiment für Demo
│
└── dashboard/                          # Next.js (React) — eigenes Deployment
    ├── app/markdown/                   # Reduzierungsliste, Accept/Reject
    └── lib/api-client.ts               # generiert aus OpenAPI-Schema
```

---

## 5. Kopplungsrisiken & Gegenmaßnahmen

| # | Risiko | Konkrete Gegenmaßnahme |
|---|---|---|
| **R1** | **advarics-Aufrufe wandern in die Business-Logik** (der Klassiker: „schnell mal den Bestand nachladen") | E2 (Mirror-First) macht es überflüssig. Zusätzlich `import-linter`-Contract: `cultfashion.modules.*.domain` darf `httpx`, `requests`, `sqlalchemy`, `fastapi`, `cultfashion.infrastructure` **nicht** importieren. Bricht den CI-Build, nicht erst das Code-Review. |
| **R2** | **advarics-Datenmodell sickert in die Domain** (deren Feldnamen, deren Artikel-IDs als unsere Identität) | ACL mit eigenen DTOs; eigene interne IDs; `external_refs(source_system, external_id, internal_id)`. Test: In `modules/*/domain/` darf der String „advarics" nicht vorkommen — als Grep-Assertion im Testlauf. |
| **R3** | **Undokumentierte / stillschweigende Schnittstellenänderung** bei advarics (Swagger ist derzeit aus dieser Umgebung nicht erreichbar) | (a) Contract-Tests gegen aufgezeichnete Responses; (b) nächtlicher Schema-Drift-Job: aktuelles Swagger gegen gespeicherten Snapshot diffen und alarmieren; (c) Mapper toleranzfähig — unbekannte Felder ignorieren, fehlende Pflichtfelder als `IngestError` in eine Dead-Letter-Tabelle, nicht als Crash des ganzen Laufs. |
| **R4** | **Fachlogik rutscht in SQL** (STR als Postgres-View berechnet → nicht mehr testbar, nicht mehr erklärbar) | Trennung: SQL macht **Aggregation** (Summen je Artikel×Woche), Python-Domain macht **Entscheidung**. Read-Models sind explizit als solche benannt und haben eigene Tests. Keine `CASE WHEN`-Preislogik in Views. |
| **R5** | **Dashboard koppelt an interne Domain-Strukturen** | API gibt ausschließlich explizite Response-DTOs zurück, versioniert unter `/api/v1`. Frontend-Client wird aus dem OpenAPI-Schema generiert; ein Domain-Refactoring, das das API-Schema ändert, fällt sofort auf. |
| **R6** | **Verstecktes Zeit-Coupling** (`date.today()` mitten in der Engine → nicht reproduzierbar, nicht testbar, „Warum kam die Empfehlung letzte Woche nicht?") | `Clock`-Port injizieren. Jede Empfehlung speichert `run_id`, `calculated_at`, `calculation_version` → jede Empfehlung ist im Nachhinein exakt reproduzierbar. Wichtig für das Vertrauen des Kunden. |
| **R7** | **Module wachsen zusammen** (Modul 3 greift direkt in Modul-2-Tabellen) | `import-linter` Independence-Contract zwischen den drei Modulen, Ausnahme nur `contracts.py`. Jedes Modul besitzt sein eigenes Tabellen-Präfix; kein Cross-Modul-JOIN, kein Cross-Modul-FK. |
| **R8** | **Bidirektionale Kopplung durch Preis-Writeback** — größtes Geschäftsrisiko: ein Bug ändert Preise in 14 Filialen | MVP schreibt gar nicht (E5). Später: eigener `PriceWritebackPort`, Feature-Flag, verpflichtender `dry_run`-Lauf, Vier-Augen-Freigabe im Dashboard, Änderungslimit pro Lauf (z. B. max. n Artikel), vollständiges Audit-Log. |
| **R9** | **Umlagerungen werden als Verkauf gezählt** → STR filialweise systematisch falsch → falsche Reduzierungen | Standard-Betrachtungsebene ist die **Kette** (Umlagerungen saldieren sich dort weg). Filialebene nur als Zusatzsignal, und dort Wareneingang = Lieferung + Umlagerungseingang − Umlagerungsausgang. Explizite Testfälle dafür. |
| **R10** | **NOS-/Basic-Artikel werden reduziert** (Only/Vero Moda-Nachorderprogramme) → echter Margenschaden | `LifecycleType` (SEASONAL / NOS / BASIC) ist Pflichtfeld im Shared Kernel. Guard-Regel in der Engine: NOS/BASIC werden hart übersprungen. Fehlt die Klassifizierung, wird der Artikel **nicht** empfohlen, sondern als „unklassifiziert" gemeldet (Fail-Safe statt Fail-Open). |

---

## 6. Wichtigste Dateien für den MVP von Modul 1

**Shared Kernel**

| Datei | Verantwortung |
|---|---|
| `core/domain/identifiers.py` | Typisierte IDs (`ArticleId`, `SkuId`, `StoreId`), damit Verwechslungen Compile-/Typecheck-Fehler statt Laufzeitfehler werden. |
| `core/domain/article.py` | Artikel/SKU mit Marke, Warengruppe, Saison und `LifecycleType` — das fachliche Zentrum des Sortiments. |
| `core/domain/season.py` | Saison und **Saisonwoche**: rechnet ein Datum in die Position auf der Zielkurve um (die Zeitachse der gesamten Engine). |
| `core/domain/money.py` | Money-Value-Object mit definierter Rundung — verhindert Cent-Fehler bei Rabattstufen. |
| `core/ports/retail_system.py` | `RetailSystemPort`: der eine Vertrag, hinter dem advarics austauschbar liegt. |
| `core/ports/clock.py` | `Clock`: macht „heute" injizierbar und die Engine reproduzierbar. |

**Markdown-Domain (rein, kein I/O — hier liegt der eigentliche Wert)**

| Datei | Verantwortung |
|---|---|
| `modules/markdown/domain/sell_through.py` | Berechnet die kumulierte Sell-Through-Rate je Artikel und Saisonwoche aus Wareneingang, Verkäufen und Retouren. |
| `modules/markdown/domain/target_curve.py` | Zielkurve je Warengruppe als Stützstellen + Interpolation; liefert den Soll-STR für eine Saisonwoche. |
| `modules/markdown/domain/coverage.py` | Reichweite (Wochen-Bestandsdeckung) als zweites, vom STR unabhängiges Signal. |
| `modules/markdown/domain/markdown_policy.py` | Rabattleiter, Mindestabstand zwischen Reduzierungen, Mindestalter, Margenuntergrenze, NOS-Ausschlüsse — alle Stellschrauben an genau einer Stelle. |
| `modules/markdown/domain/recommendation.py` | `MarkdownRecommendation` inkl. Kennzahlen und **Begründungscodes** — ohne Begründung keine Akzeptanz beim Kunden. |
| `modules/markdown/domain/engine.py` | Die reine Entscheidungsfunktion: Fakten + Kurve + Policy + Datum → Empfehlung oder begründetes Überspringen. |

**Application**

| Datei | Verantwortung |
|---|---|
| `modules/markdown/application/ports.py` | Repository-Protokolle (`ArticleFactsRepository`, `TargetCurveRepository`, `RecommendationRepository`) sowie der benötigte `StockQueryService`. |
| `modules/markdown/application/use_cases/generate_recommendations.py` | Orchestriert einen Lauf: Fakten laden → Engine aufrufen → Ergebnisse mit `run_id` persistieren → Event veröffentlichen. |
| `modules/markdown/application/use_cases/record_decision.py` | Nimmt Annahme/Ablehnung/Zurückstellen durch die Filial-/Bereichsleitung entgegen — der Audit-Trail und später die Datenbasis zur Kurvenkalibrierung. |
| `modules/markdown/application/use_cases/manage_target_curves.py` | Anlegen/Pflegen der Zielkurven je Warengruppe (im MVP Import aus Excel/CSV). |

**Infrastruktur**

| Datei | Verantwortung |
|---|---|
| `infrastructure/advarics/client.py` | HTTP-Zugriff mit Auth, Retry/Backoff, Pagination — die einzige Stelle im System, die advarics-URLs kennt. |
| `infrastructure/advarics/dtos.py` | Pydantic-Spiegel der advarics-Antworten, bewusst 1:1 zur API und ohne Fachlogik. |
| `infrastructure/advarics/mappers.py` | Übersetzt advarics-DTOs in Shared-Kernel-Records — die Grenzmauer des ACL. |
| `infrastructure/advarics/adapter.py` | Implementiert `RetailSystemPort` gegen advarics. |
| `infrastructure/advarics/fixtures_adapter.py` | Implementiert denselben Port aus CSV-Dateien → vollständige Demo ohne Credentials und ohne Netzwerk. |
| `infrastructure/sync/ingest.py` | Idempotenter, watermark-basierter Abgleich in den Mirror inkl. Dead-Letter für fehlerhafte Datensätze. |
| `infrastructure/sync/facts.py` | Verdichtet Mirror-Daten zu `article_week_facts` (Artikel × Woche × Filiale: Anfangsbestand, Zugang, Absatz, Retouren, Endbestand). |
| `modules/markdown/infrastructure/repositories.py` | Postgres-Implementierungen der Markdown-Repository-Ports. |
| `presentation/api/routers/markdown.py` | REST-Endpunkte: Empfehlungen listen/filtern, Entscheidung erfassen, Liste exportieren. |
| `presentation/cli/main.py` | Betriebskommandos `sync`, `recompute`, `export`, `doctor` — der schnellste Weg zur Demo. |

**Tests**

| Datei | Verantwortung |
|---|---|
| `tests/unit/markdown/test_engine.py` | Tabellengetriebene Goldfälle: Renner, Ladenhüter, NOS, Saisonende, bereits reduziert — die fachliche Abnahme in Testform. |
| `tests/contract/test_advarics_adapter.py` | Prüft den Mapper gegen aufgezeichnete advarics-Antworten und schlägt bei Schema-Drift an. |

---

## 7. High-Level-Logikfluss (Modul 1)

### 7.1 Nächtlicher Lauf

```
1. SYNC          advarics ──RetailSystemPort──► Mirror
                 · inkrementell über Watermark (letzter erfolgreicher Lauf)
                 · idempotenter Upsert → Wiederholung ist gefahrlos
                 · fehlerhafte Datensätze → Dead-Letter, Lauf läuft weiter

2. AGGREGATION   Mirror ──► article_week_facts
                 je Artikel × ISO-Woche (× Filiale):
                 Anfangsbestand · Wareneingang · Absatz · Retouren
                 · Umlagerung ein/aus · Endbestand · Umsatz

3. BERECHNUNG    für jeden saisonalen Artikel:
                 STR_ist(w)  = Σ(Absatz − Retouren) / Σ(Wareneingang)   [kumuliert]
                 STR_ziel(w) = Zielkurve(Warengruppe, Saisonwoche w)
                 Δ(w)        = STR_ist − STR_ziel                       [Prozentpunkte]
                 Reichweite  = Restbestand / Ø-Absatz letzte 4 Wochen   [Wochen]
                 Restlaufzeit= Wochen bis Saisonende

4. ENTSCHEIDUNG  reine Funktion, Guards zuerst:
                 ├─ LifecycleType ≠ SEASONAL ...................... SKIP (nos_excluded)
                 ├─ unklassifiziert .............................. SKIP (unclassified) ⚠ melden
                 ├─ Artikel jünger als min_age_weeks ............. SKIP (too_young)
                 ├─ letzte Reduzierung < min_interval_weeks ...... SKIP (cooldown)
                 ├─ höchste Rabattstufe erreicht ................. SKIP (ladder_exhausted)
                 ├─ Bestand unter Mindestmenge ................... SKIP (residual_stock)
                 └─ sonst Signalprüfung:
                    Δ ≤ −schwelle(Warengruppe)   ODER
                    Reichweite > Restlaufzeit × faktor
                       → Rabattstufe aus Mapping (Rückstandshöhe × Saisonfortschritt)
                       → gedeckelt durch Margenuntergrenze
                       → EMPFEHLUNG mit Begründungscodes + Kennzahlen

5. PERSISTENZ    Empfehlungen mit run_id, calculated_at, calculation_version
                 → Event MarkdownRecommended
```

### 7.2 Tagesbetrieb (Mensch)

```
6. DASHBOARD     Reduzierungsliste, filterbar nach Filiale/Warengruppe/Marke/Stufe.
                 Jede Zeile ist selbsterklärend, z. B.:

                 "Opus Bluse 'Falia' · Saisonwoche 9
                  Sell-Through 34 % (Ziel 52 %) → 18 pp Rückstand
                  Restbestand 61 Stück · Reichweite 14 Wochen · Saisonende in 7 Wochen
                  ► Empfehlung: −30 %  (Gründe: below_target_curve, coverage_exceeds_season)"

7. ENTSCHEIDUNG  Annehmen / Ablehnen / Zurückstellen → MarkdownDecision (Audit-Trail)

8. AUSFÜHRUNG    Export je Filiale (CSV/PDF) → manuelle Pflege in advarics
                 (Writeback bewusst ausserhalb des MVP — siehe R8)

9. RÜCKKOPPLUNG  Abgelehnte Empfehlungen sind die wertvollsten Daten:
                 sie zeigen, wo die Zielkurve nicht der Realität entspricht.
                 (Kurvenkalibrierung = Ausbaustufe, nicht MVP)
```

### 7.3 Bewusst **nicht** im MVP

Preis-Writeback nach advarics · automatische Kurvenkalibrierung/ML ·
filialspezifische Preise · Modul 2 und 3 (nur Contracts stehen) · Echtzeit-Sync.

---

## 8. Verifikation (wie wir beweisen, dass es funktioniert)

1. **Fachlich, ohne advarics:** `cultfashion sync --source=fixtures` +
   `cultfashion recompute` erzeugt aus dem Beispielsortiment in `tests/fixtures/`
   eine vollständige Reduzierungsliste. Damit ist der MVP demonstrierbar,
   **bevor** API-Zugangsdaten vorliegen.
2. **Unit-Tests der Engine:** Goldfälle als Tabelle, inklusive der Grenzfälle
   Renner / Ladenhüter / NOS / Saisonende / Cooldown.
3. **Contract-Tests:** Mapper gegen aufgezeichnete advarics-Antworten.
4. **Integrationstest:** Sync gegen echtes Postgres (testcontainers), zweimal
   hintereinander ausgeführt → identisches Ergebnis (Idempotenz-Beweis).
5. **Architektur-Test:** `lint-imports` in CI — bricht den Build, wenn Domain
   Infrastruktur importiert oder ein Modul in ein anderes hineingreift.
6. **Fachliche Abnahme:** ein Lauf gegen echte Vorsaison-Daten, Ergebnis neben die
   damaligen manuellen Entscheidungen legen. Das ist der eigentliche Akzeptanztest
   beim Kunden.

---

## 9. Rückfragen vor Implementierungsbeginn

1. **advarics-Datenverfügbarkeit** — die Swagger-Doku ist aus meiner Umgebung
   nicht erreichbar (Egress blockiert), ich kenne den Endpunkt-Umfang also nicht.
   Entscheidend: Liefert die API (a) **historische Verkäufe** je Artikel/Tag/Filiale,
   (b) **Wareneingänge/Lieferungen** und (c) **Umlagerungen** — oder nur den
   aktuellen Bestand? Ohne Wareneingangshistorie ist die Sell-Through-Rate nicht
   exakt berechenbar und wir brauchen eine Näherung (Erstbestand bei erstem
   Auftreten). Und: gibt es einen Delta-/`changed-since`-Parameter oder nur
   Vollabzüge? Falls du das Swagger-JSON hast, schick es mir — dann baue ich den
   Adapter gegen die echten Schemas statt gegen Annahmen.

2. **Zielkurven** — existieren die schon (Excel vom Einkauf), oder soll das System
   sie aus Vorsaison-Daten ableiten? Und auf welcher Ebene: nur je Warengruppe,
   oder Warengruppe × Marke × Saison? Das bestimmt Datenmodell und ob wir für den
   MVP zusätzlich einen Kurven-Fitter brauchen.

3. **Entscheidungsebene und Rabattleiter** — wird die Reduzierung
   **kettenweit je Artikel** entschieden (üblich, ein Preis in allen 14 Filialen)
   oder filialindividuell? Und welche Rabattstufen sind im Haus üblich
   (−20/−30/−50/−70)? Davon hängt ab, ob `Store` überhaupt Teil des
   Empfehlungsschlüssels ist.

4. **NOS-/Nachorder-Sortimente** — gibt es in advarics ein Feld, das
   Saisonware von NOS/Basics unterscheidet (relevant besonders bei Only und
   Vero Moda), oder müssen wir das aus Nachliefer-Mustern erschließen? Das ist der
   Punkt, an dem eine falsche Empfehlung echtes Geld kostet (R10).

5. **Writeback-Erwartung** — reicht dem Kunden für den MVP die geprüfte
   Reduzierungsliste als Export, oder erwartet er, dass die Preisänderung
   automatisch in advarics landet? Ich empfehle klar Variante 1 für den MVP;
   ich möchte aber wissen, ob das in der Demo als Lücke wahrgenommen würde.

---

*Nach Freigabe dieses Plans beginne ich mit Shared Kernel + Markdown-Domain +
Fixture-Adapter — also mit dem Teil, der ohne advarics-Zugang vollständig
lauffähig und demonstrierbar ist.*
