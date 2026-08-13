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
  inventurId: null, bereichId: null, name: "", letzterEventId: null,
  scans: 0, teile: 0, unbekannt: 0, letzteFarbwahl: null,
};

/* ---------- Speicher & API ---------- */

function ladeZustand() {
  try {
    Object.assign(zustand, JSON.parse(localStorage.getItem("inventur") || "{}"));
  } catch { /* verworfene Einstellungen sind kein Grund zum Absturz */ }
}
function merkeZustand() {
  localStorage.setItem("inventur", JSON.stringify({
    inventurId: zustand.inventurId, bereichId: zustand.bereichId, name: zustand.name,
  }));
}

async function api(pfad, optionen = {}) {
  const antwort = await fetch("/api" + pfad, {
    headers: optionen.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...optionen,
  });
  if (!antwort.ok) {
    let text = antwort.statusText;
    try { text = (await antwort.json()).detail || text; } catch { /* kein JSON */ }
    throw new Error(text);
  }
  return antwort.status === 204 ? null : antwort.json();
}

/* ---------- Rueckmeldung: sehen, hoeren, spueren ---------- */

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

function melde(art, titel, zeile2, zahl) {
  const box = $("rueckmeldung");
  box.className = art;
  $("rm_titel").textContent = titel;
  $("rm_zeile2").textContent = zeile2 || "";
  $("rm_zahl").textContent = zahl == null ? "" : zahl;

  if (art === "ok") { ton(880); vibriere(35); }
  else if (art === "warn") { ton(520, 0.14); vibriere([25, 45, 25]); }
  else if (art === "fehler") { ton(180, 0.28); vibriere([70, 60, 70]); }
}

/* ---------- Navigation ---------- */

const seiten = ["scan", "suche", "auswertung", "setup"];
function zeigeSeite(name) {
  seiten.forEach((s) => $("seite_" + s).classList.toggle("versteckt", s !== name));
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("aktiv", b.dataset.seite === name));
  if (name === "auswertung") ladeAuswertung();
  if (name === "scan") ladeLog();
}
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => {
    if (b.dataset.seite !== "setup" && !zustand.inventurId) {
      alert("Bitte zuerst im Setup eine Inventur auswählen.");
      return zeigeSeite("setup");
    }
    zeigeSeite(b.dataset.seite);
  }));

function aktualisiereKopf() {
  $("kopf_info").textContent = zustand.inventurId
    ? `${zustand.name || "ohne Namen"} · Inventur ${zustand.inventurId}` +
      (zustand.bereichId ? "" : " · kein Bereich")
    : "nicht eingerichtet";
}

/* ---------- Setup ---------- */

async function ladeInventuren() {
  const liste = await api("/inventuren");
  const feld = $("feld_inventur");
  feld.innerHTML = liste.length
    ? liste.map((i) =>
        `<option value="${i.id}">#${i.id} · ${i.bezeichnung} · ${i.positionen} Artikel · ${i.status}</option>`
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
  zustand.inventurId = inventur.id; zustand.bereichId = null;
  merkeZustand(); await ladeInventuren(); await ladeBereiche(); aktualisiereKopf();
});

$("btn_laden").addEventListener("click", async () => {
  const wert = $("feld_inventur").value;
  if (!wert) return;
  zustand.inventurId = Number(wert); zustand.bereichId = null;
  merkeZustand(); await ladeBereiche(); aktualisiereKopf();
});

