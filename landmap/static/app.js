/* Land Map front end: boundary, saved pins, live GPS, pin-here, offline tiles. */
(function () {
  "use strict";

  const KEY_STORAGE = "landmap.accessKey";
  const QUEUE_STORAGE = "landmap.pendingPins";
  const FIX_WINDOW_MS = 6000;      // how long "Pin here" listens for GPS readings
  const GOOD_ENOUGH_M = 5;         // stop early once a reading is this accurate
  const OFFLINE_ZOOMS = [14, 15, 16, 17, 18];
  const MIN_ZOOM = 10;             // regional perspective; no further
  const READABLE_ZOOM = 14;        // below this the property is a speck and Home lights up
  const REGION_LAT = 0.2;          // about 14 miles north and south of the property
  const REGION_LNG = 0.25;         // about 14 miles east and west
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

  function clearKey() { try { localStorage.removeItem(KEY_STORAGE); } catch (e) { /* ignore */ } }

  // A key in the link (shared once, saved to the home screen) is stored and removed from the address bar.
  (function adoptKeyFromLink() {
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("key");
    if (linked) {
      setKey(linked.trim());
      params.delete("key");
      const rest = params.toString();
      history.replaceState(null, "", window.location.pathname + (rest ? "?" + rest : "") + window.location.hash);
    }
  })();

  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    const key = getKey();
    if (key) headers["X-Access-Key"] = key;
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    if (res.status === 401) {
      setSignedIn(false);
      throw new Error("signed out");
    }
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.status === 204 ? null : res.json();
  }

  // ---- Session (signed in = holds a key the server accepts) -----------------
  let signedIn = false;
  function setSignedIn(value) {
    signedIn = value;
    $("btn-pin").hidden = !value;
    $("menu-signin").hidden = value;
    $("menu-signout").hidden = !value;
    if (!value) { pinLayer.clearLayers(); markers.clear(); }
  }

  async function checkSession() {
    if (!getKey()) { setSignedIn(false); return false; }
    try { await api("/api/session"); setSignedIn(true); return true; }
    catch (e) { return false; }
  }

  // ---- Map -----------------------------------------------------------------
  const imagery = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Imagery &copy; Esri" });
  const streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" });

  const map = L.map("map", { layers: [imagery], zoomControl: false, attributionControl: true, maxBoundsViscosity: 1.0 });
  L.control.scale({ imperial: true, metric: true }).addTo(map);
  let streetsOn = false;

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

  // ---- Property layers ----------------------------------------------------------
  const LAYER_STORAGE = "landmap.layers";
  const layerGroups = new Map();   // layer id -> L.LayerGroup
  let propertyBounds = null;
  let legalOn = true;

  function readLayerChoices() { try { return JSON.parse(localStorage.getItem(LAYER_STORAGE) || "{}"); } catch (e) { return {}; } }
  function writeLayerChoice(id, on) { const c = readLayerChoices(); c[id] = on; try { localStorage.setItem(LAYER_STORAGE, JSON.stringify(c)); } catch (e) { /* ignore */ } }

  function labelIcon(props) {
    const text = (legalOn && props.legalText) ? props.legalText : props.text;
    const size = { "x-large": "20px", large: "16px", medium: "14px", "12pt": "16px", small: "12px" }[props.size] || "16px";
    return L.divIcon({ className: "map-label", html: `<div style="color:${props.color || "#fff"};font-size:${size}">${text}</div>`, iconSize: null });
  }

  function featureStyle(p) {
    return { color: p.color || "#fff", weight: p.weight == null ? 2 : p.weight, opacity: p.opacity == null ? 0.8 : p.opacity,
             fillColor: p.fill || p.color || "#fff", fillOpacity: p.fillOpacity == null ? 0 : p.fillOpacity,
             dashArray: p.dash || null, interactive: false };
  }

  function buildLayer(layer) {
    const group = L.layerGroup();
    layer.features.features.forEach((f) => {
      const p = f.properties || {};
      if (p.kind === "image") {
        const b = p.bounds;
        group.addLayer(L.imageOverlay(`/overlays/${p.image.replace(/^overlays\//, "")}`, [[b.south, b.west], [b.north, b.east]], { opacity: p.opacity, interactive: false }));
      } else if (p.kind === "label") {
        const m = L.marker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { icon: labelIcon(p), interactive: false });
        m.labelProps = p;
        group.addLayer(m);
      } else if (f.geometry) {
        group.addLayer(L.geoJSON(f, { style: () => featureStyle(p), pointToLayer: (_, ll) => L.circleMarker(ll, { radius: 5, ...featureStyle(p), fillOpacity: 0.9 }) }));
      }
    });
    return group;
  }

  function setLayer(id, on) {
    const group = layerGroups.get(id);
    if (!group) return;
    if (on) group.addTo(map); else map.removeLayer(group);
    if (id === "legal") {
      legalOn = on;
      layerGroups.forEach((g) => g.eachLayer((l) => { if (l.labelProps) l.setIcon(labelIcon(l.labelProps)); }));
    }
  }

  function renderLayerMenu(layers) {
    const list = $("menu-layers");
    list.innerHTML = "";
    const choices = readLayerChoices();
    layers.forEach((layer) => {
      const on = layer.id in choices ? choices[layer.id] : layer.default;
      const row = document.createElement("label");
      row.className = "layer-row";
      const box = document.createElement("input");
      box.type = "checkbox"; box.checked = on;
      box.addEventListener("change", () => { setLayer(layer.id, box.checked); writeLayerChoice(layer.id, box.checked); });
      row.appendChild(box);
      row.appendChild(document.createTextNode(" " + layer.name));
      list.appendChild(row);
      if (layer.id === "legal") legalOn = on;
    });
  }

  async function loadProperty() {
    const doc = await api("/api/property");
    propertyDoc = doc;
    document.title = doc.name;
    if (doc.example) showStatus("Showing the example property: no definition in the data directory yet.", true);
    renderLayerMenu(doc.layers);
    const choices = readLayerChoices();
    const all = [];
    doc.layers.forEach((layer) => {
      const group = buildLayer(layer);
      layerGroups.set(layer.id, group);
      layer.features.features.forEach((f) => {
        if (!f.geometry) return;
        const c = f.geometry.coordinates;
        const pts = f.geometry.type === "Point" ? [c] : f.geometry.type === "Polygon" ? c[0] : c;
        pts.forEach(([lng, lat]) => all.push([lat, lng]));
      });
    });
    doc.layers.forEach((layer) => setLayer(layer.id, layer.id in choices ? choices[layer.id] : layer.default));
    propertyBounds = all.length ? L.latLngBounds(all) : null;
    if (propertyBounds) {
      // The map is about this property: you can pull back for perspective on the
      // region, but not leave it, and Home lights up whenever the property is out
      // of view or too small to read.
      const c = propertyBounds.getCenter();
      map.setMaxBounds(L.latLngBounds([c.lat - REGION_LAT, c.lng - REGION_LNG], [c.lat + REGION_LAT, c.lng + REGION_LNG]));
      map.setMinZoom(MIN_ZOOM);
      map.on("moveend zoomend", updateHomeState);
    }
    goHome(doc);
  }

  function updateHomeState() {
    if (!propertyBounds) return;
    const away = !map.getBounds().intersects(propertyBounds) || map.getZoom() < READABLE_ZOOM;
    $("btn-home").classList.toggle("away", away);
  }

  function goHome(doc) {
    if (doc && doc.center) map.setView([doc.center.lat, doc.center.lng], doc.zoom || 16);
    else if (propertyBounds) map.fitBounds(propertyBounds.pad(0.1));
    else map.setView([0, 0], 2);
  }

  async function loadPins() {
    if (!signedIn) return;
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

  function insideRegion(lat, lng) {
    const region = map.options.maxBounds;
    return !region || region.contains([lat, lng]);
  }
  function milesFromProperty(lat, lng) {
    return propertyBounds ? map.distance([lat, lng], propertyBounds.getCenter()) / 1609.34 : 0;
  }
  function directionFromProperty(lat, lng) {
    const c = propertyBounds.getCenter();
    const dLng = (lng - c.lng) * Math.cos((lat + c.lat) / 2 * Math.PI / 180);
    const deg = (Math.atan2(dLng, lat - c.lat) * 180 / Math.PI + 360) % 360;
    return ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][Math.round(deg / 45) % 8];
  }
  function farAwayMessage(lat, lng) {
    return `You're ${Math.round(milesFromProperty(lat, lng))} mi ${directionFromProperty(lat, lng)} of the property, beyond what this map shows`;
  }
  let farNotified = false;

  function updateHere(pos) {
    const ll = [pos.coords.latitude, pos.coords.longitude];
    lastFix = pos;
    if (!insideRegion(ll[0], ll[1])) {
      // Far from the land (home, the road in): the map stays on the property.
      if (!farNotified) { showStatus(farAwayMessage(ll[0], ll[1])); farNotified = true; }
      follow = false; $("btn-locate").classList.remove("active");
      return;
    }
    farNotified = false;
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
    if (follow && lastFix && insideRegion(lastFix.coords.latitude, lastFix.coords.longitude)) {
      map.setView([lastFix.coords.latitude, lastFix.coords.longitude], Math.max(map.getZoom(), 17));
    }
    if (!(lastFix && !insideRegion(lastFix.coords.latitude, lastFix.coords.longitude))) showStatus(follow ? "Following your position" : "Stopped following");
  });
  map.on("dragstart", () => { if (follow) { follow = false; $("btn-locate").classList.remove("active"); } });

  // ---- Pin here --------------------------------------------------------------
  function bestFix() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error("No GPS available"));
      // Start from the fix Locate already has, if it is fresh; readings only improve on it.
      let best = (lastFix && Date.now() - lastFix.timestamp < 15000) ? lastFix : null;
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
      if (!insideRegion(c.latitude, c.longitude)) {
        showStatus(farAwayMessage(c.latitude, c.longitude) + "; pins are for when you're on the land");
        return;
      }
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

  $("menu-offline").addEventListener("click", async () => {
    closeMenu();
    if (!("caches" in window)) { showStatus("Offline caching not supported here"); return; }
    const area = (propertyBounds && propertyBounds.isValid() ? propertyBounds : map.getBounds()).pad(0.5);
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

  let propertyDoc = null;
  $("btn-home").addEventListener("click", () => {
    follow = false; $("btn-locate").classList.remove("active");
    goHome(propertyDoc);
  });

  // ---- Menu ------------------------------------------------------------------
  function closeMenu() { $("menu").hidden = true; }
  $("btn-menu").addEventListener("click", () => { $("menu").hidden = !$("menu").hidden; });
  map.on("click", closeMenu);
  $("menu-layer").addEventListener("click", () => {
    streetsOn = !streetsOn;
    if (streetsOn) { map.removeLayer(imagery); streets.addTo(map); } else { map.removeLayer(streets); imagery.addTo(map); }
    $("menu-layer").textContent = streetsOn ? "Satellite" : "Streets";
    closeMenu();
  });
  $("menu-layers-toggle").addEventListener("click", () => { $("menu-layers").hidden = !$("menu-layers").hidden; });
  $("menu-signin").addEventListener("click", () => {
    closeMenu();
    $("signin-key").value = "";
    $("signin-sheet").hidden = false;
    setTimeout(() => $("signin-key").focus(), 50);
  });
  $("menu-signout").addEventListener("click", () => {
    closeMenu();
    clearKey();
    setSignedIn(false);
    showStatus("Signed out");
  });
  $("signin-cancel").addEventListener("click", () => { $("signin-sheet").hidden = true; });
  $("signin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    setKey($("signin-key").value.trim());
    $("signin-sheet").hidden = true;
    if (await checkSession()) { await loadPins(); flushQueue(); showStatus("Signed in"); }
    else { clearKey(); showStatus("That key was not accepted"); }
  });

  // ---- Boot ------------------------------------------------------------------
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

  (async () => {
    try {
      await loadProperty();
    } catch (err) {
      showStatus("Could not load the map: " + err.message, true);
      map.setView([0, 0], 2);
    }
    try {
      if (await checkSession()) { await loadPins(); flushQueue(); }
    } catch (err) {
      showStatus("Could not load pins: " + err.message);
    }
  })();
})();
