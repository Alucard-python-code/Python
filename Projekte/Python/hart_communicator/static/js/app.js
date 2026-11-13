/* =============================================================================
   HART-Communicator – Oberfläche (ohne externe Bibliotheken, offline-fähig)
   Live-Daten per Server-Sent Events (/api/events), Aktionen per REST (/api/*).
   ============================================================================= */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, nd = 2) => (v == null || Number.isNaN(Number(v)) ? "–" : Number(v).toFixed(nd).replace(".", ","));
const sgn = (v, nd = 3) => (v == null ? "–" : (v >= 0 ? "+" : "") + num(v, nd));
const parseNum = (s) => (s == null || String(s).trim() === "" ? null : Number(String(s).replace(",", ".")));

/* ------------------------------------------------------------------ Icons */
const svg = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const ICON = {
  lock: svg('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
  unlock: svg('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>'),
  hand: svg('<path d="M8 13V5a1.5 1.5 0 0 1 3 0v6M11 11V4a1.5 1.5 0 0 1 3 0v7M14 11V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-3l-2-4a1.5 1.5 0 0 1 2.6-1.5L8 13"/>'),
  printer: svg('<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>'),
  usb: svg('<circle cx="12" cy="20" r="2"/><path d="M12 18V3M9 6l3-3 3 3M12 14l-5-3V8M12 12l5-3V7"/><rect x="15" y="5" width="4" height="3"/><circle cx="7" cy="7" r="1.5"/>'),
  plug: svg('<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/>'),
  torch: svg('<path d="M8 2h8l-1 6H9zM9 8h6v13H9z"/><path d="M12 12v3"/>'),
  rotate: svg('<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/>'),
  rotlock: svg('<rect x="8" y="11" width="8" height="7" rx="1"/><path d="M10 11V9a2 2 0 0 1 4 0v2"/><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5"/>'),
  order: svg('<path d="M9 3h6l1 2h3v16H5V5h3z"/><path d="M9 12h6M9 16h4"/>'),
  device: svg('<circle cx="12" cy="10" r="6"/><path d="M12 10l3-3M9 21h6M12 16v5"/>'),
  cal: svg('<path d="M3 20h18M6 16l4-5 3 3 5-7"/><circle cx="18" cy="7" r="1.5"/>'),
  sniffer: svg('<path d="M2 12h3l2-6 4 12 3-9 2 3h6"/>'),
  settings: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  camera: svg('<path d="M3 8h4l2-3h6l2 3h4v12H3z"/><circle cx="12" cy="13" r="4"/>'),
  qr: svg('<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM20 14v7h-3M14 20h1"/>'),
  scan: svg('<path d="M2 12h3M19 12h3M12 2v3M12 19v3"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
  check: svg('<path d="M5 13l4 4L19 7"/>'),
};

/* ------------------------------------------------------------------ Zustand */
const S = {
  view: "order", status: {}, wf: {}, live: null, sniff: [], sniffPaused: false, selPoint: 0,
  touchBlocked: false, oskEnabled: true, overlayOnClose: null,
};
const CASE_LABEL = { NACHKALIBRIERUNG: "Nachkalibrierung", GERAETETAUSCH: "Gerätetausch", NEUAUFNAHME: "Neuaufnahme" };
const caseLabel = (c) => CASE_LABEL[c] || c;
const UNITS = [[8, "mbar"], [7, "bar"], [12, "kPa"], [237, "MPa"], [6, "psi"], [1, "inH2O"], [32, "°C"], [33, "°F"],
  [35, "K"], [57, "%"], [39, "mA"], [45, "m"], [49, "mm"], [19, "m³/h"], [17, "l/min"], [75, "kg/h"], [73, "kg/s"]];

/* ------------------------------------------------------------------ REST */
async function api(path, data, method) {
  const opt = data === undefined && !method ? {} :
    { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data || {}) };
  const r = await fetch(path, opt);
  let j = null;
  try { j = await r.json(); } catch (_) { /* leer */ }
  if (!r.ok) {
    const msg = (j && j.error) || `Fehler ${r.status}`;
    toast(msg, "error");
    throw new Error(msg);
  }
  return j;
}

/** Button sperren, Text ersetzen, Aktion ausführen, wiederherstellen. */
async function busy(btn, label, fn) {
  const old = btn ? btn.innerHTML : null;
  if (btn) { btn.disabled = true; btn.innerHTML = esc(label); }
  try { return await fn(); }
  catch (e) { return null; }
  finally { if (btn && document.body.contains(btn)) { btn.disabled = false; btn.innerHTML = old; } }
}

function toast(text, level = "info", ms = 4200) {
  const t = document.createElement("div");
  t.className = `toast ${level}`;
  t.textContent = text;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), ms);
}

/* ------------------------------------------------------------------ Navigation */
function setView(v) {
  hideOsk();
  S.view = v;
  document.body.className = document.body.className.replace(/\bview-\w+/g, "").trim() + ` view-${v}`;
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  render();
  $("#main").scrollTop = 0;
}

function render() {
  // Inaktive Ansichten leeren -> Element-IDs sind immer eindeutig
  $$(".view").forEach((v) => { if (v.id !== `view-${S.view}`) v.innerHTML = ""; });
  ({ order: renderOrder, device: renderDevice, cal: renderCal, sniffer: renderSniffer,
     export: renderExport, settings: renderSettings })[S.view]();
  renderLive();
}

/* ------------------------------------------------------------------ Statusleiste */
function renderStatus() {
  const st = S.status;
  if (!st || !st.time) return;
  $(".sb-order-no").textContent = st.order ? st.order.order_no : "Kein Auftrag";
  $(".sb-order-cust").textContent = st.order ? st.order.customer : "Auftrag öffnen";

  const safe = $("#sb-safe");
  safe.innerHTML = st.safe_mode ? ICON.lock : ICON.unlock;
  safe.className = `sb-icon ${st.safe_mode ? "ok" : "err"}`;
  safe.title = st.safe_mode ? "24/7-Safe-Mode AKTIV (nur Lesen)" : "Safe-Mode AUS – Schreiben ins Feldgerät erlaubt";

  const touch = $("#sb-touch");
  touch.innerHTML = ICON.hand;
  touch.className = `sb-icon warn ${st.touch_blocked ? "" : "hidden"}`;
  touch.title = (st.touch_block_reasons || []).join(", ");

  const p = st.printer || {};
  const pcls = { ready: "ok", busy: "on", error: "err", offline: "warn" }[p.state] || "dim";
  $("#sb-printer").innerHTML = ICON.printer;
  $("#sb-printer").className = `sb-icon ${pcls}`;
  $("#sb-printer").title = `Drucker: ${p.text || "unbekannt"}`;

  const dock = $("#sb-dock");
  dock.innerHTML = st.export && st.export.pc_published ? ICON.usb : ICON.plug;
  dock.className = `sb-icon ${st.export && st.export.pc_published ? "ok" : st.dock ? "on" : "dim"}`;
  dock.title = st.dock ? (st.export.pc_published ? "Angedockt – Laufwerk HART_EXPORT am PC" : "Angedockt") : "Nicht angedockt";

  $("#sb-torch").innerHTML = ICON.torch;
  $("#sb-torch").className = `sb-icon ${st.torch ? "on" : "dim"}`;
  const rot = st.rotation || {};
  $("#sb-rot").innerHTML = rot.locked ? ICON.rotlock : ICON.rotate;
  $("#sb-rot").className = `sb-icon ${rot.locked ? "warn" : "dim"}`;
  $("#sb-rot").title = rot.locked ? "Drehung gesperrt" : "Automatische Drehung";

  $("#sb-hours").textContent = `${num(st.runtime_hours, 1)} h`;
  const b = st.battery;
  const bat = $("#sb-bat");
  bat.className = `sb-bat ${b ? b.level : ""}`;
  bat.innerHTML = b ? `<b>${b.charging ? "⚡" : ""}${num(b.soc, 0)} %</b><span>${num(b.voltage, 1)} V</span>` : "<b>–</b>";
  const t = $("#sb-time");
  t.textContent = (st.time || "").slice(11, 16);
  t.className = `sb-time ${st.time_trusted ? "" : "untrusted"}`;
  t.title = `Zeitquelle: ${st.time_source}`;

  S.touchBlocked = !!st.touch_blocked;
  S.oskEnabled = !!st.osk_enabled;
  document.body.classList.toggle("kbd", !!st.keyboard_navigation);
  if (!S.oskEnabled) hideOsk();

  const banner = $("#banner");
  if (st.touch_blocked) {
    banner.className = "banner warn";
    banner.textContent = `Touch gesperrt: ${(st.touch_block_reasons || []).join(" · ")}`;
  } else if (st.simulated) {
    banner.className = "banner info";
    banner.textContent = "SIMULATIONSMODUS – keine echte Hardware angeschlossen";
  } else banner.className = "banner hidden";
}

