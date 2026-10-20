/* Land Map front end: boundary, saved pins, live GPS, pin-here, offline tiles. */
(function () {
  "use strict";

  const KEY_STORAGE = "landmap.accessKey";
  const QUEUE_STORAGE = "landmap.pendingPins";
  const FIX_WINDOW_MS = 6000;      // how long "Pin here" listens for GPS readings
  const GOOD_ENOUGH_M = 5;         // stop early once a reading is this accurate
  const OFFLINE_ZOOMS = [14, 15, 16, 17, 18];
  const OFFLINE_MAX_TILES = 600;

  const $ = (id) => document.getElementById(id);
  const statusEl = $("status");
  let statusTimer = null;

  function showStatus(text, sticky) {
    statusEl.textContent = text;
    statusEl.hidden = false;
    clearTimeout(statusTimer);
    if (!sticky) statusTimer = setTimeout(() => { statusEl.hidden = true; }, 3500);
  }

  // ---- API with shared access key ------------------------------------------
  function getKey() { try { return localStorage.getItem(KEY_STORAGE) || ""; } catch (e) { return ""; } }
  function setKey(k) { try { localStorage.setItem(KEY_STORAGE, k); } catch (e) { /* private mode */ } }

  async function api(path, opts, retried) {
    opts = opts || {};
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    const key = getKey();
    if (key) headers["X-Access-Key"] = key;
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    if (res.status === 401 && !retried) {
      const entered = window.prompt("Enter the Land Map access key");
      if (entered === null) throw new Error("access key required");
      setKey(entered.trim());
      return api(path, opts, true);
    }
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.status === 204 ? null : res.json();
  }

  // ---- Map -----------------------------------------------------------------
  const imagery = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Imagery &copy; Esri" });
  const streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" });

  const map = L.map("map", { layers: [imagery], zoomControl: true, attributionControl: true });
  L.control.layers({ "Satellite": imagery, "Streets": streets }, null, { position: "topright" }).addTo(map);
  L.control.scale({ imperial: true, metric: true }).addTo(map);

  let boundaryBounds = null;
  const pinLayer = L.layerGroup().addTo(map);
  const markers = new Map(); // pin id -> marker

  function pinIcon(label, pending) {
    return L.divIcon({ className: "pin-label" + (pending ? " pending" : ""), html: escapeHtml(label), iconAnchor: [0, 0] });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function fmtAccuracy(m) { return m == null ? "" : `±${Math.round(m)} m`; }

  function renderPin(pin, pending) {
    let marker = markers.get(pin.id);
    const pos = [pin.lat, pin.lng];
    if (!marker) {
      marker = L.circleMarker(pos, { radius: 7, color: "#e0a82e", fillColor: "#e0a82e", fillOpacity: 0.9, weight: 2 }).addTo(pinLayer);
      marker.labelMarker = L.marker(pos, { icon: pinIcon(pin.label, pending), interactive: false }).addTo(pinLayer);
      markers.set(pin.id, marker);
    } else {
      marker.setLatLng(pos);
      marker.labelMarker.setLatLng(pos).setIcon(pinIcon(pin.label, pending));
    }
    marker.pin = pin;
    marker.bindPopup(() => popupHtml(pin, pending));
    marker.off("popupopen").on("popupopen", (e) => wirePopup(e.popup, pin));
    return marker;
  }

  function popupHtml(pin, pending) {
    const when = pin.created_at ? new Date(pin.created_at).toLocaleString() : "";
    return `<strong>${escapeHtml(pin.label)}</strong>${pending ? " <em>(not yet saved)</em>" : ""}<br>` +
      `<span class="muted">${pin.lat.toFixed(6)}, ${pin.lng.toFixed(6)} ${fmtAccuracy(pin.accuracy)}<br>${when}</span>` +
      (pin.note ? `<p>${escapeHtml(pin.note)}</p>` : "") +
      (pending ? "" : `<div class="popup-actions"><button data-act="edit">Edit</button><button data-act="delete" class="danger">Delete</button></div>`);
  }

  function wirePopup(popup, pin) {
    const el = popup.getElement();
    if (!el) return;
    el.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (btn.dataset.act === "delete") {
          if (!window.confirm(`Delete "${pin.label}"?`)) return;
          try {
            await api(`/api/pins/${pin.id}`, { method: "DELETE" });
            removePin(pin.id);
            showStatus("Deleted");
          } catch (err) { showStatus("Delete failed: " + err.message); }
        } else {
          map.closePopup();
          openSheet({ title: "Edit pin", label: pin.label, note: pin.note || "", fix: "" }, async (values) => {
            const updated = await api(`/api/pins/${pin.id}`, { method: "PATCH", body: JSON.stringify(values) });
            renderPin(updated, false);
            showStatus("Saved");
          });
        }
      });
    });
  }

  function revealPin(pin) {
    const pos = L.latLng(pin.lat, pin.lng);
    if (!map.getBounds().contains(pos)) map.setView(pos, Math.max(map.getZoom(), 17));
  }

  function removePin(id) {
    const marker = markers.get(id);
    if (!marker) return;
    pinLayer.removeLayer(marker);
    pinLayer.removeLayer(marker.labelMarker);
    markers.delete(id);
  }

  async function loadBoundary() {
    const data = await api("/api/boundary");
    const layer = L.geoJSON(data.boundary, { style: { color: "#fbc02d", weight: 3, fillColor: "#ffffff", fillOpacity: 0.08 } }).addTo(map);
    boundaryBounds = layer.getBounds();
    if (boundaryBounds.isValid()) map.fitBounds(boundaryBounds.pad(0.15));
    else map.setView([0, 0], 2);
  }

  async function loadPins() {
    const pins = await api("/api/pins");
    pins.forEach((t) => renderPin(t, false));
    readQueue().forEach((t) => renderPin(t, true));
  }

  // ---- Offline write queue ---------------------------------------------------
  function readQueue() { try { return JSON.parse(localStorage.getItem(QUEUE_STORAGE) || "[]"); } catch (e) { return []; } }
  function writeQueue(q) { try { localStorage.setItem(QUEUE_STORAGE, JSON.stringify(q)); } catch (e) { /* ignore */ } }

  async function savePin(values) {
    try {
      const saved = await api("/api/pins", { method: "POST", body: JSON.stringify(values) });
      renderPin(saved, false);
      revealPin(saved);
      showStatus(`Saved "${saved.label}"`);
    } catch (err) {
      const pending = Object.assign({ id: "pending-" + Date.now(), created_at: new Date().toISOString() }, values);
      writeQueue(readQueue().concat([pending]));
      renderPin(pending, true);
      revealPin(pending);
      showStatus("Offline: pin queued, will sync when back online");
    }
  }

  async function flushQueue() {
    const queue = readQueue();
    if (!queue.length) return;
    const remaining = [];
    for (const pending of queue) {
      try {
        const { id, created_at, ...values } = pending;
        const saved = await api("/api/pins", { method: "POST", body: JSON.stringify(values) });
        removePin(id);
        renderPin(saved, false);
      } catch (err) { remaining.push(pending); }
    }
    writeQueue(remaining);
    if (remaining.length < queue.length) showStatus(`Synced ${queue.length - remaining.length} queued pin(s)`);
  }
  window.addEventListener("online", flushQueue);

  // ---- Live position ---------------------------------------------------------
  let watchId = null;
  let hereMarker = null, hereCircle = null, follow = false;
  let lastFix = null;

  function updateHere(pos) {
    const ll = [pos.coords.latitude, pos.coords.longitude];
    lastFix = pos;
    if (!hereMarker) {
      hereMarker = L.circleMarker(ll, { radius: 8, color: "#fff", weight: 2, fillColor: "#1e88e5", fillOpacity: 1, interactive: false }).addTo(map);
      hereCircle = L.circle(ll, { radius: pos.coords.accuracy || 0, color: "#1e88e5", weight: 1, fillOpacity: 0.12, interactive: false }).addTo(map);
    } else {
      hereMarker.setLatLng(ll);
      hereCircle.setLatLng(ll).setRadius(pos.coords.accuracy || 0);
    }
    if (follow) map.panTo(ll);
  }

  function startWatch() {
    if (!navigator.geolocation) { showStatus("No GPS available in this browser"); return; }
    if (watchId !== null) return;
    watchId = navigator.geolocation.watchPosition(updateHere,
      (err) => showStatus("GPS: " + err.message),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 });
  }

  $("btn-locate").addEventListener("click", () => {
    follow = !follow;
    $("btn-locate").classList.toggle("active", follow);
    startWatch();
    if (follow && lastFix) map.setView([lastFix.coords.latitude, lastFix.coords.longitude], Math.max(map.getZoom(), 17));
    showStatus(follow ? "Following your position" : "Stopped following");
  });
  map.on("dragstart", () => { if (follow) { follow = false; $("btn-locate").classList.remove("active"); } });

  // ---- Pin here --------------------------------------------------------------
  function bestFix() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error("No GPS available"));
      let best = null;
      const id = navigator.geolocation.watchPosition((pos) => {
        updateHere(pos);
        if (!best || pos.coords.accuracy < best.coords.accuracy) best = pos;
        showStatus(`Getting GPS fix… ${fmtAccuracy(best.coords.accuracy)}`, true);
        if (best.coords.accuracy <= GOOD_ENOUGH_M) finish();
      }, (err) => { if (!best) { cleanup(); reject(err); } },
        { enableHighAccuracy: true, maximumAge: 0, timeout: FIX_WINDOW_MS });
      const timer = setTimeout(finish, FIX_WINDOW_MS);
      function cleanup() { clearTimeout(timer); navigator.geolocation.clearWatch(id); }
      function finish() { cleanup(); best ? resolve(best) : reject(new Error("No GPS fix yet, try again in the open")); }
    });
  }

  $("btn-pin").addEventListener("click", async () => {
    const btn = $("btn-pin");
    btn.disabled = true;
    try {
      const fix = await bestFix();
      statusEl.hidden = true;
      const c = fix.coords;
      openSheet({ title: "New pin", label: "", note: "", fix: `${c.latitude.toFixed(6)}, ${c.longitude.toFixed(6)} ${fmtAccuracy(c.accuracy)}` },
        (values) => savePin({ label: values.label, note: values.note, lat: c.latitude, lng: c.longitude, accuracy: c.accuracy }));
    } catch (err) {
      showStatus("GPS: " + err.message);
    } finally { btn.disabled = false; }
  });

  // Long-press / right-click on the map pins an arbitrary spot (planning from the couch).
  map.on("contextmenu", (e) => {
    openSheet({ title: "New pin at this spot", label: "", note: "", fix: `${e.latlng.lat.toFixed(6)}, ${e.latlng.lng.toFixed(6)}` },
      (values) => savePin({ label: values.label, note: values.note, lat: e.latlng.lat, lng: e.latlng.lng, accuracy: null }));
  });

  // ---- Bottom sheet ----------------------------------------------------------
  let sheetSubmit = null;
  function openSheet(fields, onSubmit) {
    $("sheet-title").textContent = fields.title;
    $("sheet-fix").textContent = fields.fix;
    $("pin-label").value = fields.label;
    $("pin-note").value = fields.note;
    sheetSubmit = onSubmit;
    $("sheet").hidden = false;
    setTimeout(() => $("pin-label").focus(), 50);
  }
  function closeSheet() { $("sheet").hidden = true; sheetSubmit = null; }
  $("pin-cancel").addEventListener("click", closeSheet);
  $("pin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const values = { label: $("pin-label").value.trim(), note: $("pin-note").value.trim() };
    if (!values.label) return;
    const fn = sheetSubmit;
    closeSheet();
    try { await fn(values); } catch (err) { showStatus("Save failed: " + err.message); }
  });

  // ---- Offline tiles ---------------------------------------------------------
  function tileRange(bounds, z) {
    const toTile = (lat, lng) => {
      const n = Math.pow(2, z);
      const x = Math.floor((lng + 180) / 360 * n);
      const latR = lat * Math.PI / 180;
      const y = Math.floor((1 - Math.log(Math.tan(latR) + 1 / Math.cos(latR)) / Math.PI) / 2 * n);
      return [x, y];
    };
    const [x1, y1] = toTile(bounds.getNorth(), bounds.getWest());
    const [x2, y2] = toTile(bounds.getSouth(), bounds.getEast());
    const urls = [];
    for (let x = x1; x <= x2; x++) for (let y = y1; y <= y2; y++) {
      urls.push(`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`);
    }
    return urls;
  }

  $("btn-offline").addEventListener("click", async () => {
    if (!("caches" in window)) { showStatus("Offline caching not supported here"); return; }
    const area = (boundaryBounds && boundaryBounds.isValid() ? boundaryBounds : map.getBounds()).pad(0.5);
    let urls = [];
    OFFLINE_ZOOMS.forEach((z) => { urls = urls.concat(tileRange(area, z)); });
    if (urls.length > OFFLINE_MAX_TILES) { showStatus(`Area too large (${urls.length} tiles); zoom in first`); return; }
    const cache = await caches.open("landmap-tiles");
    let done = 0, failed = 0;
    showStatus(`Saving tiles 0/${urls.length}`, true);
    for (const url of urls) {
      try {
        if (!(await cache.match(url))) {
          const res = await fetch(url, { mode: "cors" });
          if (res.ok) await cache.put(url, res); else failed++;
        }
      } catch (e) { failed++; }
      done++;
      if (done % 10 === 0) showStatus(`Saving tiles ${done}/${urls.length}`, true);
    }
    showStatus(`Offline map ready: ${urls.length - failed} tiles saved${failed ? `, ${failed} failed` : ""}`);
  });

  // ---- Boot ------------------------------------------------------------------
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/static/sw.js", { scope: "/" }).catch(() => {});

  (async () => {
    try {
      await loadBoundary();
      await loadPins();
      flushQueue();
    } catch (err) {
      showStatus("Could not load map data: " + err.message, true);
      map.setView([0, 0], 2);
    }
  })();
})();