$("feld_name").addEventListener("change", (e) => {
  zustand.name = e.target.value.trim(); merkeZustand(); aktualisiereKopf();
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
      `<div class="warnbox" style="background:#152a1e;border-color:var(--ok)">
         <b>${e.zeilen_importiert} Artikel importiert</b><br>
         ${e.zeilen_uebersprungen} Zeilen übersprungen (Titel, Zwischensummen)
       </div>
       <p class="hinweis"><b>Erkannte Spalten:</b><br>${spalten}</p>` +
      (e.hinweise.length
        ? `<div class="warnbox">${e.hinweise.length} Hinweise:<br>` +
          e.hinweise.slice(0, 8).map((h) => "· " + h).join("<br>") + "</div>"
        : "");
    await ladeInventuren();
  } catch (fehler) {
    $("import_ergebnis").innerHTML =
      `<div class="warnbox" style="border-color:var(--fehler)">${fehler.message}</div>`;
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
  if (zustand.bereichId) feld.value = String(zustand.bereichId);
  else if (liste.length) { zustand.bereichId = liste[0].id; merkeZustand(); }
  const aktiv = liste.find((b) => b.id === zustand.bereichId);
  if (aktiv) { zustand.teile = aktiv.teile; $("z_teile").textContent = aktiv.teile; }
  aktualisiereKopf();
}

$("feld_bereich").addEventListener("change", (e) => {
  zustand.bereichId = Number(e.target.value) || null; merkeZustand(); ladeBereiche();
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

/* ---------- Buchen ---------- */

async function verarbeite(antwort, rohCode) {
  if (antwort.ergebnis === "ungueltig") {
    melde("fehler", "Code ungültig", "Prüfziffer stimmt nicht – bitte erneut scannen");
    return;
  }
  if (antwort.ergebnis === "unbekannt") {
    zustand.unbekannt += 1; zustand.scans += 1;
    $("z_unbekannt").textContent = zustand.unbekannt;
    $("z_scans").textContent = zustand.scans;
    zustand.letzterEventId = antwort.event_id;
    $("btn_undo").disabled = false;
    melde("warn", "Nicht im Sollbestand", `${antwort.ean} – als unbekannt erfasst`);
    ladeLog();
    return;
  }
  if (antwort.ergebnis === "mehrdeutig") {
    ton(520, 0.08); vibriere(20);
    zeigeAuswahl(antwort, rohCode);
    return;
  }

  const a = antwort.artikel;
  zustand.scans += 1; zustand.teile += 1;
  $("z_scans").textContent = zustand.scans;
  $("z_teile").textContent = zustand.teile;
  zustand.letzterEventId = antwort.event_id;
  $("btn_undo").disabled = false;
  melde("ok", `${a.marke} ${a.artikelname}`,
        `${a.farbe} · Gr. ${a.groesse}`, antwort.gezaehlt);
  ladeLog();
}

async function bucheDirekt(positionId, art, rohCode) {
  try {
    const antwort = await api(`/inventuren/${zustand.inventurId}/buchung`, {
      method: "POST",
      body: JSON.stringify({
        position_id: positionId, zaehlbereich_id: zustand.bereichId,
        erfasst_von: zustand.name || "unbekannt", roh_code: rohCode || null,
        erfassungsart: art, geraet: navigator.platform || null,
      }),
    });
    await verarbeite(antwort, rohCode);
  } catch (fehler) { melde("fehler", "Fehler", fehler.message); }
}

async function sendeCode(code) {
  try {
    const antwort = await api(`/inventuren/${zustand.inventurId}/scan`, {
      method: "POST",
      body: JSON.stringify({
        code, zaehlbereich_id: zustand.bereichId,
        erfasst_von: zustand.name || "unbekannt", geraet: navigator.platform || null,
      }),
    });
    await verarbeite(antwort, code);
  } catch (fehler) { melde("fehler", "Fehler", fehler.message); }
}

/* ---------- Auswahl bei mehrdeutiger EAN ---------- */

function zeigeAuswahl(antwort, rohCode) {
  const dlg = $("dlg_auswahl");
  $("dlg_grund").textContent =
    `${antwort.kandidaten.length} Artikel teilen die EAN ${antwort.ean}`;

  // Zuletzt gewaehlte Farbe nach oben: bei einer Serie gleicher Teile spart das viel
  const kandidaten = [...antwort.kandidaten].sort((a, b) =>
    (b.farbe === zustand.letzteFarbwahl) - (a.farbe === zustand.letzteFarbwahl));

  $("dlg_liste").innerHTML = kandidaten.map((k) => `
    <button class="wahl" data-id="${k.id}" data-farbe="${k.farbe}">
      <b>${k.marke} ${k.artikelname}</b>
      <small>${k.farbe} (${k.farbnummer}) · Gr. ${k.groesse}</small>
    </button>`).join("");

  $("dlg_liste").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      zustand.letzteFarbwahl = b.dataset.farbe;
      dlg.close();
      bucheDirekt(Number(b.dataset.id), "auswahl", rohCode);
    }));

  dlg.showModal();
}
$("dlg_abbruch").addEventListener("click", () => $("dlg_auswahl").close());

/* ---------- Storno ---------- */

$("btn_undo").addEventListener("click", async () => {
  if (!zustand.letzterEventId) return;
  try {
    const antwort = await api(
      `/inventuren/${zustand.inventurId}/scans/${zustand.letzterEventId}/storno` +
      `?erfasst_von=${encodeURIComponent(zustand.name || "unbekannt")}`,
      { method: "POST" });
    zustand.teile = Math.max(0, zustand.teile - 1);
    $("z_teile").textContent = zustand.teile;
    zustand.letzterEventId = null;
    $("btn_undo").disabled = true;
    melde("warn", "Storniert", antwort.artikel
      ? `${antwort.artikel.artikelname} · jetzt ${antwort.gezaehlt}` : "");
    ladeLog();
  } catch (fehler) { melde("fehler", "Storno nicht möglich", fehler.message); }
});

/* ---------- Log ---------- */

