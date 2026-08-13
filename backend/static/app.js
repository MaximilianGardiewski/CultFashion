/* Inventur-PWA – ohne Framework und ohne Build-Schritt.
 *
 * Der heikelste Teil ist die Entprellung: die Kamera sieht dasselbe Etikett
 * 30-mal pro Sekunde, zwei echte Teile hintereinander muessen aber zweimal
 * zaehlen. Geloest ueber "der Code muss das Bild verlassen haben" statt ueber
 * eine feste Wartezeit - siehe entprellung().
 */
"use strict";

const $ = (id) => document.getElementById(id);
const zustand = {
  inventurId: null, bereichId: null, bereichName: "", name: "",
  token: null, rolle: null,
  letzterEventId: null, teile: 0, letzteFarbwahl: null,
};
const istAdmin = () => zustand.rolle === "admin";

/* ---------- Speicher & API ---------- */

function ladeZustand() {
  try {
    Object.assign(zustand, JSON.parse(localStorage.getItem("inventur") || "{}"));
  } catch { /* verworfene Einstellungen sind kein Grund zum Absturz */ }
}
function merkeZustand() {
  localStorage.setItem("inventur", JSON.stringify({
    inventurId: zustand.inventurId, bereichId: zustand.bereichId,
    bereichName: zustand.bereichName, name: zustand.name,
    token: zustand.token, rolle: zustand.rolle,
  }));
}

async function api(pfad, optionen = {}) {
  const kopf = optionen.body instanceof FormData
    ? {} : { "Content-Type": "application/json" };
  if (zustand.token) kopf["X-Token"] = zustand.token;

  const antwort = await fetch("/api" + pfad, { headers: kopf, ...optionen });

  if (antwort.status === 401) {
    // Token abgelaufen oder abgemeldet - zurück zur Anmeldung, statt eine
    // Fehlermeldung zu zeigen, mit der niemand etwas anfangen kann.
    zustand.token = null; zustand.rolle = null; merkeZustand();
    zeigeAnmeldung();
    throw new Error("Bitte neu anmelden.");
  }
  if (!antwort.ok) {
    let text = antwort.statusText;
    try {
      const daten = await antwort.json();
      // FastAPI meldet Validierungsfehler als Liste von Objekten. Ohne diese
      // Behandlung stünde "[object Object]" auf dem Bildschirm.
      if (Array.isArray(daten.detail)) {
        text = daten.detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
      } else if (typeof daten.detail === "string") {
        text = daten.detail;
      }
    } catch { /* keine JSON-Antwort */ }
    throw new Error(text);
  }
  return antwort.status === 204 ? null : antwort.json();
}

/* ---------- Anmeldung ---------- */

let ersterBenutzer = false;

async function pruefeEinrichtung() {
  try {
    const stand = await (await fetch("/api/einrichtung")).json();
    ersterBenutzer = !stand.benutzer_vorhanden;
  } catch { ersterBenutzer = false; }

  $("an_titel").textContent = ersterBenutzer ? "Erste Anmeldung einrichten" : "Anmelden";
  $("an_hinweis").textContent = ersterBenutzer
    ? "Es ist noch niemand angelegt. Wer sich hier einträgt, wird Administratorin."
    : "Name und PIN wie besprochen.";
  $("an_senden").textContent = ersterBenutzer ? "Anlegen und anmelden" : "Anmelden";
}

function zeigeAnmeldung() {
  $("anmeldung").classList.remove("versteckt");
  pruefeEinrichtung();
}

async function anmelden() {
  const name = $("an_name").value.trim();
  const pin = $("an_pin").value;
  if (!name || !pin) return;

  $("an_senden").disabled = true;
  $("an_fehler").innerHTML = "";
  try {
    if (ersterBenutzer) {
      const antwort = await fetch("/api/benutzer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, pin, rolle: "admin" }),
      });
      if (!antwort.ok) throw new Error((await antwort.json()).detail || "Fehlgeschlagen");
    }

    const antwort = await fetch("/api/anmeldung", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, pin, geraet: navigator.userAgent.slice(0, 120) }),
    });
    if (!antwort.ok) throw new Error((await antwort.json()).detail || "Fehlgeschlagen");

    const daten = await antwort.json();
    Object.assign(zustand, { token: daten.token, name: daten.name, rolle: daten.rolle });
    merkeZustand();
    $("an_pin").value = "";
    $("anmeldung").classList.add("versteckt");
    await starteApp();
  } catch (fehler) {
    $("an_fehler").innerHTML = `<div class="band schlecht">${fehler.message}</div>`;
  } finally {
    $("an_senden").disabled = false;
  }
}

$("an_senden").addEventListener("click", anmelden);
$("an_pin").addEventListener("keydown", (e) => { if (e.key === "Enter") anmelden(); });

/* ---------- Rückmeldung: sehen, hören, spüren ---------- */

let tonkontext = null;
function ton(frequenz, dauer = 0.09, lautstaerke = 0.16) {
  try {
    tonkontext = tonkontext || new (window.AudioContext || window.webkitAudioContext)();
    const o = tonkontext.createOscillator(), g = tonkontext.createGain();
    o.frequency.value = frequenz; o.type = "square";
    g.gain.value = lautstaerke;
    o.connect(g); g.connect(tonkontext.destination);
    o.start(); o.stop(tonkontext.currentTime + dauer);
  } catch { /* ohne Ton geht es auch */ }
}
const vibriere = (muster) => navigator.vibrate && navigator.vibrate(muster);

