const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
const TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>, &copy; CartoDB';

const COLOR_HOP = '#f59e0b';
const COLOR_TIMEOUT = '#fbbf24';
const COLOR_TARGET = '#ef4444';
const COLOR_SOURCE = '#06b6d4';
const COLOR_LINE = '#22d3ee';

let map, traceSegments = [], markers = [], hopCoords = [], animTimer = null;
let activeEntry = null;
let activeEventSource = null;
let currentTraceStream = null;
let traceAttempts = 0;
const MAX_TRACE_ATTEMPTS = 3;
let coordinateRegistry = {};
let hopCounter = 0;
let oceanicHops = {};

function initMap() {
  map = L.map('map', {
    center: [20, 0],
    zoom: 2,
    zoomControl: false,
    worldCopyJump: true,
  });
  L.control.zoom({ position: 'topright' }).addTo(map);

  // Reset zoom button
  var ResetControl = L.Control.extend({
    options: { position: 'topright' },
    onAdd: function() {
      var btn = L.DomUtil.create('button', 'reset-zoom-btn');
      btn.innerHTML = '&#8634;';
      btn.title = 'Reset zoom to fit all hops';
      L.DomEvent.disableClickPropagation(btn);
      btn.onclick = function() { fitMapToHops(); };
      return btn;
    }
  });
  new ResetControl().addTo(map);

  L.tileLayer(TILE_URL, { attribution: TILE_ATTR, maxZoom: 18, subdomains: 'abcd' }).addTo(map);
}

function fitMapToHops() {
  var valid = [];
  for (var i = 0; i < hopCoords.length; i++) {
    var c = hopCoords[i];
    if (c && c.lat != null) valid.push([c.lat, c.lng]);
  }
  if (valid.length === 0) return;
  if (valid.length === 1) {
    map.setView(valid[0], 9, { animate: true, duration: 2.0 });
    return;
  }
  if (valid.length === 2) {
    map.setView(valid[1], 15, { animate: true, duration: 2.5 });
    return;
  }
  // Fit all points with high maxZoom — only zooms out when lines leave the screen
  map.fitBounds(valid, { paddingTopLeft: [320, 40], paddingBottomRight: [40, 40], maxZoom: 15, animate: true, duration: 2.5 });
}

function clearMap() {
  if (currentTraceStream) { currentTraceStream.close(); currentTraceStream = null; }
  if (activeEventSource) { activeEventSource.close(); activeEventSource = null; }
  if (animTimer) { clearInterval(animTimer); animTimer = null; }
  markers.forEach(m => map.removeLayer(m));
  markers = [];
  traceSegments.forEach(s => map.removeLayer(s));
  traceSegments = [];
  oceanMidMarkers.forEach(function(m) { map.removeLayer(m); });
  oceanMidMarkers = [];
  hopCoords = [];
  coordinateRegistry = {};
  oceanicHops = {};
  hopCounter = 0;
  activeEntry = null;
  document.getElementById('hopEntries').innerHTML = '<div class="text-slate-600 text-[10px] font-mono">Ready. Select a destination and click Trace Route.</div>';
  document.getElementById('traceProgress').classList.add('hidden');
  document.getElementById('traceBtn').disabled = false;
  document.getElementById('traceBtn').textContent = 'Trace Route';
  document.getElementById('traceBtn').className = 'flex-1 bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed';
}