/* ------------------------------------------------------------------ Auftrag */
async function renderOrder() {
  const el = $("#view-order");
  const [o, orders] = await Promise.all([api("/api/order"), api("/api/orders")]);
  let html = "";
  if (o) {
    const s = o.summary;
    html += `<div class="card accent"><h3>Offener Auftrag</h3>
      <div class="tag">${esc(o.order_no)}</div><p class="muted">${esc(o.description || "")}</p>
      <dl class="kv"><dt>Kunde</dt><dd>${esc(o.customer_name)} ${o.customer_no ? `(${esc(o.customer_no)})` : ""}</dd>
      <dt>Prüfer</dt><dd>${esc(o.technician)}</dd><dt>Geöffnet</dt><dd>${new Date(o.opened_at * 1000).toLocaleString("de-DE")}</dd>
      <dt>Geräte beim Kunden</dt><dd>${o.devices.length}</dd></dl>
      <div class="row" style="margin-top:12px">
        <span class="badge info">${s.calibrations} geprüft</span><span class="badge ok">${s.passed} bestanden</span>
        <span class="badge ${s.failed ? "err" : "info"}">${s.failed} nicht bestanden</span>
        <span class="badge ${s.swaps ? "warn" : "info"}">${s.swaps} Tausch</span><span class="badge info">${s.new_devices} neu</span></div>
      ${o.entries.length ? `<div class="tbl-wrap" style="margin-top:12px"><table class="data"><tr><th>TAG</th><th>Gerät</th><th>Prüfart</th><th>Ergebnis</th></tr>
        ${o.entries.map((e) => `<tr><td><b>${esc(e.tag)}</b></td><td>${esc(e.name || "")}</td><td>${esc(caseLabel(e.case))}</td>
        <td class="${e.result === "BESTANDEN" ? "pos" : "neg"}">${esc(e.result)}</td></tr>`).join("")}</table></div>` : ""}
      <div class="btn-row"><button class="btn primary" data-goto="device">${ICON.device} Gerät anschließen</button>
        <button class="btn danger" id="btn-close-order">${ICON.check} Auftrag abschließen & PDF</button></div></div>`;
  } else {
    const customers = await api("/api/customers");
    html += `<div class="card accent"><h3>Neuen Auftrag öffnen</h3>
      <label class="field">Kunde<select id="o-cust">${customers.map((c) => `<option value="${c.id}">${esc(c.name)}${c.customer_no ? ` (${esc(c.customer_no)})` : ""} – ${c.device_count} Geräte</option>`).join("")}
        <option value="new">+ Neuer Kunde …</option></select></label>
      <div id="o-newcust" class="${customers.length ? "hidden" : ""}" style="margin-top:8px">
        <div class="grid2"><label class="field">Kundenname<input type="text" class="kb" id="c-name"></label>
        <label class="field">Kundennummer<input type="text" class="kb" id="c-no"></label></div>
        <label class="field" style="margin-top:8px">Anschrift<input type="text" class="kb" id="c-addr"></label></div>
      <div class="grid2" style="margin-top:8px"><label class="field">Auftragsnummer<input type="text" class="kb" id="o-no" placeholder="z.B. A-2026-0815"></label>
        <label class="field">Prüfer<input type="text" class="kb" id="o-tech" value="${esc(localStorage.getItem("tech") || "")}"></label></div>
      <label class="field" style="margin-top:8px">Beschreibung<input type="text" class="kb" id="o-desc" data-enter="#btn-open-order"></label>
      <div class="btn-row"><button class="btn primary" id="btn-open-order" data-primary>Auftrag öffnen</button></div></div>`;
  }
  const closed = (orders || []).filter((x) => x.status === "CLOSED").slice(0, 8);
  if (closed.length) {
    html += `<div class="card"><h3>Abgeschlossene Aufträge</h3><table class="data">
      ${closed.map((x) => `<tr><td><b>${esc(x.order_no)}</b><br><span class="muted">${esc(x.customer_name)}</span></td>
      <td>${new Date(x.closed_at * 1000).toLocaleDateString("de-DE")}</td>
      <td>${x.pdf_url ? `<a class="btn" href="${x.pdf_url}" target="_blank">PDF</a>` : "–"}</td></tr>`).join("")}</table></div>`;
  }
  el.innerHTML = html;
  bindKb(el);

  const sel = $("#o-cust", el);
  if (sel) {
    if (!sel.options.length || sel.value === "new") $("#o-newcust").classList.remove("hidden");
    sel.onchange = () => $("#o-newcust").classList.toggle("hidden", sel.value !== "new");
    $("#btn-open-order").onclick = (ev) => busy(ev.currentTarget, "Öffne …", async () => {
      let cid = sel.value;
      if (cid === "new") {
        const c = await api("/api/customers", { name: $("#c-name").value, customer_no: $("#c-no").value, address: $("#c-addr").value });
        cid = c.id;
      }
      localStorage.setItem("tech", $("#o-tech").value);
      await api("/api/order", { customer_id: cid, order_no: $("#o-no").value, technician: $("#o-tech").value, description: $("#o-desc").value });
      toast("Auftrag geöffnet", "ok");
      setView("device");
    });
  }
  const cbtn = $("#btn-close-order", el);
  if (cbtn) cbtn.onclick = async () => {
    if (!(await confirmDialog("Auftrag abschließen?", "Der Auftrag wird geschlossen und das Gesamt-PDF (Deckblatt, Geräteseiten, Kunden-Rückläufer) erstellt. Danach sind keine Prüfungen mehr in diesem Auftrag möglich.", "Abschließen & PDF erstellen", "primary"))) return;
    const res = await busy(cbtn, "Erstelle PDF …", () => api("/api/order/close", {}));
    if (!res) return;
    openSheet(`<h2>Auftrag abgeschlossen</h2><p>Prüfbericht mit ${res.pdf.pages} Seiten erstellt.</p>
      <p class="muted mono" style="font-size:12px">SHA-256 ${esc(res.pdf.sha256.slice(0, 32))}…</p>
      <div class="btn-row"><a class="btn primary" href="${res.pdf.url}" target="_blank">PDF öffnen</a>
      <button class="btn" data-goto="export" data-close>Exportieren</button></div>`);
    renderOrder();
  };
}

/* ------------------------------------------------------------------ Gerät */
function needOrder(el) {
  if (S.status.order) return false;
  el.innerHTML = `<div class="card warn"><h3>Kein offener Auftrag</h3><p>Jede Prüfung läuft innerhalb eines Kundenauftrags.</p>
    <button class="btn primary block" data-goto="order">Auftrag öffnen</button></div>`;
  return true;
}

