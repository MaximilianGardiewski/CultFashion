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
  letzterEventId: null, teile: 0, letzteFarbwahl: null,
};

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
  }));
}

async function api(pfad, optionen = {}) {
  const antwort = await fetch("/api" + pfad, {
    headers: optionen.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...optionen,
  });
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

const seiten = ["scan", "suche", "auswertung", "setup"];
function zeigeSeite(name) {
  seiten.forEach((s) => $("seite_" + s).classList.toggle("aktiv", s === name));
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("aktiv", b.dataset.seite === name));
  if (name === "auswertung") ladeAuswertung();
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

$("feld_name").addEventListener("change", (e) => {
  zustand.name = e.target.value.trim(); merkeZustand();
});

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
  const liste = await api(`/inventuren/${zustand.inventurId}/bereiche`);
  const feld = $("feld_bereich");
  feld.innerHTML = liste.length
    ? liste.map((b) => `<option value="${b.id}">${b.name} · ${b.teile} Teile</option>`).join("")
    : '<option value="">– noch keiner –</option>';

  if (!liste.some((b) => b.id === zustand.bereichId)) {
    zustand.bereichId = liste.length ? liste[0].id : null;
  }
  if (zustand.bereichId) feld.value = String(zustand.bereichId);

  const aktiv = liste.find((b) => b.id === zustand.bereichId);
  zustand.bereichName = aktiv ? aktiv.name : "";
  zustand.teile = aktiv ? aktiv.teile : 0;
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
  } catch (fehler) { melde("schlecht", "Storno nicht möglich", fehler.message, ""); }
});

/* ---------- Protokoll ---------- */

$("meldung").addEventListener("click", async () => {
  if (!zustand.inventurId) return;
  oeffneSheet("sheet_log");
  await ladeLog();
});

async function ladeLog() {
  const eintraege = await api(`/inventuren/${zustand.inventurId}/log?grenze=15`);
  $("log_liste").innerHTML = eintraege.length ? eintraege.map((e) => `
    <li>
      <span class="menge ${e.menge < 0 ? "minus" : "plus"}">${e.menge > 0 ? "+" : ""}${e.menge}</span>
      <span class="haupttext">
        <div>${e.artikel}</div>
        <small>${new Date(e.erfasst_am).toLocaleTimeString("de-DE")} · ${e.erfasst_von} · ${e.erfassungsart}</small>
      </span>
      ${e.stornierbar ? `<button class="knopf klein" data-storno="${e.id}">Storno</button>` : ""}
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

let strom = null, detektor = null, laeuft = false;
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
    schleife();
  } catch (fehler) {
    $("kamera_aus").textContent = "Kamera nicht verfügbar: " + fehler.message;
  }
}

function stoppeKamera() {
  laeuft = false;
  if (strom) strom.getTracks().forEach((t) => t.stop());
  strom = null; gesehen.clear();
  $("reticle").classList.add("versteckt");
  $("kamera_aus").classList.remove("versteckt");
  $("kamera_aus").textContent = "Kamera ist aus";
  $("b_kamera").textContent = "▣";
}

$("b_kamera").addEventListener("click", () => laeuft ? stoppeKamera() : starteKamera());

let letztePruefung = 0;
async function schleife() {
  if (!laeuft) return;
  const jetzt = performance.now();

  if (jetzt - letztePruefung > 120) {          // ~8 Prüfungen/s reichen völlig
    letztePruefung = jetzt;
    try {
      const treffer = await detektor.detect($("video"));
      raeumeAuf(jetzt);
      for (const t of treffer) {
        if (entprellung(t.rawValue, jetzt)) await sendeCode(t.rawValue);
      }
    } catch { /* einzelner Frame nicht lesbar - egal, der naechste kommt */ }
  }
  requestAnimationFrame(schleife);
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

(async function start() {
  ladeZustand();
  $("feld_name").value = zustand.name || "";
  aktualisiereKopf();
  try {
    await ladeInventuren();
    if (zustand.inventurId) await ladeBereiche();
  } catch (fehler) {
    console.error(fehler);
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
})();