function makeBadgeIcon(number, color, glowClass) {
  const extraClass = glowClass || '';
  return L.divIcon({
    className: 'custom-hop-badge',
    html: '<div class="hop-badge-circle ' + extraClass + '" style="background:' + color + '">' + number + '</div>',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

function applyJitter(rawLat, rawLng) {
  var coordKey = rawLat.toFixed(4) + ',' + rawLng.toFixed(4);
  if (coordinateRegistry[coordKey]) {
    var count = coordinateRegistry[coordKey];
    var baseSpacing = 0.0015;
    var radius = baseSpacing * count;
    var angle = count * (2 * Math.PI / 6);
    var jitLat = rawLat + radius * Math.cos(angle);
    var jitLng = rawLng + radius * Math.sin(angle);
    coordinateRegistry[coordKey] += 1;
    return { lat: jitLat, lng: jitLng, key: coordKey, stacked: true, stackCount: count };
  }
  coordinateRegistry[coordKey] = 1;
  return { lat: rawLat, lng: rawLng, key: coordKey, stacked: false, stackCount: 0 };
}
function addMarker(lat, lng, number, color, hopData, glowClass) {
  var extraClass = glowClass || '';
  var icon = makeBadgeIcon(number, color, extraClass);
  var m = L.marker([lat, lng], { icon, interactive: true }).addTo(map);
  m.on('click', function() {
    showDetail(hopData);
    highlightSidebarEntry(hopData);
    map.setView([lat, lng], 13, { animate: true, duration: 1.0 });
  });
  m._ixpData = hopData;
  markers.push(m);
  return m;
}

function highlightSidebarEntry(hopData) {
  let id = hopData._sidebarId || hopData._entryId;
  if (!id && hopData.hop) {
    id = 'sidebar-hop-' + hopData.hop;
  } else if (!id && hopData.type === 'target') {
    id = 'sidebar-target';
  }
  if (!id) return;
  var el = document.getElementById(id);
  if (el && !el.classList.contains('expanded')) {
    if (activeEntry && activeEntry !== el) {
      activeEntry.classList.remove('expanded', 'highlighted');
    }
    el.classList.add('expanded', 'highlighted');
    activeEntry = el;
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setTimeout(function() { el.classList.remove('highlighted'); }, 1800);
  }
}

function showDetail(h) {
  // Sidebar accordion already shows all data — just trigger expand if sidebar entry exists
  if (h._sidebarId) {
    var el = document.getElementById(h._sidebarId);
    if (el && !el.classList.contains('expanded')) {
      el.click();
    }
  }
}

function addHopEntry(hopData, color) {
  const entries = document.getElementById('hopEntries');
  if (entries.querySelector('.placeholder')) {
    entries.innerHTML = '';
  }
  const num = hopData.hop;
  let sidebarId;
  if (hopData.type === 'target') {
    sidebarId = 'sidebar-target';
  } else {
    sidebarId = 'sidebar-hop-' + num;
  }
  hopData._sidebarId = sidebarId;
  hopData._entryId = sidebarId;

  const div = document.createElement('div');
  div.id = sidebarId;
  div.className = 'hop-entry';

  const summary = document.createElement('div');
  summary.className = 'hop-summary';

  const dot = document.createElement('span');
  dot.className = 'hop-indicator';
  dot.style.background = color;
  summary.appendChild(dot);

  const label = document.createElement('span');
  label.className = 'hop-label';
  var suffix = '';
  if (hopData._stacked && hopData._stackCount > 0) {
    suffix = ' \u00D7' + (hopData._stackCount + 1);
  }
  if (hopData.timeout) {
    label.textContent = 'Hop ' + num + ':  * * *' + suffix;
    label.style.color = 'rgba(245,158,11,0.7)';
  } else if (hopData.type === 'target') {
    label.textContent = 'Target: ' + (hopData.org || 'Destination').substring(0, 22) + suffix;
    label.style.color = '#ef4444';
  } else {
    const isp = (hopData.org || hopData.isp || 'Router').substring(0, 26);
    label.textContent = 'Hop ' + num + ': ' + (isp || 'Router') + suffix;
  }
  label.style.overflow = 'hidden';
  label.style.textOverflow = 'ellipsis';
  label.style.whiteSpace = 'nowrap';
  summary.appendChild(label);

  const rtt = document.createElement('span');
  rtt.className = 'hop-rtt';
  rtt.style.color = '#64748b';
  if (hopData.rtt_cumulative) {
    var delta = hopData.rtt_ms ? '+' + hopData.rtt_ms.toFixed(1) : '';
    rtt.textContent = (delta ? delta + ' / ' : '') + hopData.rtt_cumulative.toFixed(1) + 'ms';
  }
  summary.appendChild(rtt);

  div.appendChild(summary);

  if (!hopData.timeout) {
    const detail = document.createElement('div');
    detail.className = 'hop-detail';
    var parts = [];

    // ── ISP / ASN identity ──
    var asnSuffix = hopData.asn ? ' (AS' + hopData.asn + ')' : '';
    parts.push('<div class="enrich-section"><span class="badge badge-isp">ISP</span> ' +
      '<span class="detail-val">' + (hopData.org || hopData.isp || 'Unspecified Core Fabric') + asnSuffix + '</span></div>');

    // ── Firewall / ICMP error ──
    if (hopData.icmp_error) {
      var icmpLabel = {'!H':'Host Unreachable','!N':'Network Unreachable','!X':'Admin Prohibited','!P':'Protocol Unreachable'}[hopData.icmp_error] || hopData.icmp_error;
      parts.push('<div class="enrich-section"><span class="badge badge-100g">' + hopData.icmp_error + '</span> ' +
        '<span class="detail-val">Firewall: ' + icmpLabel + '</span></div>');
    }

    // ── MPLS label ──
    if (hopData.mpls_label) {
      parts.push('<div class="enrich-section"><span class="badge badge-mpls">MPLS</span> ' +
        '<span class="detail-val">' + hopData.mpls_label + '</span></div>');
    }

    // ── IP + hostname ──
    if (hopData.ip || hopData.hostname) {
      var idLine = '<div class="enrich-section"><span class="badge badge-net">NET</span> ';
      if (hopData.ip) idLine += '<code>' + hopData.ip + '</code>';
      if (hopData.hostname) idLine += ' <span class="host-badge tooltip-host" title="' + hopData.hostname + '">host</span>';
      idLine += '</div>';
      parts.push(idLine);
    }

    // ── Interconnect (PeeringDB) ──
    if (hopData.interconnect && hopData.interconnect !== 'Internal Backbone (same AS)') {
      var icType = hopData.interconnect_type === 'IXP' ? 'badge-ixp' : 'badge-pni';
      var icLabel = hopData.interconnect_type === 'IXP' ? 'IXP' : 'PNI';
      parts.push('<div class="enrich-section"><span class="badge ' + icType + '">' + icLabel + '</span> ' +
        '<span class="detail-val">' + hopData.interconnect + '</span></div>');
    }

    // ── Submarine cable ──
    if (hopData.submarine_cable) {
      parts.push('<div class="enrich-section"><span class="badge badge-sub">SUB</span> ' +
        '<span class="detail-val">' + hopData.submarine_cable + '</span></div>');
    }

    // ── Hardware interface ──
    if (hopData.iface_speed || hopData.iface_type || hopData.iface) {
      var speedClass = 'badge-iface';
      if (hopData.iface_speed && hopData.iface_speed.indexOf('100G') !== -1) speedClass = 'badge-100g';
      else if (hopData.iface_speed && hopData.iface_speed.indexOf('10G') !== -1) speedClass = 'badge-10g';
      else if (hopData.iface_speed && hopData.iface_speed.indexOf('LAG') !== -1) speedClass = 'badge-lag';
      var ifLine = '<div class="enrich-section"><span class="badge ' + speedClass + '">' + (hopData.iface_speed || 'IF') + '</span> ';
      if (hopData.iface_type) ifLine += '<span class="detail-val">' + hopData.iface_type + '</span>';
      if (hopData.iface) ifLine += ' <code class="text-[10px]">' + hopData.iface + '</code>';
      ifLine += '</div>';
      parts.push(ifLine);
    }

    // ── Router role ──
    if (hopData.router_role) {
      var roleClass = hopData.router_role.indexOf('Core') !== -1 || hopData.router_role.indexOf('Backbone') !== -1 ?
        'badge-core' : 'badge-edge';
      parts.push('<div class="enrich-section"><span class="badge ' + roleClass + '">&#x2606;</span> ' +
        '<span class="detail-val">' + hopData.router_role + '</span></div>');
    }

    // ── IATA / gateway city ──
    if (hopData.iata_city) {
      parts.push('<div class="enrich-section"><span class="badge badge-iata">GATE</span> ' +
        '<span class="detail-val">' + hopData.iata_city + '</span></div>');
    }

    // ── RDAP allocation ──
    if (hopData.allocated) {
      parts.push('<div class="enrich-section"><span class="badge badge-rdap">REG</span> ' +
        '<span class="detail-val">Allocated: ' + hopData.allocated + ' (' + (hopData.registry || '?') + ')</span></div>');
    }

    // ── Trivia / labels ──
    if (hopData.labels && hopData.labels.length) {
      parts.push('<div class="enrich-section text-yellow-400/60 text-[10px]">' +
        hopData.labels.map(function(l) { return l; }).join(' | ') + '</div>');
    }

    // ── Oceanic leap explainer ──
    if (oceanicHops[hopData.hop]) {
      var o = oceanicHops[hopData.hop];
      var distKm = o.distance || 0;
      var lightMs = (distKm / 200).toFixed(0);
      parts.push(
        '<div class="enrich-section oceanic-explainer mt-2 pt-2 border-t border-sky-900/50">' +
        '<span class="badge badge-sub">SUB</span>' +
        '<span class="detail-val text-[10px] leading-relaxed block mt-1">' +
        '<strong>Deep-Dive: The Invisible Ocean Pipe</strong><br>' +
        'This segment spans <b>' + distKm.toLocaleString() + ' km</b> of subsea fiber-optic cable. ' +
        'Underwater optical repeaters amplify the laser every 60km at Layer 1 (Physical) — ' +
        'they never read IP headers, so traceroute cannot see them. ' +
        'The 14,000km voyage looks like a single ~' + lightMs + 'ms hop to our packets.</span>' +
        '</div>');
    }

    // ── RTT stats ──
    if (hopData.rtt_ms || hopData.rtt_cumulative) {
      parts.push('<div class="enrich-section text-[9px] mt-1 pt-1 border-t border-slate-800">' +
        '<span class="text-slate-500">RTT: </span>' +
        '<span class="text-slate-200">' + (hopData.rtt_ms ? hopData.rtt_ms.toFixed(1) + 'ms' : '\u2014') + '</span>' +
        ' <span class="text-slate-600 mx-1">|</span> ' +
        '<span class="text-slate-500">Cumul: </span>' +
        '<span class="text-slate-200">' + (hopData.rtt_cumulative ? hopData.rtt_cumulative.toFixed(1) + 'ms' : '\u2014') + '</span>' +
        '</div>');
    }

    detail.innerHTML = parts.join('');
    div.appendChild(detail);
  }

function pingMarker(hopData) {
  markers.forEach(function(m) {
    if (m._ixpData && m._ixpData._sidebarId === hopData._sidebarId) {
      var el = m.getElement();
      if (el) {
        var badge = el.querySelector('.hop-badge-circle');
        if (badge) {
          badge.classList.add('ping-ring');
          setTimeout(function() { badge.classList.remove('ping-ring'); }, 1500);
        }
      }
    }
  });
}

  div.addEventListener('click', function() {
    var wasExpanded = div.classList.contains('expanded');
    if (wasExpanded) {
      div.classList.remove('expanded', 'highlighted');
    } else {
      // Collapse any previously expanded entry
      if (activeEntry && activeEntry !== div) {
        activeEntry.classList.remove('expanded', 'highlighted');
      }
      div.classList.add('expanded', 'highlighted');
      activeEntry = div;
      showDetail(hopData);
      pingMarker(hopData);
      // Zoom to the marker's actual jittered position
      markers.forEach(function(m) {
        if (m._ixpData && m._ixpData._sidebarId === hopData._sidebarId) {
          var pos = m.getLatLng();
          map.setView(pos, 13, { animate: true, duration: 1.0 });
        }
      });
      div.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      setTimeout(function() { div.classList.remove('highlighted'); }, 1800);
    }
  });

  entries.appendChild(div);
  entries.parentElement.scrollTop = entries.parentElement.scrollHeight;
}

function latColor(rtt) {
  if (rtt == null) return 'rgba(148,163,184,0.4)';
  if (rtt < 20) return '#22d3ee';
  if (rtt < 70) return '#f59e0b';
  return '#ef4444';
}

function curveArc(a, b) {
  var midLat = (a[0] + b[0]) / 2;
  var midLng = (a[1] + b[1]) / 2;
  var dLat = b[0] - a[0];
  var dLng = b[1] - a[1];
  var dist = Math.sqrt(dLat * dLat + dLng * dLng);
  var bulge = Math.min(dist * 0.15, 8);
  var perpLat = -dLng;
  var perpLng = dLat;
  var len = Math.sqrt(perpLat * perpLat + perpLng * perpLng) || 1;
  var steps = Math.max(4, Math.floor(dist * 3));
  var pts = [];
  for (var i = 0; i <= steps; i++) {
    var t = i / steps;
    var curvedT = Math.sin(t * Math.PI);
    pts.push([
      a[0] + dLat * t + perpLat / len * bulge * curvedT,
      a[1] + dLng * t + perpLng / len * bulge * curvedT
    ]);
  }
  return pts;
}

function haversineKm(lat1, lng1, lat2, lng2) {
  var R = 6371;
  var dLat = (lat2 - lat1) * Math.PI / 180;
  var dLng = (lng2 - lng1) * Math.PI / 180;
  var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLng / 2) * Math.sin(dLng / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function oceanIcon() {
  return L.divIcon({
    className: 'ocean-badge',
    html: '<div class="ocean-badge-circle">&#9889;</div>',
    iconSize: [22, 22], iconAnchor: [11, 11]
  });
}

var oceanMidMarkers = [];

function extendPolyline() {
  traceSegments.forEach(function(s) { map.removeLayer(s); });
  traceSegments = [];
  oceanMidMarkers.forEach(function(m) { map.removeLayer(m); });
  oceanMidMarkers = [];

  var valid = [];
  for (var i = 0; i < hopCoords.length; i++) {
    var c = hopCoords[i];
    if (c && c.lat != null) valid.push({ lat: c.lat, lng: c.lng, rtt: c.rtt, idx: i, hop: c.hop || i });
  }
  for (var i = 0; i < valid.length - 1; i++) {
    var a = valid[i], b = valid[i + 1];
    var curved = curveArc([a.lat, a.lng], [b.lat, b.lng]);
    var dist = haversineKm(a.lat, a.lng, b.lat, b.lng);
    var deltaRtt = (b.rtt || 0) - (a.rtt || 0);
    var isOcean = dist > 3000 && Math.abs(deltaRtt) > 60;

    if (isOcean) {
      oceanicHops[b.hop] = { distance: Math.round(dist), deltaRtt: Math.round(deltaRtt) };
      var seg = L.polyline(curved, {
        color: '#0284c7', weight: 3, opacity: 0.9,
        dashArray: '10, 15', smoothFactor: 0,
        className: 'ixp-flow-line ixp-ocean-line'
      }).addTo(map);
      traceSegments.push(seg);
      // Subsea anchor at midpoint
      var midPt = curved[Math.floor(curved.length / 2)];
      var midMarker = L.marker([midPt[0], midPt[1]], { icon: oceanIcon(), interactive: true }).addTo(map);
      midMarker._oceanHops = { from: a.idx, to: b.idx, distance: Math.round(dist), deltaRtt: deltaRtt };
      midMarker.on('click', function() {
        var entryId = 'sidebar-hop-' + b.idx;
        var el = document.getElementById(entryId);
        if (el) {
          if (activeEntry && activeEntry !== el) activeEntry.classList.remove('expanded', 'highlighted');
          el.classList.add('expanded', 'highlighted');
          activeEntry = el;
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          setTimeout(function() { el.classList.remove('highlighted'); }, 1800);
        }
      });
      oceanMidMarkers.push(midMarker);
    } else {
      var color = latColor(b.rtt);
      var seg = L.polyline(curved, { color: color, weight: 2.5, opacity: 0.85, smoothFactor: 0, className: 'ixp-flow-line' }).addTo(map);
      traceSegments.push(seg);
    }
  }
}

function finalizeTrace() {
  var btn = document.getElementById('traceBtn');
  btn.disabled = false;
  btn.textContent = 'Trace Complete ✓';
  btn.className = 'flex-1 bg-green-600 hover:bg-green-500 text-white text-xs font-medium px-3 py-1.5 rounded-md transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed';
  setTimeout(function() {
    btn.textContent = 'Trace Route';
    btn.className = 'flex-1 bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium px-3 py-1.5 rounded-md transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed';
  }, 2500);
  var elapsed = ((Date.now() - window._traceStart) / 1000).toFixed(1);
  document.getElementById('traceProgress').textContent = 'Done \u2014 ' + hopCounter + ' hops in ' + elapsed + 's';
  document.getElementById('traceProgress').classList.remove('hidden');
  // Zoom out to fit the entire trace
  var allLats = [], allLngs = [];
  for (var i = 0; i < hopCoords.length; i++) {
    var c = hopCoords[i];
    if (c && c.lat != null) { allLats.push(c.lat); allLngs.push(c.lng); }
  }
  if (allLats.length >= 2) {
    map.fitBounds([[Math.min.apply(null, allLats), Math.min.apply(null, allLngs)], [Math.max.apply(null, allLats), Math.max.apply(null, allLngs)]],
      { paddingTopLeft: [320, 30], paddingBottomRight: [30, 30], animate: true, duration: 4.0 });
  }
}

function doTrace() {
  const sel = document.getElementById('targetSelect');
  const domain = sel.value;
  if (!domain) { return; }
  const btn = document.getElementById('traceBtn');
  btn.disabled = true;
  btn.textContent = 'Tracing...';

  // ── Full lifecycle teardown ──
  if (currentTraceStream) { currentTraceStream.close(); currentTraceStream = null; }
  if (activeEventSource) { activeEventSource.close(); activeEventSource = null; }
  clearMap();
  coordinateRegistry = {};
  traceAttempts = 0;

  const progress = document.getElementById('traceProgress');
  progress.classList.remove('hidden');
  progress.textContent = 'Submitting trace...';

  function startStream() {
    var es = new EventSource('/api/trace?target=' + encodeURIComponent(domain));
    currentTraceStream = es;
    activeEventSource = es;
    window._traceStart = Date.now();

    var hardTimer = setTimeout(function() {
      if (es.readyState !== 2) {
        es.close(); currentTraceStream = null; activeEventSource = null;
        progress.textContent = 'Trace timed out after 90s';
        btn.disabled = false;
        btn.textContent = 'Trace Route';
      }
    }, 90000);

    var tickTimer = setInterval(function() {
      if (es.readyState === 2) { clearInterval(tickTimer); return; }
      var sec = ((Date.now() - window._traceStart) / 1000).toFixed(1);
      progress.textContent = '\u23F1 ' + sec + 's \u2014 waiting...';
    }, 500);

    es.addEventListener('message', function(e) {
      if (e.data === '[DONE]') {
        es.close(); currentTraceStream = null; activeEventSource = null;
        clearTimeout(hardTimer); clearInterval(tickTimer); finalizeTrace(); return;
      }
      try {
        const hop = JSON.parse(e.data);
        if (hop.error) {
          es.close(); currentTraceStream = null; activeEventSource = null;
          clearTimeout(hardTimer); clearInterval(tickTimer);
          progress.textContent = hop.error;
          btn.disabled = false; btn.textContent = 'Trace Route'; return;
        }
        if (hop.type === 'heartbeat') {
          progress.textContent = '\u23F1 ' + hop.elapsed + 's \u2014 tracing hop ' + hop.hop + '...';
          return;
        }
        if (hop.type === 'meta') {
          progress.textContent = 'Polling Globalping...';
          return;
        }
        if (hop.type === 'source') {
          const srcJit = applyJitter(hop.lat, hop.lng);
          const sourceHop = { type: 'source', lat: srcJit.lat, lng: srcJit.lng, city: hop.city, rtt_ms: 0, rtt_cumulative: 0, org: 'Source', hostname: hop.city, _stacked: srcJit.stacked, _stackCount: srcJit.stackCount };
          addMarker(srcJit.lat, srcJit.lng, 'S', COLOR_SOURCE, sourceHop, 'src-badge');
          hopCoords.push({lat: srcJit.lat, lng: srcJit.lng, rtt: 0, hop: 'S'});
          extendPolyline();
          fitMapToHops();
          progress.textContent = 'Querying from ' + hop.city + '...';
          return;
        }
        if (hop.type === 'target') {
          if (hop.lat !== null && hop.lat !== undefined) {
            hopCounter++;
            const tgtJit = applyJitter(hop.lat, hop.lng);
            const targetHop = Object.assign({}, hop, { type: 'target', lat: tgtJit.lat, lng: tgtJit.lng, _stacked: tgtJit.stacked, _stackCount: tgtJit.stackCount });
            addMarker(tgtJit.lat, tgtJit.lng, 'T', COLOR_TARGET, targetHop, 'tgt-badge');
            hopCoords.push({lat: tgtJit.lat, lng: tgtJit.lng, rtt: 0, hop: 'T'});
            extendPolyline();
            addHopEntry(targetHop, COLOR_TARGET);
          }
          es.close(); currentTraceStream = null; activeEventSource = null;
          clearTimeout(hardTimer); clearInterval(tickTimer); finalizeTrace(); return;
        }
        if (hop.timeout) {
          hopCoords.push(null);
          addHopEntry(hop, COLOR_TIMEOUT);
          progress.textContent = 'Hop ' + hop.hop + ' / 30 \u2014 timeout';
          return;
        }
        hopCounter++;
        const badgeNum = hop.hop;
        if (hop.lat !== null && hop.lat !== undefined) {
          const hopJit = applyJitter(hop.lat, hop.lng);
          hop._stacked = hopJit.stacked;
          hop._stackCount = hopJit.stackCount;
          addMarker(hopJit.lat, hopJit.lng, badgeNum, COLOR_HOP, hop, '');
          hopCoords.push({lat: hopJit.lat, lng: hopJit.lng, rtt: hop.rtt_ms || 0, hop: hop.hop});
          extendPolyline();
          fitMapToHops();
        } else {
          hopCoords.push(null);
        }
        addHopEntry(hop, COLOR_HOP);
        progress.textContent = 'Hop ' + hop.hop + ' / 30';
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    });

    // ── Circuit-breaker error handler ──
    es.addEventListener('error', function() {
      es.close(); currentTraceStream = null; activeEventSource = null;
      clearTimeout(hardTimer); clearInterval(tickTimer);
      traceAttempts++;
      if (es.readyState === 2) {
        finalizeTrace();
      } else if (traceAttempts < MAX_TRACE_ATTEMPTS) {
        progress.textContent = 'Retry ' + traceAttempts + '/' + MAX_TRACE_ATTEMPTS + '...';
        clearMap();
        coordinateRegistry = {};
        setTimeout(startStream, 1000);
      } else {
        progress.textContent = '\u274C Trace failed: Connection timed out after maximum attempts. Please check destination host configuration.';
        btn.disabled = false;
        btn.textContent = 'Trace Route';
      }
    });
  }

  startStream();
}

async function loadPresets() {
  try {
    const r = await fetch('/api/presets');
    const presets = await r.json();
    const sel = document.getElementById('targetSelect');
    presets.forEach(function(p) {
      const opt = document.createElement('option');
      opt.value = p.domain;
      opt.textContent = p.label;
      sel.appendChild(opt);
    });
  } catch (e) {}
}

document.addEventListener('DOMContentLoaded', function() {
  initMap();
  loadPresets();
  document.getElementById('traceBtn').addEventListener('click', doTrace);
  document.getElementById('clearBtn').addEventListener('click', clearMap);
});