function loopCard() {
  const lm = (S.status.loop || {}).mode || "PASSIVE";
  const opts = [["PASSIVE", "Passiv"], ["PASSIVE_250R", "Passiv + 250 Ω"], ["ACTIVE_24V", "Aktiv 24 V"]];
  return `<div class="card"><h3>Schleife</h3><div class="seg" id="loop-seg">
    ${opts.map(([v, l]) => `<button data-loop="${v}" class="${lm === v ? "active" : ""}">${l}</button>`).join("")}</div>
    <p class="muted" style="font-size:13px;margin:8px 0 0">${esc((S.status.loop || {}).label || "")}</p></div>`;
}

function renderDevice() {
  const el = $("#view-device");
  if (needOrder(el)) return;
  const w = S.wf;
  let html = `<div class="card"><div class="btn-row" style="margin-top:0">
      <button class="btn primary" id="btn-scan" data-primary>${ICON.scan} HART-Scan</button>
      <button class="btn" id="btn-qr">${ICON.qr} QR scannen</button></div>
      <label class="field" style="margin-top:10px">Polling-Adresse<select id="poll">${[...Array(16).keys()].map((i) => `<option>${i}</option>`).join("")}</select></label></div>`;
  if (w.qr && !w.info) {
    html += `<div class="card accent"><h3>QR-Vorauswahl</h3><div class="tag">${esc(w.qr.tag)}</div>
      <p class="muted mono">${esc(w.qr.uid || "ohne UID")}</p><p>${w.qr.known_device ? "In der Datenbank bekannt." : "Noch nicht in der Datenbank."} Gerät anklemmen und HART-Scan starten.</p></div>`;
  }
  if (w.info) html += deviceCard(w) + casePanel(w);
  html += loopCard();
  el.innerHTML = html;
  bindKb(el);

  $("#btn-scan").onclick = (ev) => busy(ev.currentTarget, "Suche Gerät …", async () => {
    S.wf = await api("/api/identify/hart", { poll_address: Number($("#poll").value) });
    renderDevice();
  });
  $("#btn-qr").onclick = () => openCamera("scan");
  $$("[data-loop]", el).forEach((b) => (b.onclick = () => setLoop(b.dataset.loop)));
  bindCase(el);
}

function deviceCard(w) {
  const i = w.info, r = i.range || {}, pv = (i.dynamic || {}).pv || {};
  const cat = i.catalog || {};
  return `<div class="card"><h3>Angeschlossenes Gerät</h3>
    <div class="row"><div><div class="tag">${esc(i.tag)}</div><div class="muted">${esc(i.descriptor)}</div></div>
    <div style="flex:0 0 auto">${w.is_positioner ? '<span class="badge info">Stellungsregler</span>' : ""}
    ${cat.needs_confirmation ? '<span class="badge warn">Typ prüfen</span>' : ""}</div></div>
    <dl class="kv" style="margin-top:10px"><dt>Gerät</dt><dd>${esc(i.display_name)}</dd>
    <dt>Unique-ID</dt><dd class="mono">${esc(i.unique_id)}</dd><dt>HART</dt><dd>Rev ${esc(i.universal_rev)} · Geräterev ${esc(i.device_rev)} · Poll ${esc(i.poll_address)}</dd>
    <dt>Messbereich</dt><dd>${num(r.lower_range, 3)} … ${num(r.upper_range, 3)} ${esc(r.unit || "")}</dd>
    <dt>PV</dt><dd>${num(pv.value, 3)} ${esc(pv.unit || "")}</dd></dl></div>`;
}

function casePanel(w) {
  const m = w.match || {}, d = w.device;
  const startBtns = `<div class="btn-row"><button class="btn primary" id="btn-start" data-primary>${ICON.cal} Kalibrierung starten</button>
    <button class="btn" id="btn-label">${ICON.printer} QR-ETIKETT DRUCKEN</button></div>`;
  if (m.case === "NACHKALIBRIERUNG") {
    return `<div class="card ok"><h3>Fall A</h3><div class="big" style="color:var(--green)">NACHKALIBRIERUNG</div>
      <p>Solldaten aus der Datenbank: <b>${num(d.lrv, 3)} … ${num(d.urv, 3)} ${esc(d.unit)}</b>, Toleranz ± ${num(d.tolerance_pct)} %</p>${startBtns}</div>`;
  }
  if (m.case === "GERAETETAUSCH") {
    if (d) return `<div class="card ok"><h3>Fall B</h3><div class="big" style="color:var(--green)">Gerätetausch gespeichert</div>
      <p>Neues Gerät übernimmt TAG ${esc(d.tag)} und die Solldaten. Historie bleibt erhalten.</p>${startBtns}</div>`;
    const old = m.device;
    return `<div class="card warn"><h3>Fall B</h3><div class="big" style="color:var(--amber)">⚠ GERÄTETAUSCH ERKANNT</div>
      <p>TAG <b>${esc(old.tag)}</b> ist beim Kunden mit einem anderen Gerät registriert.</p>
      <div class="swap"><div><div class="muted">Alte Unique-ID</div><div class="uid old">${esc(old.hart_unique_id)}</div></div><div class="big">→</div>
      <div><div class="muted">Neue Unique-ID</div><div class="uid new">${esc(w.info.unique_id)}</div></div></div>
      <p class="muted">Der Datensatz wird überschrieben, die Historie des Altgeräts bleibt erhalten. Zwei Bestätigungen erforderlich.</p>
      <div class="btn-row">${w.swap_confirmations === 0
        ? '<button class="btn warn" id="btn-swap1">Tausch bestätigen (1/2)</button>'
        : '<button class="btn warn" id="btn-swap2">ENDGÜLTIG bestätigen (2/2)</button>'}
      <button class="btn" id="btn-reset">Abbrechen</button></div></div>`;
  }
  if (m.case === "NEUAUFNAHME") {
    if (d) return `<div class="card ok"><h3>Fall C</h3><div class="big" style="color:var(--green)">Neuaufnahme gespeichert</div>${startBtns}</div>`;
    const r = w.info.range || {};
    const safe = S.status.safe_mode;
    return `<div class="card accent"><h3>Fall C</h3><div class="big" style="color:var(--cyan)">NEUAUFNAHME</div>
      <div class="grid2" style="margin-top:10px"><label class="field">TAG<input type="text" class="kb" id="n-tag" value="${esc(w.info.tag)}"></label>
      <label class="field">Beschreibung<input type="text" class="kb" id="n-desc" value="${esc(w.info.descriptor)}"></label>
      <label class="field">0 % (unterer Messbereich)<input type="text" inputmode="decimal" class="kb num" id="n-lrv" value="${num(r.lower_range, 3)}"></label>
      <label class="field">100 % (oberer Messbereich)<input type="text" inputmode="decimal" class="kb num" id="n-urv" value="${num(r.upper_range, 3)}"></label>
      <label class="field">Einheit<select id="n-unit">${UNITS.map(([c, n]) => `<option value="${c}" ${c === r.unit_code ? "selected" : ""}>${n}</option>`).join("")}
        ${UNITS.some(([c]) => c === r.unit_code) ? "" : `<option value="${r.unit_code}" selected>${esc(r.unit)}</option>`}</select></label>
      <label class="field">Toleranz (% der Spanne)<input type="text" inputmode="decimal" class="kb num" id="n-tol" value="0,25"></label></div>
      <label class="field" style="margin-top:8px">Einbauort<input type="text" class="kb" id="n-loc"></label>
      <label class="check"><input type="checkbox" id="n-write" ${safe ? "disabled" : ""}> TAG, Beschreibung, Einheit und Messbereich ins Gerät schreiben (Cmd 18/44/35)</label>
      ${safe ? '<p class="muted" style="font-size:13px;margin:0">🔒 24/7-Safe-Mode aktiv – Schreiben ins Gerät gesperrt (nur Datenbank).</p>' : ""}
      <div class="btn-row"><button class="btn primary" id="btn-register" data-primary>Neuaufnahme speichern</button>
      <button class="btn" id="btn-reset">Abbrechen</button></div></div>`;
  }
  return "";
}