async function ladeLog() {
  if (!zustand.inventurId) return;
  const eintraege = await api(`/inventuren/${zustand.inventurId}/log?grenze=12`);
  $("log_liste").innerHTML = eintraege.length ? eintraege.map((e) => `
    <li>
      <span class="menge ${e.menge < 0 ? "minus" : "plus"}">${e.menge > 0 ? "+" : ""}${e.menge}</span>
      <span class="haupttext">
        <div>${e.artikel}</div>
        <small>${new Date(e.erfasst_am).toLocaleTimeString("de-DE")} · ${e.erfasst_von} · ${e.erfassungsart}</small>
      </span>
      ${e.stornierbar ? `<button class="klein" data-storno="${e.id}">Storno</button>` : ""}
    </li>`).join("") : "<li><small>noch nichts</small></li>";

  $("log_liste").querySelectorAll("[data-storno]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api(`/inventuren/${zustand.inventurId}/scans/${b.dataset.storno}/storno`,
                  { method: "POST" });
        melde("warn", "Storniert", "");
        ladeLog();
      } catch (fehler) { melde("fehler", "Storno nicht möglich", fehler.message); }
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
  if (!zustand.inventurId) { alert("Erst im Setup eine Inventur wählen."); return; }
  if (!("BarcodeDetector" in window)) {
    $("kamera_hinweis").innerHTML =
      "Dieser Browser kann keine Barcodes lesen.<br>" +
      "Android Chrome funktioniert. Auf dem iPhone bitte vorerst die Suche nutzen.";
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
    $("kamera_hinweis").classList.add("versteckt");
    $("zielrahmen").classList.remove("versteckt");
    $("btn_kamera").textContent = "Kamera stoppen";
    schleife();
  } catch (fehler) {
    $("kamera_hinweis").textContent = "Kamera nicht verfügbar: " + fehler.message;
  }
}

function stoppeKamera() {
  laeuft = false;
  if (strom) strom.getTracks().forEach((t) => t.stop());
  strom = null; gesehen.clear();
  $("zielrahmen").classList.add("versteckt");
  $("kamera_hinweis").classList.remove("versteckt");
  $("kamera_hinweis").textContent = "Kamera ist aus";
  $("btn_kamera").textContent = "Kamera starten";
}

$("btn_kamera").addEventListener("click", () => laeuft ? stoppeKamera() : starteKamera());

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
  if (text.length < 2) { $("such_liste").innerHTML = ""; return; }
  suchTimer = setTimeout(async () => {
    const treffer = await api(
      `/inventuren/${zustand.inventurId}/suche?q=${encodeURIComponent(text)}`);
    $("such_liste").innerHTML = treffer.length ? treffer.map((t) => `
      <li>
        <span class="haupttext">
          <div>${t.marke} ${t.artikelname}</div>
          <small>${t.farbe} · Gr. ${t.groesse} · ${t.ean || "ohne EAN"}</small>
        </span>
        <button class="klein" data-buche="${t.id}">+1</button>
      </li>`).join("") : "<li><small>nichts gefunden</small></li>";

    $("such_liste").querySelectorAll("[data-buche]").forEach((b) =>
      b.addEventListener("click", () => bucheDirekt(Number(b.dataset.buche), "manuell")));
  }, 250);
});

/* ---------- Auswertung ---------- */

const euro = (n) => n.toLocaleString("de-DE",
  { style: "currency", currency: "EUR" });

async function ladeAuswertung() {
  if (!zustand.inventurId) return;
  const a = await api(`/inventuren/${zustand.inventurId}/auswertung`);
  const k = a.kennzahlen;

  $("a_gezaehlt").textContent = k.gezaehlt_gesamt;
  $("a_fehl").textContent = k.fehlmenge;
  $("a_ueber").textContent = k.ueberbestand;
  $("a_wert").textContent = euro(k.differenz_wert);
  $("a_fortschritt").textContent =
    `${k.positionen_gezaehlt} von ${k.positionen_gesamt} Artikeln berührt · ` +
    `${k.scans_gesamt} Scans · ${k.unbekannte_teile} unbekannte Teile`;

  $("a_tabelle").innerHTML = a.differenzen.slice(0, 25).map((d) => `
    <tr>
      <td>${d.artikel.marke} ${d.artikel.artikelname}<br>
          <small style="color:var(--gedimmt)">${d.artikel.farbe} · ${d.artikel.groesse}</small></td>
      <td class="zahl_re">${d.buchbestand}</td>
      <td class="zahl_re">${d.gezaehlt}</td>
      <td class="zahl_re ${d.differenz < 0 ? "minus" : "plus"}">
        ${d.differenz > 0 ? "+" : ""}${d.differenz}</td>
    </tr>`).join("") || '<tr><td colspan="4"><small>keine Abweichungen</small></td></tr>';

  $("a_unbekannt_karte").classList.toggle("versteckt", a.unbekannte.length === 0);
  $("a_unbekannt").innerHTML = a.unbekannte.map((u) => `
    <li><span class="haupttext"><div>${u.ean || u.roh_code}</div></span>
        <span class="menge">${u.menge}×</span></li>`).join("");
}

$("btn_export").addEventListener("click", () => {
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