/* Die Farbe trägt die Aussage über die ganze Fläche, nicht nur als Rand:
   beim Zählen fällt nur ein kurzer Blick aufs Display. */
function melde(art, rolle, titel, unter, menge) {
  $("meldung").dataset.art = art;
  $("m_rolle").textContent = rolle;
  $("m_titel").textContent = titel;
  $("m_unter").textContent = unter || "";
  $("m_menge").textContent = menge == null ? "" : menge;

  if (art === "gut") { ton(880); vibriere(35); }
  else if (art === "info") { ton(520, 0.14); vibriere([25, 45, 25]); }
  else if (art === "schlecht") { ton(180, 0.28); vibriere([70, 60, 70]); }
}

/* ---------- Sheets ---------- */

function oeffneSheet(id) {
  document.querySelectorAll(".sheet").forEach((s) => s.classList.remove("offen"));
  $(id).classList.add("offen");
  $("schleier").classList.add("offen");
}
function schliesseSheets() {
  document.querySelectorAll(".sheet").forEach((s) => s.classList.remove("offen"));
  $("schleier").classList.remove("offen");
}
$("schleier").addEventListener("click", schliesseSheets);

/* ---------- Navigation ---------- */

const seiten = ["karte", "scan", "suche", "auswertung", "setup"];
function zeigeSeite(name) {
  seiten.forEach((s) => $("seite_" + s).classList.toggle("aktiv", s === name));
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("aktiv", b.dataset.seite === name));
  if (name === "auswertung") ladeAuswertung();
  if (name === "karte") ladeKarte();
  if (name !== "scan" && laeuft) stoppeKamera();
}
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => {
    if (b.dataset.seite !== "setup" && !zustand.inventurId) {
      melde("info", "Noch nicht eingerichtet", "Erst eine Inventur wählen", "");
      return zeigeSeite("setup");
    }
    zeigeSeite(b.dataset.seite);
  }));

function aktualisiereKopf() {
  const kopf = $("kopf_bereich");
  kopf.textContent = zustand.bereichName
    || (zustand.inventurId ? `Inventur ${zustand.inventurId} · kein Bereich` : "nicht eingerichtet");
  kopf.classList.toggle("aktiv", Boolean(zustand.bereichId));
  $("k_teile").textContent = zustand.teile;
}

/* ---------- Setup ---------- */

async function ladeInventuren() {
  const liste = await api("/inventuren");
  const feld = $("feld_inventur");
  feld.innerHTML = liste.length
    ? liste.map((i) =>
        `<option value="${i.id}">#${i.id} · ${i.bezeichnung} · ${i.positionen} Artikel</option>`
      ).join("")
    : '<option value="">– noch keine –</option>';
  if (zustand.inventurId) feld.value = String(zustand.inventurId);
}

$("btn_neue_inventur").addEventListener("click", async () => {
  const heute = new Date().toLocaleDateString("de-DE");
  const inventur = await api("/inventuren", {
    method: "POST",
    body: JSON.stringify({ filial_nr: "12", filiale: "Bad Krozingen",
                           bezeichnung: "Inventur " + heute }),
  });
  Object.assign(zustand, { inventurId: inventur.id, bereichId: null,
                           bereichName: "", teile: 0 });
  merkeZustand(); await ladeInventuren(); await ladeBereiche(); aktualisiereKopf();
});

$("btn_laden").addEventListener("click", async () => {
  const wert = $("feld_inventur").value;
  if (!wert) return;
  Object.assign(zustand, { inventurId: Number(wert), bereichId: null,
                           bereichName: "", teile: 0 });
  merkeZustand(); await ladeBereiche(); aktualisiereKopf();
});

// Der Name kommt jetzt aus der Anmeldung und ist nicht mehr frei wählbar.
$("feld_name").disabled = true;

$("btn_import").addEventListener("click", async () => {
  if (!zustand.inventurId) return alert("Erst eine Inventur anlegen.");
  const datei = $("feld_datei").files[0];
  if (!datei) return alert("Bitte eine Excel-Datei wählen.");

  const formular = new FormData();
  formular.append("datei", datei);
  $("btn_import").disabled = true;
  $("import_ergebnis").innerHTML = '<p class="hinweis">Wird gelesen …</p>';

  try {
    const e = await api(`/inventuren/${zustand.inventurId}/import`,
                        { method: "POST", body: formular });
    const spalten = Object.entries(e.spaltenzuordnung)
      .map(([feld, ueberschrift]) => `${feld} ← „${ueberschrift}“`).join("<br>");
    $("import_ergebnis").innerHTML =
      `<div class="band gut"><b>${e.zeilen_importiert} Artikel importiert</b><br>
         ${e.zeilen_uebersprungen} Zeilen übersprungen (Titel, Zwischensummen)</div>
       <p class="hinweis"><b>Erkannte Spalten:</b><br>${spalten}</p>` +
      (e.hinweise.length
        ? `<div class="band">${e.hinweise.length} Hinweise:<br>` +
          e.hinweise.slice(0, 8).map((h) => "· " + h).join("<br>") + "</div>"
        : "");
    await ladeInventuren();
  } catch (fehler) {
    $("import_ergebnis").innerHTML = `<div class="band schlecht">${fehler.message}</div>`;
  } finally {
    $("btn_import").disabled = false;
  }
});