function bindCase(el) {
  const on = (id, fn) => { const b = $(id, el); if (b) b.onclick = fn; };
  on("#btn-start", (ev) => busy(ev.currentTarget, "Starte …", async () => {
    S.wf = await api("/api/calibration/start", {});
    S.selPoint = 0;
    setView("cal");
  }));
  on("#btn-label", () => labelSheet());
  on("#btn-reset", async () => { S.wf = await api("/api/workflow/reset", {}); renderDevice(); });
  on("#btn-swap1", async () => {
    if (!(await confirmDialog("Gerätetausch bestätigen (1/2)", "Wurde das Gerät an dieser Messstelle tatsächlich getauscht?", "Ja, Gerät wurde getauscht", "warn"))) return;
    S.wf = await api("/api/swap/confirm", { step: 1 }); renderDevice();
  });
  on("#btn-swap2", async () => {
    if (!(await confirmDialog("ENDGÜLTIG bestätigen (2/2)", "Der Datensatz der Messstelle wird auf das neue Gerät umgeschrieben. Die Historie des Altgeräts bleibt erhalten.", "Endgültig übernehmen", "warn"))) return;
    S.wf = await api("/api/swap/confirm", { step: 2 }); renderDevice();
  });
  on("#btn-register", (ev) => busy(ev.currentTarget, "Speichere …", async () => {
    S.wf = await api("/api/device/register", {
      tag: $("#n-tag").value, descriptor: $("#n-desc").value, lrv: $("#n-lrv").value, urv: $("#n-urv").value,
      unit_code: $("#n-unit").value, tolerance_pct: $("#n-tol").value, location: $("#n-loc").value,
      write_to_device: $("#n-write").checked });
    renderDevice();
  }));
}

async function setLoop(mode) {
  let confirmed = false;
  if (mode === "ACTIVE_24V") {
    confirmed = await confirmDialog("24-V-Schleifenspeisung einschalten?",
      "Nur für einen 2-Leiter-Transmitter OHNE andere Speisung (z.B. Werkbank). Niemals in einer vom Leitsystem gespeisten Schleife!", "24 V einschalten", "warn");
    if (!confirmed) return;
  }
  try { await api("/api/loop_mode", { mode, confirmed }); toast("Schleifenmodus umgeschaltet", "ok"); } catch (_) { /* Toast */ }
  S.status = await api("/api/status"); renderStatus(); render();
}

/* ------------------------------------------------------------------ Kalibrierung */
function renderCal() {
  const el = $("#view-cal");
  if (needOrder(el)) return;
  const w = S.wf, d = w.device;
  if (!d || (w.stage !== "calibrating" && w.stage !== "done")) {
    el.innerHTML = `<div class="card"><h3>Keine Kalibrierung aktiv</h3><p>Gerät anschließen, identifizieren und die Kalibrierung starten.</p>
      <button class="btn primary block" data-goto="device">${ICON.device} Zum Gerät</button></div>`;
    return;
  }
  const pts = w.points || {};
  const head = `<div class="card"><div class="row"><div><div class="tag">${esc(d.tag)}</div><div class="muted">${esc(d.display_name)}</div></div>
    <div style="flex:0 0 auto;text-align:right"><span class="badge info">${esc(caseLabel(w.calibration.case_type))}</span>
    ${d.is_positioner ? '<br><span class="badge info" style="margin-top:4px">Stellungsregler</span>' : ""}</div></div>
    <p class="muted" style="margin:8px 0 0">Bereich ${num(d.lrv, 3)} … ${num(d.urv, 3)} ${esc(d.unit)} · Toleranz ± ${num(d.tolerance_pct)} %</p></div>`;
  const table = Object.keys(pts).length ? `<div class="card"><h3>Messpunkte</h3><div class="tbl-wrap"><table class="data">
    <tr><th>Punkt</th><th>Soll</th><th>HART</th><th>True-mA</th><th>Abw. PV</th><th>Abw. mA</th><th>D/A</th><th></th></tr>
    ${Object.values(pts).map((p) => `<tr><td>${num(p.point_pct, 0)} %</td><td>${num(p.setpoint_value, 3)}</td><td>${num(p.hart_pv, 3)}</td>
      <td>${num(p.true_ma, 3)}</td><td class="${Math.abs(p.error_pv_pct) > d.tolerance_pct ? "neg" : ""}">${sgn(p.error_pv_pct)}</td>
      <td class="${Math.abs(p.error_ma_pct) > d.tolerance_pct ? "neg" : ""}">${sgn(p.error_ma_pct)}</td>
      <td class="${Math.abs(p.da_mismatch_pct) > 0.25 ? "warn-t" : ""}">${sgn(p.da_mismatch_pct)}</td>
      <td class="${p.passed ? "pos" : "neg"}">${p.passed ? "OK" : "FEHLER"}</td></tr>`).join("")}</table></div></div>` : "";

  if (w.stage === "done") {
    const r = w.last_result || w.calibration;
    el.innerHTML = head + `<div class="result ${r.result === "BESTANDEN" ? "ok" : "err"}">${esc(r.result)}</div>
      <p class="muted" style="text-align:center">Max. Abweichung ${num(r.max_error_pct, 3)} % · Dauer ${Math.round((r.duration_s || 0) / 60)} min</p>`
      + table + `<div class="btn-row"><button class="btn primary" id="btn-label">${ICON.printer} QR-ETIKETT DRUCKEN</button>
      <button class="btn" id="btn-next" data-primary>${ICON.device} Nächstes Gerät</button></div>`;
    $("#btn-label").onclick = () => labelSheet();
    $("#btn-next").onclick = async () => { S.wf = await api("/api/workflow/reset", {}); setView("device"); };
    return;
  }

  const cal = w.cal_points;
  if (!cal.includes(S.selPoint)) S.selPoint = cal[0];
  const p = S.selPoint;
  const target = d.lrv + (d.urv - d.lrv) * p / 100;
  const done = Object.keys(pts).length;
  el.innerHTML = head + `<div class="points">${cal.map((c) => {
      const q = pts[String(c)];
      return `<button data-pt="${c}" class="${c === p ? "sel" : ""} ${q ? (q.passed ? "ok" : "fail") : ""}">${c} %<small>${q ? (q.passed ? "OK" : "FEHLER") : "offen"}</small></button>`;
    }).join("")}</div>
    <div class="card accent"><h3>Prüfpunkt ${p} %</h3>
      <div class="row"><div><div class="muted">Sollwert</div><div class="big">${num(target, 3)} ${esc(d.unit)}</div></div>
      <div><div class="muted">Soll-Strom</div><div class="big">${num(4 + 0.16 * p, 3)} mA</div></div></div>
      ${d.is_positioner
        ? `<div class="btn-row"><button class="btn" id="btn-setpoint">Sollwert anfahren (Cmd 40) → ${num(4 + 0.16 * p, 2)} mA</button></div>
           ${w.fixed_current_active ? '<p class="muted" style="font-size:13px">Festwertmodus aktiv – wird beim Abschluss automatisch beendet.</p>' : ""}`
        : `<label class="field" style="margin-top:10px">Tatsächlich aufgegebener Referenzwert (optional, sonst Sollwert)
           <input type="text" inputmode="decimal" class="kb num" id="ref" placeholder="${num(target, 3)}" data-enter="#btn-measure"></label>`}
      <div class="btn-row"><button class="btn primary" id="btn-measure" data-primary>${ICON.check} Messpunkt übernehmen</button>
        <button class="btn" id="btn-photo">${ICON.camera} Foto</button></div></div>`
    + table + `<div class="btn-row"><button class="btn danger" id="btn-abort">Abbrechen</button>
      <button class="btn success" id="btn-finish" ${done < cal.length ? "disabled" : ""}>Kalibrierung abschließen (${done}/${cal.length})</button></div>`;
  bindKb(el);
  $$("[data-pt]", el).forEach((b) => (b.onclick = () => { S.selPoint = Number(b.dataset.pt); renderCal(); }));
  const sp = $("#btn-setpoint", el);
  if (sp) sp.onclick = (ev) => busy(ev.currentTarget, "Fahre an …", async () => {
    await api("/api/calibration/setpoint", { pct: p }); toast(`Sollwert ${p} % vorgegeben – Ventil abwarten`, "ok");
  });
  $("#btn-measure").onclick = (ev) => busy(ev.currentTarget, "Messe … warte auf stabilen Wert", async () => {
    const ref = $("#ref") ? $("#ref").value : null;
    const pt = await api("/api/calibration/measure", { pct: p, reference_value: ref });
    toast(`${p} %: ${pt.passed ? "OK" : "außerhalb Toleranz"}`, pt.passed ? "ok" : "warn");
    S.wf = await api("/api/workflow");
    const next = cal.find((c) => !(S.wf.points || {})[String(c)]);
    if (next !== undefined) S.selPoint = next;
    renderCal();
  });
  $("#btn-photo").onclick = () => openCamera("photo", p);
  $("#btn-abort").onclick = async () => {
    if (!(await confirmDialog("Kalibrierung abbrechen?", "Die bisherigen Messpunkte werden als ABGEBROCHEN gespeichert. Ein aktiver Festwertmodus wird beendet.", "Abbrechen", "danger"))) return;
    S.wf = await api("/api/calibration/abort", {}); setView("device");
  };
  $("#btn-finish").onclick = (ev) => busy(ev.currentTarget, "Speichere …", async () => {
    S.wf = await api("/api/calibration/finish", {}); renderCal();
  });
}

/* ------------------------------------------------------------------ Live-Panel */
function renderLive() {
  const el = $("#live");
  const L = S.live, msgs = (S.wf.messages || []).slice(-4).reverse();
  if (!L && !msgs.length) {
    el.classList.remove("has-data");
    el.innerHTML = '<p class="muted">Kein Gerät verbunden.</p>';
    return;
  }
  el.classList.add("has-data");
  let html = "";
  if (L && !L.error) {
    const da = L.da_mismatch_pct;
    html += `<div class="live-grid">
      <div class="live-cell"><div class="lbl">HART PV</div><div class="val">${num(L.hart_pv, 3)} <small>${esc(L.unit || "")}</small></div></div>
      <div class="live-cell"><div class="lbl">HART mA</div><div class="val">${num(L.hart_ma, 3)}</div></div>
      <div class="live-cell ${L.overrange ? "err" : L.namur === "OK" ? "" : "warn"}"><div class="lbl">True-mA · ${esc(L.namur)}</div><div class="val">${L.overrange ? "ÜBER" : num(L.true_ma, 3)}</div></div>
      <div class="live-cell ${da == null ? "" : Math.abs(da) > 0.25 ? "err" : "ok"}"><div class="lbl">Digital ↔ Analog</div><div class="val">${sgn(da)} %</div></div></div>`;
    if ((L.status_texts || []).length) html += `<div class="live-msgs">${L.status_texts.map((t) => `<div class="msg warn">${esc(t)}</div>`).join("")}</div>`;
  } else if (L && L.error) html += `<div class="msg error">${esc(L.error)}</div>`;
  if (msgs.length) html += `<div class="live-msgs">${msgs.map((m) => `<div class="msg ${esc(m.level)}">${esc(m.text)}</div>`).join("")}</div>`;
  el.innerHTML = html;
}