async function ladeBereiche() {
  if (!zustand.inventurId) return;
  const baum = await api(`/inventuren/${zustand.inventurId}/bereiche`);

  // Die API liefert Bereiche mit ihren Ständern. Gezählt wird auf
  // Ständerebene, deshalb hier flach ausgerollt.
  const liste = [];
  for (const knoten of baum) {
    liste.push(knoten);
    for (const kind of knoten.kinder || []) liste.push({ ...kind, eingerueckt: true });
  }

  const feld = $("feld_bereich");
  feld.innerHTML = liste.length
    ? liste.map((b) => {
        const stand = b.soll_teile
          ? `${b.gezaehlt}/${b.soll_teile}` : `${b.gezaehlt} Teile`;
        const wer = b.zugewiesen_an ? ` · ${b.zugewiesen_an}` : "";
        return `<option value="${b.id}">${b.eingerueckt ? "   " : ""}${b.name} · ${stand}${wer}</option>`;
      }).join("")
    : '<option value="">– noch keiner –</option>';

  if (!liste.some((b) => b.id === zustand.bereichId)) {
    zustand.bereichId = liste.length ? liste[0].id : null;
  }
  if (zustand.bereichId) feld.value = String(zustand.bereichId);

  const aktiv = liste.find((b) => b.id === zustand.bereichId);
  zustand.bereichName = aktiv ? aktiv.name : "";
  zustand.teile = aktiv ? aktiv.gezaehlt : 0;
  merkeZustand();
  aktualisiereKopf();
}

$("feld_bereich").addEventListener("change", (e) => {
  zustand.bereichId = Number(e.target.value) || null;
  merkeZustand(); ladeBereiche();
});

$("btn_neuer_bereich").addEventListener("click", async () => {
  const name = $("feld_neuer_bereich").value.trim();
  if (!name || !zustand.inventurId) return;
  try {
    const bereich = await api(`/inventuren/${zustand.inventurId}/bereiche`, {
      method: "POST", body: JSON.stringify({ name, zugewiesen_an: zustand.name || null }),
    });
    zustand.bereichId = bereich.id; merkeZustand();
    $("feld_neuer_bereich").value = "";
    await ladeBereiche();
  } catch (fehler) { alert(fehler.message); }
});

/* ---------- Farbflächen ----------
   Der Griff zum Farbfeld ist schneller als „bordeaux“ zu lesen und mit dem
   Teil in der Hand abzugleichen. Unbekannte Farbnamen bekommen ein neutrales
   Feld statt einer geratenen Farbe. */

const FARBFELDER = {
  "black": "#16151A", "schwarz": "#16151A",
  "offwhite": "#EDE7DC", "weiss": "#F2EFE9", "weiß": "#F2EFE9", "white": "#F2EFE9",
  "créme": "#E4D8BE", "creme": "#E4D8BE", "beige": "#D8C7A6",
  "camel": "#B08654", "cognac": "#8C5A2E", "braun": "#5C4433",
  "khaki": "#6E6B45", "oliv": "#5A5C3A", "grün": "#3F6B4A", "green": "#3F6B4A",
  "navy": "#22304F", "blau": "#2F4C7E", "blue": "#2F4C7E",
  "denim blue": "#3C5A80", "denim": "#3C5A80", "jeans": "#3C5A80",
  "bordeaux": "#5C2230", "rot": "#8E2B2B", "red": "#8E2B2B",
  "rosé": "#C89096", "rose": "#C89096", "pink": "#B75A80",
  "light grey melange": "#9A97A0", "grau": "#7C7986", "grey": "#7C7986",
  "silber": "#B9B6BE", "gold": "#B08D4A", "gelb": "#C9A227",
};
function farbfeld(name) {
  const schluessel = (name || "").trim().toLowerCase();
  if (FARBFELDER[schluessel]) return FARBFELDER[schluessel];
  for (const [wort, farbe] of Object.entries(FARBFELDER)) {
    if (schluessel.includes(wort)) return farbe;
  }
  return "#4A4456";
}

/* ---------- Buchen ---------- */

async function verarbeite(antwort) {
  if (antwort.ergebnis === "ungueltig") {
    melde("schlecht", "Abgewiesen", "Prüfziffer stimmt nicht",
          "Etikett beschädigt – bitte erneut scannen");
    return;
  }
  if (antwort.ergebnis === "unbekannt") {
    zustand.teile += 1; merkeZustand(); aktualisiereKopf();
    zustand.letzterEventId = antwort.event_id;
    $("b_undo").disabled = false;
    melde("info", "Nicht im Sollbestand", "Unbekannter Artikel",
          `${antwort.ean} · trotzdem erfasst`);
    ladeLetzte();
    return;
  }
  if (antwort.ergebnis === "mehrdeutig") {
    ton(520, 0.08); vibriere(20);
    // Ohne diese Zeile bliebe die vorherige Meldung stehen - der Bildschirm
    // widerspräche dem offenen Auswahl-Sheet.
    melde("", "Mehrdeutig", `${antwort.kandidaten.length} Artikel teilen die EAN`,
          "Bitte auswählen");
    zeigeAuswahl(antwort);
    return;
  }

  const a = antwort.artikel;
  zustand.teile += 1; merkeZustand(); aktualisiereKopf();
  zustand.letzterEventId = antwort.event_id;
  $("b_undo").disabled = false;
  melde("gut", "Gebucht", `${a.marke} ${a.artikelname}`,
        `${a.farbe} · Gr. ${a.groesse}`, antwort.gezaehlt);
  ladeLetzte();
}

async function bucheDirekt(positionId, art, rohCode) {
  try {
    await verarbeite(await api(`/inventuren/${zustand.inventurId}/buchung`, {
      method: "POST",
      body: JSON.stringify({
        position_id: positionId, zaehlbereich_id: zustand.bereichId,
        erfasst_von: zustand.name || "unbekannt", roh_code: rohCode || null,
        erfassungsart: art, geraet: navigator.platform || null,
      }),
    }));
  } catch (fehler) { melde("schlecht", "Fehler", fehler.message, ""); }
}