/* ------------------------------------------------------------------ Bus-Sniffer */
function renderSniffer() {
  const el = $("#view-sniffer");
  el.innerHTML = `<div class="card"><div class="row"><span class="ocd" id="ocd"><i></i> OCD (Träger)</span>
      <button class="btn" id="sn-pause">${S.sniffPaused ? "Fortsetzen" : "Pause"}</button><button class="btn" id="sn-clear">Leeren</button></div></div>
    <div class="sniff" id="sniff"></div>
    <p class="muted" style="font-size:12px">TX = Anfrage (Secondary Master), RX = Antwort, BLOCK = vom Safe-Mode blockiert. Hex ab Präambel.</p>`;
  $("#sn-pause").onclick = () => { S.sniffPaused = !S.sniffPaused; renderSniffer(); };
  $("#sn-clear").onclick = async () => { await api("/api/sniffer/clear", {}); S.sniff = []; renderSniffer(); };
  if (!S.sniff.length) api("/api/sniffer").then((r) => { S.sniff = r.events; drawSniff(); });
  drawSniff();
}
function sniffLine(e) {
  const t = new Date(e.t * 1000).toLocaleTimeString("de-DE") + "." + String(Math.floor((e.t % 1) * 1000)).padStart(3, "0");
  return `<div class="${esc(e.dir)}">${t} ${esc(e.dir.padEnd(5))} ${esc(e.summary)}${e.hex ? "\n      " + esc(e.hex) : ""}</div>`;
}
function drawSniff() {
  const box = $("#sniff");
  if (!box) return;
  box.innerHTML = S.sniff.slice(-300).map(sniffLine).join("");
  box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------------ Export */
async function renderExport() {
  const el = $("#view-export");
  const ex = await api("/api/export");
  const last = ex.last_export;
  el.innerHTML = `<div class="card ${ex.docked ? "accent" : ""}"><h3>Dock / USB-C</h3>
      <div class="big">${ex.docked ? "Angedockt" : "Nicht angedockt"}</div>
      <p class="muted">${ex.pc_published ? (ex.pc_connected ? "Laufwerk HART_EXPORT ist am PC eingebunden (schreibgeschützt)." : "Laufwerk HART_EXPORT wird angeboten – warte auf PC.") : "Kein Laufwerk angeboten."}</p>
      <div class="btn-row"><button class="btn primary" id="ex-pc">${ICON.usb} Als Laufwerk am PC anbieten</button>
      <button class="btn" id="ex-unpub" ${ex.pc_published ? "" : "disabled"}>Trennen</button></div></div>
    <div class="card"><h3>USB-Stick</h3>${ex.sticks.length ? ex.sticks.map((s) => `<div class="row"><div><b>${esc(s.label)}</b> <span class="muted">${esc(s.device)} · ${esc(s.size)} · ${esc(s.fstype)}</span></div>
      <button class="btn primary" data-stick="${esc(s.device)}" style="flex:0 0 auto">Exportieren</button></div>`).join("") : '<p class="muted">Kein USB-Stick erkannt.</p>'}</div>
    ${last ? `<div class="card ok"><h3>Letzter Export</h3><p>${last.target === "pc" ? "PC-Laufwerk" : "USB-Stick"} · ${last.files} Dateien · ${new Date(last.at * 1000).toLocaleString("de-DE")}</p></div>` : ""}
    <p class="muted" style="font-size:13px">Enthält Prüfberichte, Fotos, Etiketten, Datenbanken (auch für Grafana), CSV und Prüfsummen. Am PC „Auf_Desktop_kopieren.bat“ starten.</p>`;
  $("#ex-pc").onclick = (ev) => busy(ev.currentTarget, "Erstelle Export …", async () => {
    const r = await api("/api/export/pc", {}); toast(`Laufwerk HART_EXPORT bereit (${r.files} Dateien)`, "ok"); renderExport();
  });
  $("#ex-unpub").onclick = async () => { await api("/api/export/unpublish", {}); renderExport(); };
  $$("[data-stick]", el).forEach((b) => (b.onclick = (ev) => busy(ev.currentTarget, "Kopiere …", async () => {
    const r = await api("/api/export/stick", { device: b.dataset.stick });
    toast(`Export geprüft (${r.files} Dateien) – Stick kann entfernt werden`, "ok"); renderExport();
  })));
}

/* ------------------------------------------------------------------ Einstellungen */
async function renderSettings() {
  const el = $("#view-settings");
  const st = S.status;
  const fb = await api("/api/stats");
  let sim = "";
  if (window.HART.simulated) {
    const sc = await api("/api/sim/scenarios");
    sim = `<div class="card"><h3>Simulation</h3>
      <label class="field">Angeschlossenes Feldgerät<select id="sim-dev"><option value="">(keins)</option>
        ${sc.scenarios.map((n) => `<option>${esc(n)}</option>`).join("")}</select></label>
      <label class="field" style="margin-top:8px">Prozesswert Transmitter: <span id="sim-pv">50</span> %<input type="range" id="sim-proc" min="-5" max="105" value="50"></label>
      <div class="row"><label class="check"><input type="checkbox" id="sim-dock" ${st.dock ? "checked" : ""}> Angedockt</label>
      <label class="check"><input type="checkbox" id="sim-lock" ${(st.touch_block_reasons || []).some((r) => r.startsWith("Putz")) ? "checked" : ""}> Putzmodus-Schalter</label>
      <label class="check"><input type="checkbox" id="sim-kbd"> Tastatur</label><label class="check"><input type="checkbox" id="sim-mouse"> Maus</label></div>
      <div class="seg">${[0, 90, 180, 270].map((d) => `<button data-rot="${d}">${d}°</button>`).join("")}</div></div>`;
  }
  el.innerHTML = `<div class="card ${st.safe_mode ? "ok" : "err"}"><h3>24/7-Safe-Mode</h3>
      <div class="seg"><button id="safe-on" class="${st.safe_mode ? "active" : ""}">${ICON.lock} Nur Lesen</button>
      <button id="safe-off" class="${st.safe_mode ? "" : "active"}">${ICON.unlock} Schreiben erlaubt</button></div>
      <p class="muted" style="font-size:13px;margin:8px 0 0">Standardmäßig beim Start aktiv. Blockiert alle Schreibkommandos ans Feldgerät.</p></div>
    <div class="card"><h3>Rückmeldung</h3>
      <label class="check"><input type="checkbox" id="fb-hap" checked> Vibration</label>
      <label class="check"><input type="checkbox" id="fb-snd" checked> Signaltöne</label>
      <label class="check"><input type="checkbox" id="fb-touch" checked> Vibration bei jedem Tippen</label>
      <label class="field">Lautstärke<input type="range" id="fb-vol" min="0" max="100" value="80"></label></div>
    <div class="card"><h3>Eingabe & Anzeige</h3>
      <label class="check"><input type="checkbox" id="in-mouse" checked> Touch sperren, solange eine Maus angeschlossen ist</label>
      <div class="seg"><button id="rot-auto" class="${st.rotation.locked ? "" : "active"}">Auto-Drehung</button>
      <button id="rot-lock" class="${st.rotation.locked ? "active" : ""}">Drehung gesperrt</button></div></div>
    <div class="card"><h3>Uhrzeit</h3><p class="muted">Quelle: <b>${esc(st.time_source)}</b> · RTC ${esc(fb.rtc.backend)}${fb.rtc.temperature_c != null ? ` · ${num(fb.rtc.temperature_c, 1)} °C` : ""}</p>
      <div class="row"><input type="datetime-local" id="time-set"><button class="btn" id="time-btn" style="flex:0 0 auto">Uhrzeit stellen</button></div></div>
    <div class="card"><h3>Prüfmittel True-mA</h3><dl class="kv"><dt>Shunt</dt><dd>${num(fb.meter.shunt_ohm, 1)} Ω · bis ${num(fb.meter.max_measurable_ma, 2)} mA ${fb.meter.range_ok ? "" : '<span class="badge err">Messbereich zu klein</span>'}</dd>
      <dt>Kalibriert</dt><dd>${esc((fb.meter.calibration.calibrated_at || "nie").slice(0, 10))} ${fb.meter.calibration.is_due ? '<span class="badge warn">fällig</span>' : ""}</dd></dl></div>
    ${sim}
    <div class="card"><h3>Gerät</h3><p class="muted">Version ${esc(window.HART.version)} · ${num(fb.total_hours, 1)} Betriebsstunden</p>
      <button class="btn danger block" id="btn-shutdown">Herunterfahren</button></div>`;
  bindKb(el);
  $("#safe-on").onclick = () => setSafe(true);
  $("#safe-off").onclick = () => setSafe(false);
  const fbSend = () => api("/api/settings/feedback", { haptic_enabled: $("#fb-hap").checked, sound_enabled: $("#fb-snd").checked,
    touch_haptic: $("#fb-touch").checked, volume: Number($("#fb-vol").value) });
  ["#fb-hap", "#fb-snd", "#fb-touch", "#fb-vol"].forEach((id) => ($(id).onchange = fbSend));
  $("#in-mouse").onchange = (e) => api("/api/settings/block_touch_with_mouse", { enabled: e.target.checked });
  $("#rot-auto").onclick = $("#rot-lock").onclick = async (e) => {
    if ((e.currentTarget.id === "rot-lock") !== !!st.rotation.locked) await api("/api/rotation/lock", {});
    S.status = await api("/api/status"); renderStatus(); renderSettings();
  };
  $("#time-btn").onclick = async () => {
    const v = $("#time-set").value;
    if (!v) return toast("Datum und Uhrzeit wählen", "warn");
    await api("/api/time", { local: v }); toast("Uhrzeit gestellt", "ok");
  };
  $("#btn-shutdown").onclick = async () => {
    if (await confirmDialog("Herunterfahren?", "Laufende Kalibrierungen werden abgebrochen, die Schleife wird passiv geschaltet.", "Herunterfahren", "danger"))
      await api("/api/shutdown", { confirmed: true });
  };
  if (window.HART.simulated) {
    $("#sim-dev").onchange = (e) => api("/api/sim/device", { scenario: e.target.value }).then(() => toast("Simuliertes Gerät gewechselt", "ok"));
    $("#sim-proc").oninput = (e) => { $("#sim-pv").textContent = e.target.value; api("/api/sim/process", { pct: Number(e.target.value) }); };
    $("#sim-dock").onchange = (e) => api("/api/sim/dock", { docked: e.target.checked });
    $("#sim-lock").onchange = (e) => api("/api/sim/touchlock", { locked: e.target.checked });
    $("#sim-kbd").onchange = (e) => api("/api/sim/input", { name: "Sim-Tastatur", kind: "keyboard", connected: e.target.checked });
    $("#sim-mouse").onchange = (e) => api("/api/sim/input", { name: "Sim-Maus", kind: "mouse", connected: e.target.checked });
    $$("[data-rot]", el).forEach((b) => (b.onclick = () => api("/api/sim/rotate", { deg: Number(b.dataset.rot) })));
  }
}

async function setSafe(enabled) {
  if (!enabled && !(await confirmDialog("Safe-Mode deaktivieren?",
    "Schreibkommandos an Feldgeräte werden freigegeben (TAG, Messbereich, Festwertmodus/Sollwert). In 24/7-Anlagen kann das den Prozess beeinflussen!",
    "Schreiben erlauben", "danger"))) return;
  await api("/api/safe_mode", { enabled, confirmed: true });
  S.status = await api("/api/status"); renderStatus(); render();
}

/* ------------------------------------------------------------------ Overlays */
function openSheet(html, onClose) {
  $(".sheet-body").innerHTML = html;
  $("#overlay").classList.remove("hidden");
  S.overlayOnClose = onClose || null;
  bindKb($(".sheet-body"));
}
function closeSheet() {
  if ($("#overlay").classList.contains("hidden")) return;
  $("#overlay").classList.add("hidden");
  const cb = S.overlayOnClose;
  S.overlayOnClose = null;
  $(".sheet-body").innerHTML = "";
  hideOsk();
  if (cb) cb();
}
function confirmDialog(title, text, okLabel = "OK", cls = "primary") {
  return new Promise((resolve) => {
    let answered = false;
    openSheet(`<h2>${esc(title)}</h2><p>${esc(text)}</p><div class="btn-row">
      <button class="btn" id="cf-no">Abbrechen</button><button class="btn ${cls}" id="cf-yes" data-primary>${esc(okLabel)}</button></div>`,
      () => { if (!answered) resolve(false); });
    $("#cf-no").onclick = () => closeSheet();
    $("#cf-yes").onclick = () => { answered = true; closeSheet(); resolve(true); };
  });
}

async function batterySheet() {
  const b = await api("/api/battery");
  if (!b.cells) return;
  const vmin = Math.min(...b.cells_v), vmax = Math.max(...b.cells_v);
  const scale = (v) => Math.max(5, Math.min(100, ((v - 2.8) / (3.65 - 2.8)) * 100));
  openSheet(`<h2>Akku 8S LiFePO4</h2>
    <div class="row"><div><div class="muted">Ladezustand</div><div class="big">${num(b.soc_percent, 1)} %</div></div>
      <div><div class="muted">Spannung</div><div class="big">${num(b.pack_voltage_v, 2)} V</div></div>
      <div><div class="muted">Strom</div><div class="big">${sgn(b.current_a, 2)} A</div></div>
      <div><div class="muted">${b.charging ? "bis voll" : "Restlaufzeit"}</div><div class="big">${b.minutes_remaining ? Math.round(b.minutes_remaining) + " min" : "–"}</div></div></div>
    <h3 style="margin-top:14px">Zellen · Drift ${num(b.cell_drift_mv, 1)} mV</h3>
    <div class="cells">${b.cells.map((c, i) => `<div class="cell ${b.cells_v[i] === vmax ? "max" : ""} ${b.cells_v[i] === vmin ? "min" : ""} ${c.balancing ? "bal" : ""}">
      <div class="bar" style="height:${scale(c.v)}%"></div><span>${esc(c.name)}</span><b>${num(c.v, 3)} V</b><span>+${num(c.delta_mv, 1)} mV</span></div>`).join("")}</div>
    <dl class="kv" style="margin-top:12px"><dt>Aktiv-Balancer</dt><dd>${esc(b.active_balancing)}</dd>
      <dt>Temperatur</dt><dd>${b.temperatures_c.map((t) => (t == null ? "–" : num(t, 1) + " °C")).join(" / ")}</dd>
      <dt>FETs</dt><dd>Laden ${b.chg_fet ? "EIN" : "AUS"} · Entladen ${b.dsg_fet ? "EIN" : "AUS"}</dd>
      <dt>Zyklen</dt><dd>${num(b.cycles, 1)}</dd></dl>
    ${b.faults.map((f) => `<div class="msg error">${esc(f)}</div>`).join("")}${b.warnings.map((f) => `<div class="msg warn">${esc(f)}</div>`).join("")}`);
}

async function statsSheet() {
  const s = await api("/api/stats");
  openSheet(`<h2>Betriebsstatistik</h2>
    <div class="row"><div><div class="muted">Gesamt</div><div class="big">${num(s.total_hours, 1)} h</div></div>
      <div><div class="muted">Feld</div><div class="big">${num(s.field_hours, 1)} h</div></div>
      <div><div class="muted">Dock</div><div class="big">${num(s.dock_hours, 1)} h</div></div>
      <div><div class="muted">HART aktiv</div><div class="big">${num(s.hart_hours, 2)} h</div></div></div>
    <dl class="kv" style="margin-top:12px"><dt>Starts</dt><dd>${s.boot_count}</dd><dt>Kalibrierungen</dt><dd>${s.calibrations_total} (${s.calibrations_passed} bestanden, Ø ${num(s.avg_calibration_min, 1)} min)</dd>
      <dt>Gerätetausche</dt><dd>${s.device_swaps_total}</dd><dt>Neuaufnahmen</dt><dd>${s.new_devices_total}</dd><dt>Diese Sitzung</dt><dd>${num(s.session_minutes, 0)} min</dd></dl>
    <h3 style="margin-top:14px">Letzte Ereignisse</h3><div class="tbl-wrap"><table class="data">
    ${s.events.slice(0, 15).map((e) => `<tr><td>${new Date(e.timestamp_unix * 1000).toLocaleString("de-DE")}</td><td>${esc(e.event_type)}</td><td style="text-align:left;white-space:normal">${esc(e.message)}</td></tr>`).join("")}</table></div>`);
}

function openCamera(mode, pct) {
  const photo = mode === "photo";
  openSheet(`<h2>${photo ? "Beweisfoto" : "QR-Code scannen"}</h2>
    <div class="camera-view"><img id="cam-img" src="/camera/stream?t=${Date.now()}" alt="Kamera">${photo ? "" : '<div class="aim"></div>'}</div>
    <label class="field" style="margin-top:10px">Ringlicht (gegen Reflexe auf Metall-Typenschildern)<input type="range" id="cam-light" min="5" max="100" value="60"></label>
    <div class="btn-row">${photo ? `<button class="btn primary" id="cam-shot" data-primary>${ICON.camera} Foto aufnehmen</button>` : '<p class="muted">Typenschild/Prüfplakette in den Rahmen halten …</p>'}</div>`,
    async () => { const img = $("#cam-img"); if (img) img.src = ""; if (!photo) await api("/api/camera/scan", { active: false }).catch(() => {}); });
  if (!photo) api("/api/camera/scan", { active: true });
  $("#cam-light").onchange = (e) => api("/api/camera/light", { percent: Number(e.target.value) });
  const shot = $("#cam-shot");
  if (shot) shot.onclick = (ev) => busy(ev.currentTarget, "Speichere …", async () => {
    await api("/api/calibration/photo", { pct }); toast("Beweisfoto gespeichert", "ok"); closeSheet();
  });
}

function labelSheet() {
  openSheet(`<h2>Prüfplakette 40 × 30 mm</h2>
    <div class="label-preview"><img src="/api/label/preview.png?t=${Date.now()}" alt="Etikettenvorschau"></div>
    <p class="muted">Drucker: ${esc((S.status.printer || {}).text || "–")}</p>
    <div class="btn-row"><button class="btn primary" id="lbl-print" data-primary>${ICON.printer} QR-ETIKETT DRUCKEN</button></div>`);
  $("#lbl-print").onclick = (ev) => busy(ev.currentTarget, "Drucke …", async () => {
    const r = await api("/api/label/print", { copies: 1 });
    toast(r.ok ? (r.backend === "file" ? "Etikett gespeichert (Simulation)" : "Etikett gedruckt") : `Druckfehler: ${r.error}`, r.ok ? "ok" : "error");
    if (r.ok) closeSheet();
  });
}

/* ------------------------------------------------------------------ On-Screen-Tastatur */
const OSK_TEXT = ["1234567890ß", "qwertzuiopü", "asdfghjklöä", "⇧yxcvbnm-⌫"];
const OSK_NUM = ["789", "456", "123", "-0,⌫"];
let oskTarget = null, oskShift = true;
function bindKb(root) {
  $$("input.kb", root).forEach((inp) => {
    inp.addEventListener("focus", () => { if (S.oskEnabled) showOsk(inp); });
    // Fokus verlässt das Feld (nicht zur Bildschirmtastatur) -> Tastatur schließen
    inp.addEventListener("blur", () => setTimeout(() => {
      const a = document.activeElement;
      if (!a || !a.classList || !a.classList.contains("kb")) hideOsk();
    }, 120));
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && inp.dataset.enter) { e.preventDefault(); const b = $(inp.dataset.enter); if (b) b.click(); }
    });
  });
}
function showOsk(inp) {
  oskTarget = inp;
  const numeric = inp.classList.contains("num");
  const rows = numeric ? OSK_NUM : OSK_TEXT;
  const k = (c) => {
    const upper = (ch) => (ch === "ß" ? ch : ch.toUpperCase());       // "ß".toUpperCase() wäre "SS"
    const label = c === "⇧" ? "⇧" : c === "⌫" ? "⌫" : oskShift && !numeric ? upper(c) : c;
    return `<button data-k="${esc(c)}" class="${c === "⇧" || c === "⌫" ? "wide" : ""}">${esc(label)}</button>`;
  };
  $("#osk").innerHTML = rows.map((r) => `<div class="osk-row">${[...r].map(k).join("")}</div>`).join("")
    + `<div class="osk-row">${numeric ? "" : '<button data-k="." >.</button><button data-k=" " class="space">Leertaste</button><button data-k="/">/</button>'}
       <button data-k="close" class="wide">Fertig</button><button data-k="enter" class="wide accent">⏎</button></div>`;
  $("#osk").classList.remove("hidden");
  // Inhalt oberhalb der Tastatur scrollbar halten
  document.body.style.setProperty("--osk-h", `${$("#osk").offsetHeight}px`);
  document.body.classList.add("osk-open");
  setTimeout(() => inp.scrollIntoView({ block: "center", behavior: "smooth" }), 50);
}
function hideOsk() { $("#osk").classList.add("hidden"); document.body.classList.remove("osk-open"); oskTarget = null; }
$("#osk").addEventListener("mousedown", (e) => e.preventDefault());           // Fokus im Eingabefeld halten
$("#osk").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b || !oskTarget) return;
  const k = b.dataset.k, inp = oskTarget;
  if (k === "close") return hideOsk();
  if (k === "enter") { const t = inp.dataset.enter ? $(inp.dataset.enter) : null; hideOsk(); inp.blur(); if (t) t.click(); return; }
  if (k === "⇧") { oskShift = !oskShift; return showOsk(inp); }
  const s = inp.selectionStart ?? inp.value.length, en = inp.selectionEnd ?? inp.value.length;
  if (k === "⌫") inp.setRangeText("", Math.max(0, s - (s === en ? 1 : 0)), en, "end");
  else inp.setRangeText(oskShift && !inp.classList.contains("num") && k !== "ß" ? k.toUpperCase() : k, s, en, "end");
  inp.dispatchEvent(new Event("input", { bubbles: true }));
  if (oskShift && k !== "⌫" && inp.id !== "o-no") { oskShift = false; showOsk(inp); }
});

/* ------------------------------------------------------------------ Touch-Sperre */
let lastTouch = 0;
["touchstart", "touchmove", "touchend"].forEach((t) => document.addEventListener(t, (e) => {
  if (!S.touchBlocked) return;
  lastTouch = Date.now();
  if (e.cancelable) e.preventDefault();
  e.stopPropagation();
}, { capture: true, passive: false }));
["pointerdown", "pointerup", "mousedown", "mouseup", "click"].forEach((t) => document.addEventListener(t, (e) => {
  if (!S.touchBlocked) return;
  if (e.pointerType === "touch" || Date.now() - lastTouch < 800) { e.preventDefault(); e.stopPropagation(); }
}, true));

/* ------------------------------------------------------------------ Tastatursteuerung */
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!$("#osk").classList.contains("hidden")) return hideOsk();
    if (!$("#overlay").classList.contains("hidden")) return closeSheet();
    if (document.activeElement) document.activeElement.blur();
  }
  if (e.altKey && /^[1-6]$/.test(e.key)) {
    e.preventDefault();
    setView(["order", "device", "cal", "sniffer", "export", "settings"][Number(e.key) - 1]);
  }
  if (e.key === "Enter" && !["INPUT", "SELECT", "TEXTAREA", "BUTTON", "A"].includes(document.activeElement.tagName)) {
    const scope = $("#overlay").classList.contains("hidden") ? $(`#view-${S.view}`) : $(".sheet-body");
    const b = scope && $("[data-primary]:not([disabled])", scope);
    if (b) { e.preventDefault(); b.click(); }
  }
});