async function sendeCode(code) {
  try {
    await verarbeite(await api(`/inventuren/${zustand.inventurId}/scan`, {
      method: "POST",
      body: JSON.stringify({
        code, zaehlbereich_id: zustand.bereichId,
        erfasst_von: zustand.name || "unbekannt", geraet: navigator.platform || null,
      }),
    }));
  } catch (fehler) { melde("schlecht", "Fehler", fehler.message, ""); }
}

/* ---------- Auswahl bei mehrdeutiger EAN ---------- */

function zeigeAuswahl(antwort) {
  const mehrereArtikel =
    new Set(antwort.kandidaten.map((k) => k.artikelname)).size > 1;

  $("sheet_warum").textContent = mehrereArtikel
    ? `${antwort.kandidaten.length} verschiedene Artikel teilen die EAN ${antwort.ean}`
    : `${antwort.kandidaten.length} Farben teilen die EAN ${antwort.ean}`;

  // Zuletzt gewählte Farbe nach oben: solche Teile kommen in Serie.
  const kandidaten = [...antwort.kandidaten].sort((a, b) =>
    (b.farbe === zustand.letzteFarbwahl) - (a.farbe === zustand.letzteFarbwahl));

  $("farben").innerHTML = kandidaten.map((k) => `
    <button class="farbe" data-id="${k.id}" data-farbe="${k.farbe}">
      <span class="klecks" style="background:${farbfeld(k.farbe)}"></span>
      <span style="min-width:0">
        <b>${mehrereArtikel ? k.artikelname : k.farbe}</b>
        <small>${mehrereArtikel ? k.marke + " · " + k.farbe : k.farbnummer + " · Gr. " + k.groesse}</small>
      </span>
      ${k.farbe === zustand.letzteFarbwahl ? '<span class="zuletzt">zuletzt</span>' : ""}
    </button>`).join("");

  $("farben").querySelectorAll(".farbe").forEach((b) =>
    b.addEventListener("click", () => {
      zustand.letzteFarbwahl = b.dataset.farbe;
      schliesseSheets();
      bucheDirekt(Number(b.dataset.id), "auswahl", antwort.roh_code);
    }));

  oeffneSheet("sheet_farben");
}

/* ---------- Storno ---------- */

$("b_undo").addEventListener("click", async () => {
  if (!zustand.letzterEventId) return;
  if (!istAdmin()) return oeffneMarkierung(zustand.letzterEventId);
  try {
    const antwort = await api(
      `/inventuren/${zustand.inventurId}/scans/${zustand.letzterEventId}/storno` +
      `?erfasst_von=${encodeURIComponent(zustand.name || "unbekannt")}`,
      { method: "POST" });
    zustand.teile = Math.max(0, zustand.teile - 1);
    merkeZustand(); aktualisiereKopf();
    zustand.letzterEventId = null;
    $("b_undo").disabled = true;
    melde("info", "Storniert", "Gegenbuchung erfasst",
          antwort.artikel ? `${antwort.artikel.artikelname} · jetzt ${antwort.gezaehlt}`
                          : "Das Protokoll behält beide Einträge");
    ladeLetzte();
  } catch (fehler) { melde("schlecht", "Storno nicht möglich", fehler.message, ""); }
});

/* ---------- Karte ----------
   Die Skizze ist nicht Dekoration, sondern die Fläche, über die Arbeit
   verteilt wird: wer aufmacht, sieht was offen ist, was gerade jemand zählt
   und was fertig ist - und nimmt sich einen Bereich. */

let zonen = [];              // flach, in Anzeigereihenfolge
let bearbeiten = false;
let gewaehlteZone = null;
let neueKoordinaten = null;

function flach(baum) {
  const raus = [];
  for (const knoten of baum) {
    raus.push(knoten);
    for (const kind of knoten.kinder || []) raus.push({ ...kind, kind: true });
  }
  return raus;
}

async function ladeKarte() {
  if (!zustand.inventurId) return;

  const inventur = await api(`/inventuren/${zustand.inventurId}`);
  const baum = await api(`/inventuren/${zustand.inventurId}/bereiche`);
  zonen = flach(baum);

  const bild = $("plan_bild");
  if (inventur.karte_bild) {
    bild.src = `/api/bilder/${inventur.karte_bild}`;
    bild.classList.remove("versteckt");
    $("plan_leer").classList.add("versteckt");
  } else {
    bild.classList.add("versteckt");
    $("plan_leer").classList.remove("versteckt");
    $("plan_leer").textContent = istAdmin()
      ? "Noch keine Skizze. Auf „Bearbeiten“ tippen und Grundriss hochladen."
      : "Noch keine Skizze hinterlegt.";
  }

  $("btn_bearbeiten").classList.toggle("versteckt", !istAdmin());
  zeichnePunkte();
  zeichneZonenListe(baum);
}

function zeichnePunkte() {
  $("plan_punkte").innerHTML = zonen
    .filter((z) => z.karte_x != null && z.karte_y != null)
    .map((z) => `
      <button class="punkt" data-id="${z.id}" data-status="${z.status}"
              style="left:${z.karte_x * 100}%;top:${z.karte_y * 100}%"
              title="${z.name}">${z.name}</button>`).join("");

  $("plan_punkte").querySelectorAll(".punkt").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      oeffneZone(Number(b.dataset.id));
    }));
}

function zeichneZonenListe(baum) {
  const zeile = (z, kind) => {
    const anteil = z.anteil == null ? null : Math.round(z.anteil * 100);
    const balken = z.soll_teile
      ? `<span class="balken ${anteil < 100 ? "knapp" : ""}"><i style="width:${Math.min(100, anteil)}%"></i></span>`
      : "";
    const zahl = z.soll_teile ? `${z.gezaehlt}/${z.soll_teile}` : `${z.gezaehlt}`;
    const wer = z.zugewiesen_an ? ` · ${z.zugewiesen_an}` : "";
    const status = { offen: "offen", laeuft: "wird gezählt", fertig: "fertig" }[z.status];
    return `<button class="zone ${kind ? "kind" : ""}" data-id="${z.id}">
        <span class="wer"><b>${z.name}</b><small>${status}${wer}</small></span>
        ${balken}<span class="zahl">${zahl}</span>
      </button>`;
  };

  const teile = [];
  for (const knoten of baum) {
    teile.push(zeile(knoten, false));
    for (const k of knoten.kinder || []) teile.push(zeile(k, true));
  }
  $("zonen_liste").innerHTML = teile.join("")
    || '<p class="hinweis">Noch keine Bereiche angelegt.</p>';

  $("zonen_liste").querySelectorAll(".zone").forEach((b) =>
    b.addEventListener("click", () => oeffneZone(Number(b.dataset.id))));
}

/* -- Bereich übernehmen ------------------------------------------------ */

function oeffneZone(id) {
  const z = zonen.find((x) => x.id === id);
  if (!z) return;
  gewaehlteZone = z;

  $("zo_name").textContent = z.name;
  const stand = z.soll_teile
    ? `${z.gezaehlt} von ${z.soll_teile} vorgezählten Teilen erfasst`
    : `${z.gezaehlt} Teile erfasst · nicht vorgezählt`;
  const wer = z.zugewiesen_an ? ` · ${z.zugewiesen_an} zählt hier` : "";
  $("zo_stand").textContent = stand + wer;

  $("zo_foto").innerHTML = z.bild
    ? `<img src="/api/bilder/${z.bild}" alt="" style="width:100%;border-radius:11px;margin-top:6px">`
    : "";
  $("zo_aendern").classList.toggle("versteckt", !istAdmin());
  $("zo_uebernehmen").textContent =
    z.status === "laeuft" && z.zugewiesen_an === zustand.name
      ? "Weiter zählen" : "Übernehmen";

  oeffneSheet("sheet_zone");
}

$("zo_uebernehmen").addEventListener("click", async () => {
  const z = gewaehlteZone;
  try {
    await api(`/inventuren/${zustand.inventurId}/bereiche/${z.id}/status`, {
      method: "POST", body: JSON.stringify({ status: "laeuft" }),
    });
    zustand.bereichId = z.id;
    zustand.bereichName = z.name;
    zustand.teile = z.gezaehlt;
    merkeZustand(); aktualisiereKopf();
    schliesseSheets();
    zeigeSeite("scan");
    melde("", "Bereich übernommen", z.name,
          z.soll_teile ? `${z.soll_teile} Teile vorgezählt` : "nicht vorgezählt");
  } catch (fehler) {
    melde("schlecht", "Nicht möglich", fehler.message, "");
    schliesseSheets();
  }
});

$("zo_fertig").addEventListener("click", async () => {
  try {
    await api(`/inventuren/${zustand.inventurId}/bereiche/${gewaehlteZone.id}/status`, {
      method: "POST", body: JSON.stringify({ status: "fertig" }),
    });
    schliesseSheets();
    await ladeKarte();
  } catch (fehler) { alert(fehler.message); }
});

$("zo_markieren").addEventListener("click", () => {
  const z = gewaehlteZone;
  schliesseSheets();
  zustand.bereichName = zustand.bereichName || z.name;
  oeffneMarkierung(null, z.id, z.name);
});

/* -- Vorzählmodus: Bereiche anlegen ------------------------------------ */

$("btn_bearbeiten").addEventListener("click", () => {
  bearbeiten = !bearbeiten;
  $("plan").classList.toggle("bearbeiten", bearbeiten);
  $("btn_bearbeiten").textContent = bearbeiten ? "Fertig" : "Bearbeiten";
  $("plan_hinweis").textContent = bearbeiten
    ? "Auf die Skizze tippen, um einen Bereich zu setzen. Ohne Skizze unten anlegen."
    : "Bereich antippen, um ihn zu übernehmen.";
  if (bearbeiten && !$("plan_bild").src) $("feld_karte").click();
});

$("feld_karte").addEventListener("change", async (e) => {
  const datei = e.target.files[0];
  if (!datei) return;
  const formular = new FormData();
  formular.append("datei", datei);
  try {
    await api(`/inventuren/${zustand.inventurId}/karte`,
              { method: "POST", body: formular });
    await ladeKarte();
  } catch (fehler) { alert(fehler.message); }
});

$("plan").addEventListener("click", (e) => {
  if (!bearbeiten || !istAdmin()) return;
  const kasten = $("plan").getBoundingClientRect();
  neueKoordinaten = {
    x: (e.clientX - kasten.left) / kasten.width,
    y: (e.clientY - kasten.top) / kasten.height,
  };
  oeffneNeueZone();
});