/* ------------------------------------------------------------------ Globale Klicks */
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) { if (g.hasAttribute("data-close")) closeSheet(); setView(g.dataset.goto); return; }
  const v = e.target.closest("#nav [data-view], #sb-order, #sb-dock");
  if (v) return setView(v.dataset.view);
  if (e.target.closest("[data-close]") || e.target.id === "overlay") return closeSheet();
});
$("#sb-bat").onclick = batterySheet;
$("#sb-hours").onclick = statsSheet;
$("#sb-safe").onclick = () => setSafe(!S.status.safe_mode);
$("#sb-torch").onclick = async () => { await api("/api/torch", {}); S.status = await api("/api/status"); renderStatus(); };
$("#sb-rot").onclick = async () => { await api("/api/rotation/lock", {}); S.status = await api("/api/status"); renderStatus(); };
$("#sb-printer").onclick = () => toast(`Drucker: ${(S.status.printer || {}).text || "unbekannt"}`);
$$("#nav .ico").forEach((i) => (i.innerHTML = ICON[i.dataset.icon]));

/* ------------------------------------------------------------------ Live-Ereignisse (SSE) */
function connectEvents() {
  const es = new EventSource("/api/events");
  const on = (name, fn) => es.addEventListener(name, (e) => fn(JSON.parse(e.data)));
  on("status", (d) => {
    const orderChanged = (S.status.order || {}).id !== (d.order || {}).id;
    S.status = d; renderStatus();
    if (orderChanged && ["order", "device", "cal"].includes(S.view)) render();
  });
  on("workflow", (d) => {
    S.wf = d;
    if (d.stage === "idle" || d.stage === "done") S.live = null;      // keine veralteten Messwerte
    if (["device", "cal"].includes(S.view)) render(); else renderLive();
  });
  on("live", (d) => { S.live = d; renderLive(); });
  on("sniffer", (d) => {
    S.sniff.push(d); if (S.sniff.length > 600) S.sniff.splice(0, 200);
    const o = $("#ocd"); if (o) o.classList.toggle("on", d.dir === "OCD" ? d.ocd : o.classList.contains("on"));
    if (S.view === "sniffer" && !S.sniffPaused) { const box = $("#sniff"); if (box) { box.insertAdjacentHTML("beforeend", sniffLine(d)); box.scrollTop = box.scrollHeight; } }
  });
  on("qr", (d) => {
    if (!d.is_plaque) return toast(`QR-Code: ${d.text.slice(0, 60)}`, "warn");
    toast(`Plakette erkannt: ${d.identity.tag}`, "ok");
    closeSheet(); setView("device");
  });
  on("toast", (d) => toast(d.text, d.level));
  on("input", (d) => { Object.assign(S.status, d); renderStatus(); });
  on("export", (d) => { if (d.event === "published") toast("Laufwerk HART_EXPORT bereit", "ok"); if (S.view === "export") renderExport(); });
  es.onerror = () => { $("#banner").className = "banner warn"; $("#banner").textContent = "Verbindung zum Gerätedienst unterbrochen – verbinde neu …"; };
  es.onopen = () => renderStatus();
}

(async function init() {
  S.status = await api("/api/status");
  S.wf = await api("/api/workflow");
  renderStatus();
  setView(S.status.order ? (S.wf.stage === "calibrating" ? "cal" : "device") : "order");
  connectEvents();
})();