function oeffneNeueZone() {
  $("zn_titel").textContent = neueKoordinaten ? "Bereich auf der Skizze" : "Neuer Bereich";
  $("zn_name").value = "";
  $("zn_soll").value = "";
  $("zn_bild").value = "";
  $("zn_fehler").innerHTML = "";

  // Nur Bereiche können Eltern sein - Ständer hängen darunter.
  const eltern = zonen.filter((z) => z.ebene === "bereich" && !z.kind);
  $("zn_eltern").innerHTML =
    '<option value="">– eigenständiger Bereich –</option>' +
    eltern.map((z) => `<option value="${z.id}">${z.name}</option>`).join("");

  oeffneSheet("sheet_zone_neu");
}

$("zn_senden").addEventListener("click", async () => {
  const name = $("zn_name").value.trim();
  if (!name) return $("zn_name").focus();
  const eltern = $("zn_eltern").value;
  const soll = $("zn_soll").value;

  try {
    const zone = await api(`/inventuren/${zustand.inventurId}/bereiche`, {
      method: "POST",
      body: JSON.stringify({
        name,
        ebene: eltern ? "staender" : "bereich",
        eltern_id: eltern ? Number(eltern) : null,
        soll_teile: soll === "" ? null : Number(soll),
        karte_x: neueKoordinaten ? neueKoordinaten.x : null,
        karte_y: neueKoordinaten ? neueKoordinaten.y : null,
      }),
    });

    const foto = $("zn_bild").files[0];
    if (foto) {
      const formular = new FormData();
      formular.append("datei", foto);
      await api(`/inventuren/${zustand.inventurId}/bereiche/${zone.id}/bild`,
                { method: "POST", body: formular });
    }

    neueKoordinaten = null;
    schliesseSheets();
    await ladeKarte();
  } catch (fehler) {
    $("zn_fehler").innerHTML = `<div class="band schlecht">${fehler.message}</div>`;
  }
});

/* ---------- Meldungen ---------- */

async function ladeMeldungsZahl() {
  if (!zustand.inventurId) return;
  try {
    const zahl = await api(`/inventuren/${zustand.inventurId}/markierungen/anzahl`);
    // Nur zeigen, wenn wirklich etwas offen ist - ein Abzeichen mit "0"
    // erzeugt Gewöhnung und wird dann auch bei "3" übersehen.
    const knopf = $("btn_meldungen");
    knopf.classList.toggle("versteckt", zahl.gesamt === 0);
    knopf.classList.toggle("still", zahl.sofort === 0);
    $("k_meldungen").textContent = zahl.gesamt;
  } catch { /* Abzeichen ist Beiwerk */ }
}

$("btn_meldungen").addEventListener("click", async () => {
  if (!zustand.inventurId) return;
  const liste = await api(`/inventuren/${zustand.inventurId}/markierungen`);
  const zahl = await api(`/inventuren/${zustand.inventurId}/markierungen/anzahl`);

  $("md_zusammenfassung").textContent = zahl.gesamt
    ? `${zahl.sofort} sofort · ${zahl.bald} heute · ${zahl.spaeter} kann warten`
    : "Nichts offen.";

  $("md_liste").innerHTML = liste.length ? liste.map((m) => `
    <li>
      <span class="stufe_chip stufe${m.dringlichkeit}">${m.dringlichkeit}</span>
      <span class="haupttext">
        <div>${m.grund}</div>
        <small>${m.gemeldet_von} · ${new Date(m.gemeldet_am).toLocaleTimeString("de-DE")}${m.bereich ? " · " + m.bereich : ""}${m.artikel ? " · " + m.artikel : ""}</small>
      </span>
      ${istAdmin() ? `<button class="knopf klein" data-erledigt="${m.id}">Erledigt</button>` : ""}
    </li>`).join("") : "<li><small>keine offenen Meldungen</small></li>";

  $("md_liste").querySelectorAll("[data-erledigt]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api(`/inventuren/${zustand.inventurId}/markierungen/${b.dataset.erledigt}/erledigt`,
                  { method: "POST", body: JSON.stringify({}) });
        b.closest("li").remove();
        await ladeMeldungsZahl();
      } catch (fehler) { alert(fehler.message); }
    }));

  oeffneSheet("sheet_meldungen");
});

/* ---------- Markieren ----------
   Zählerinnen korrigieren nicht selbst: sie halten fest, was nicht stimmt,
   und eine Administratorin entscheidet. Die Zählung bleibt unangetastet. */

let markierungBezug = null;
let markierungBereich = null;

function oeffneMarkierung(scanEventId = null, bereichId = null, bereichName = null) {
  markierungBezug = scanEventId;
  markierungBereich = bereichId || zustand.bereichId;
  $("mk_bezug").textContent = scanEventId
    ? "Zur letzten Buchung – was stimmt nicht?"
    : `${bereichName || zustand.bereichName || "Bereich"} – was stimmt nicht?`;
  $("mk_grund").value = "";
  oeffneSheet("sheet_markierung");
}

$("mk_stufen").querySelectorAll(".stufe").forEach((b) =>
  b.addEventListener("click", () => {
    $("mk_stufen").querySelectorAll(".stufe").forEach((x) => x.classList.remove("aktiv"));
    b.classList.add("aktiv");
  }));

$("mk_senden").addEventListener("click", async () => {
  const grund = $("mk_grund").value.trim();
  if (grund.length < 3) {
    $("mk_grund").focus();
    return;
  }
  const stufe = Number($("mk_stufen").querySelector(".stufe.aktiv").dataset.stufe);
  try {
    await api(`/inventuren/${zustand.inventurId}/markierungen`, {
      method: "POST",
      body: JSON.stringify({
        grund, dringlichkeit: stufe,
        scan_event_id: markierungBezug,
        zaehlbereich_id: markierungBezug ? null : markierungBereich,
      }),
    });
    schliesseSheets();
    await ladeMeldungsZahl();
    melde("info", "Gemeldet", "Markierung abgeschickt",
          `Dringlichkeit ${stufe} · die Zählung bleibt unverändert`);
  } catch (fehler) {
    melde("schlecht", "Fehler", fehler.message, "");
  }
});

/* ---------- Protokoll ---------- */

for (const id of ["meldung", "letzte"]) {
  $(id).addEventListener("click", async () => {
    if (!zustand.inventurId) return;
    oeffneSheet("sheet_log");
    await ladeLog();
  });
}

/* Kurzfassung unter dem Kamerakasten - nur die letzten drei, ohne Bedienung. */
async function ladeLetzte() {
  if (!zustand.inventurId) return;
  try {
    const eintraege = await api(`/inventuren/${zustand.inventurId}/log?grenze=3`);
    $("letzte_liste").innerHTML = eintraege.length ? eintraege.map((e) => `
      <li>
        <span class="menge ${e.menge < 0 ? "minus" : "plus"}">${e.menge > 0 ? "+" : ""}${e.menge}</span>
        <span class="haupttext">
          <div>${e.artikel}</div>
          <small>${new Date(e.erfasst_am).toLocaleTimeString("de-DE")} · ${e.erfasst_von}</small>
        </span>
      </li>`).join("") : "<li><small>noch nichts gezählt</small></li>";
  } catch { /* Anzeige ist Beiwerk, kein Grund für eine Fehlermeldung */ }
}

async function ladeLog() {
  const eintraege = await api(`/inventuren/${zustand.inventurId}/log?grenze=15`);
  $("log_liste").innerHTML = eintraege.length ? eintraege.map((e) => `
    <li>
      <span class="menge ${e.menge < 0 ? "minus" : "plus"}">${e.menge > 0 ? "+" : ""}${e.menge}</span>
      <span class="haupttext">
        <div>${e.artikel}</div>
        <small>${new Date(e.erfasst_am).toLocaleTimeString("de-DE")} · ${e.erfasst_von} · ${e.erfassungsart}</small>
      </span>
      ${e.stornierbar && istAdmin()
          ? `<button class="knopf klein" data-storno="${e.id}">Storno</button>` : ""}
    </li>`).join("") : "<li><small>noch nichts gezählt</small></li>";

  $("log_liste").querySelectorAll("[data-storno]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api(`/inventuren/${zustand.inventurId}/scans/${b.dataset.storno}/storno`,
                  { method: "POST" });
        zustand.teile = Math.max(0, zustand.teile - 1);
        merkeZustand(); aktualisiereKopf();
        await ladeLog();
      } catch (fehler) { alert(fehler.message); }
    }));
}

/* ---------- Kamera & Entprellung ---------- */

let strom = null, detektor = null, laeuft = false, startet = false;
let schleifenNr = 0;                // laufende Nummer der aktiven Scanschleife
const imFlug = new Set();           // Codes, deren Buchung gerade unterwegs ist
const gesehen = new Map();          // Code -> Zeitpunkt der letzten Sichtung
const VERSCHWUNDEN_MS = 700;        // so lange muss ein Code weg sein, um neu zu zaehlen

function entprellung(code, jetzt) {
  const zuletzt = gesehen.get(code);
  gesehen.set(code, jetzt);
  // Kein Eintrag = Code ist neu im Bild -> zaehlt. Liegt er dauerhaft im Bild,
  // wird sein Zeitstempel laufend erneuert und er zaehlt nicht erneut.
  return zuletzt === undefined;
}
function raeumeAuf(jetzt) {
  for (const [code, zeit] of gesehen)
    if (jetzt - zeit > VERSCHWUNDEN_MS) gesehen.delete(code);
}

async function starteKamera() {
  // Ohne diese Sperre startet ein zweiter Tap waehrend getUserMedia eine
  // zweite Scanschleife - beide lesen denselben Frame und buchen doppelt.
  if (laeuft || startet) return;
  startet = true;
  try {
    await starteKameraWirklich();
  } finally {
    startet = false;
  }
}

async function starteKameraWirklich() {
  if (!zustand.inventurId) {
    melde("info", "Noch nicht eingerichtet", "Erst eine Inventur wählen", "");
    return zeigeSeite("setup");
  }
  if (!("BarcodeDetector" in window)) {
    $("kamera_aus").innerHTML =
      "Dieser Browser kann keine Barcodes lesen.<br>" +
      "Android Chrome funktioniert. Auf dem iPhone bitte die Suche nutzen.";
    return;
  }
  try {
    strom = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false,
    });
    $("video").srcObject = strom;
    await $("video").play();

    detektor = new BarcodeDetector({
      formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"],
    });
    laeuft = true;
    $("kamera_aus").classList.add("versteckt");
    $("reticle").classList.remove("versteckt");
    $("b_kamera").textContent = "⏸";
    melde("", "Bereit", "Warte auf Barcode", "Etikett in den Rahmen halten");
    schleife(++schleifenNr);
  } catch (fehler) {
    $("kamera_aus").textContent = "Kamera nicht verfügbar: " + fehler.message;
  }
}

function stoppeKamera() {
  laeuft = false;
  schleifenNr += 1;                 // laufende Schleife verfaellt
  imFlug.clear();
  if (strom) strom.getTracks().forEach((t) => t.stop());
  strom = null; gesehen.clear();
  $("reticle").classList.add("versteckt");
  $("kamera_aus").classList.remove("versteckt");
  $("kamera_aus").textContent = "Kamera ist aus";
  $("b_kamera").textContent = "▣";
}

$("b_kamera").addEventListener("click", () => laeuft ? stoppeKamera() : starteKamera());

let letztePruefung = 0;
async function schleife(nr) {
  // Nur die zuletzt gestartete Schleife laeuft weiter. Eine aeltere beendet
  // sich hier von selbst, statt parallel weiterzuscannen.
  if (!laeuft || nr !== schleifenNr) return;
  const jetzt = performance.now();

  if (jetzt - letztePruefung > 120) {          // ~8 Prüfungen/s reichen völlig
    letztePruefung = jetzt;
    try {
      const treffer = await detektor.detect($("video"));
      raeumeAuf(jetzt);
      for (const t of treffer) {
        // Solange die Buchung eines Codes unterwegs ist, wird er nicht erneut
        // gebucht - auch dann nicht, wenn er zwischendurch aus dem Bild war.
        if (imFlug.has(t.rawValue)) continue;
        if (!entprellung(t.rawValue, jetzt)) continue;

        imFlug.add(t.rawValue);
        try {
          await sendeCode(t.rawValue);
        } finally {
          imFlug.delete(t.rawValue);
        }
      }
    } catch { /* einzelner Frame nicht lesbar - egal, der naechste kommt */ }
  }
  requestAnimationFrame(() => schleife(nr));
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden && laeuft) stoppeKamera();
});

/* ---------- Suche ---------- */

let suchTimer = null;
$("suchfeld").addEventListener("input", (e) => {
  clearTimeout(suchTimer);
  const text = e.target.value.trim();
  if (text.length < 2) { $("such_liste").innerHTML = "<li><small>mindestens zwei Zeichen</small></li>"; return; }
  suchTimer = setTimeout(async () => {
    const treffer = await api(
      `/inventuren/${zustand.inventurId}/suche?q=${encodeURIComponent(text)}`);
    $("such_liste").innerHTML = treffer.length ? treffer.map((t) => `
      <li>
        <span class="klecks" style="background:${farbfeld(t.farbe)}"></span>
        <span class="haupttext">
          <div>${t.marke} ${t.artikelname}</div>
          <small>${t.farbe} · Gr. ${t.groesse} · ${t.ean || "ohne EAN"}</small>
        </span>
        <button class="knopf klein" data-buche="${t.id}">+1</button>
      </li>`).join("") : "<li><small>nichts gefunden</small></li>";

    $("such_liste").querySelectorAll("[data-buche]").forEach((b) =>
      b.addEventListener("click", () => bucheDirekt(Number(b.dataset.buche), "manuell")));
  }, 250);
});

/* ---------- Auswertung ---------- */

const euro = (n) => n.toLocaleString("de-DE", { style: "currency", currency: "EUR" });

async function ladeAuswertung() {
  if (!zustand.inventurId) return;
  const a = await api(`/inventuren/${zustand.inventurId}/auswertung`);
  const k = a.kennzahlen;

  $("a_gezaehlt").textContent = k.gezaehlt_gesamt;
  $("a_fehl").textContent = k.fehlmenge;
  $("a_ueber").textContent = k.ueberbestand;
  $("a_wert").textContent = euro(k.differenz_wert);
  $("a_wert").style.color = k.differenz_wert < 0 ? "var(--schlecht)" : "var(--text)";
  $("a_fortschritt").textContent =
    `${k.positionen_gezaehlt} von ${k.positionen_gesamt} Artikeln berührt · ` +
    `${k.scans_gesamt} Scans · ${k.unbekannte_teile} unbekannte Teile`;

  $("a_tabelle").innerHTML = a.differenzen.slice(0, 25).map((d) => `
    <tr>
      <td>${d.artikel.marke} ${d.artikel.artikelname}<br>
          <small style="color:var(--leise)">${d.artikel.farbe} · ${d.artikel.groesse}</small></td>
      <td class="re">${d.buchbestand}</td>
      <td class="re">${d.gezaehlt}</td>
      <td class="re" style="color:${d.differenz < 0 ? "var(--schlecht)" : "var(--gut)"}">
        ${d.differenz > 0 ? "+" : ""}${d.differenz}</td>
    </tr>`).join("") || '<tr><td colspan="4"><small>keine Abweichungen</small></td></tr>';

  $("a_unbekannt_karte").classList.toggle("versteckt", a.unbekannte.length === 0);
  $("a_unbekannt").innerHTML = a.unbekannte.map((u) => `
    <li><span class="haupttext"><div>${u.ean || u.roh_code}</div></span>
        <span class="menge">${u.menge}×</span></li>`).join("");
}

$("b_export").addEventListener("click", () => {
  window.location.href = `/api/inventuren/${zustand.inventurId}/export.xlsx`;
});

/* ---------- Start ---------- */

async function starteApp() {
  $("feld_name").value = zustand.name || "";
  $("b_undo").textContent = istAdmin() ? "↺ Rückgängig" : "⚑ Markieren";
  aktualisiereKopf();
  try {
    await ladeInventuren();
    if (zustand.inventurId) {
      await ladeBereiche(); await ladeLetzte(); await ladeMeldungsZahl();
    }
  } catch (fehler) {
    console.error(fehler);
  }
}

(async function start() {
  ladeZustand();
  if (zustand.token) {
    $("anmeldung").classList.add("versteckt");
    await starteApp();
  } else {
    zeigeAnmeldung();
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
})();
