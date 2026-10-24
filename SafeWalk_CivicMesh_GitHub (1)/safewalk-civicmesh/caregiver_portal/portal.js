const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const human = value => String(value || '').toLowerCase().replaceAll('_', ' ');
const shortTime = value => value ? new Intl.DateTimeFormat('en-IN', {hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(new Date(value)) : '—';
const safeStored = key => { try { return sessionStorage.getItem(key) || ''; } catch { return ''; } };
const svg = (tag, attributes = {}) => { const item = document.createElementNS(SVG, tag); Object.entries(attributes).forEach(([key, value]) => item.setAttribute(key, String(value))); return item; };
const element = (tag, className, text) => { const item = document.createElement(tag); if (className) item.className = className; if (text !== undefined) item.textContent = text; return item; };
const icon = id => { const item = svg('svg', {class: 'icon', 'aria-hidden': 'true'}); item.append(svg('use', {href: `#i-${id}`})); return item; };

class CaregiverPortal {
  constructor() {
    this.token = safeStored('safewalk-caregiver-token'); $('caregiverToken').value = this.token;
    this.devices = new Map(); this.tickets = new Map(); this.incidents = new Map();
    this.selected = ''; this.paused = false; this.socket = null; this.reconnectTimer = null;
    this.backoff = 1000; this.connected = false; this.demoRunning = false; this.toastTimer = null;
    this.activeIncident = null; this.videoUrl = null;
    this.bind();
  }
  bind() {
    $('authButton').onclick = () => { if (!$('authDialog').open) $('authDialog').showModal(); };
    $('cancelAuthButton').onclick = () => $('authDialog').close();
    $('saveAuthButton').onclick = () => this.setCredential();
    $('caregiverToken').addEventListener('keydown', e => { if (e.key === 'Enter') this.setCredential(); });
    $('deviceSelect').onchange = () => { this.selected = $('deviceSelect').value; this.renderSelected(); };
    $('pauseButton').onclick = () => { this.paused = !this.paused; $('pauseButton').textContent = this.paused ? 'Resume view' : 'Pause view'; $('pauseButton').setAttribute('aria-pressed', String(this.paused)); if (!this.paused) this.renderSelected(); };
    $('showTests').onchange = () => { this.renderTickets(); this.renderMap(); this.renderIncidents(); };
    $('testSosButton').onclick = () => this.busy('testSosButton', () => this.testSos());
    $('injectTicketButton').onclick = () => this.busy('injectTicketButton', () => this.injectTicket());
    $('demoButton').onclick = () => this.toggleDemo();
    $('closeIncidentButton').onclick = () => $('incidentDialog').close();
    $('incidentDialog').addEventListener('close', () => { $('incidentVideo').pause(); $('incidentVideo').removeAttribute('src'); $('incidentVideo').hidden = true; if (this.videoUrl) URL.revokeObjectURL(this.videoUrl); this.videoUrl = null; });
    $('playArchiveButton').onclick = () => this.busy('playArchiveButton', () => this.playArchive());
    $('downloadSbarButton').onclick = () => this.downloadJSON(this.activeIncident?.sbar, `sbar-${this.activeIncident?.id}.json`);
    window.addEventListener('online', () => { if (!this.connected) this.connectSocket(); });
    window.addEventListener('pagehide', () => { this.stopDemo(); this.disconnectSocket(); });
  }
  headers() { return this.token ? {Authorization: `Bearer ${this.token}`} : {}; }
  async api(path, options = {}, json = true) {
    const response = await fetch(path, {...options, headers: {...this.headers(), ...(options.headers || {})}, cache: 'no-store', signal: options.signal || AbortSignal.timeout(60000)});
    if (!response.ok) {
      let detail = `Hub returned ${response.status}`;
      try { const payload = await response.json(); if (typeof payload.detail === 'string') detail = payload.detail; } catch { /* Non-JSON proxy response. */ }
      const error = new Error(detail); error.status = response.status;
      if (response.status === 401 || response.status === 403) {
        this.setConnection(false, 'Access token required');
        $('authError').textContent = detail;
        if (!$('authDialog').open) $('authDialog').showModal();
      }
      throw error;
    }
    return json ? response.json() : response;
  }
  async init() {
    $('todayDate').textContent = new Intl.DateTimeFormat('en-IN', {day: '2-digit', month: 'short', year: 'numeric'}).format(new Date());
    try {
      const configuration = await (await fetch('/api/v1/config', {signal: AbortSignal.timeout(5000)})).json();
      if (!configuration.auth_required) $('devNotice').textContent = 'DEVELOPMENT / NO AUTHENTICATION — use synthetic test data only. Docker production mode generates separate device and caregiver credentials.';
      if (configuration.auth_required && !this.token) { this.setConnection(false, 'Access token required'); $('authDialog').showModal(); }
      else { await this.loadState(); this.connectSocket(); }
    } catch (error) { this.toast(error.message); this.setConnection(false, 'Hub unavailable'); }
    this.ageTimer = setInterval(() => { this.renderStats(); this.renderAge(); }, 1000);
    this.refreshTimer = setInterval(() => { if (this.connected) this.loadState().catch(error => this.toast(error.message)); }, 30000);
  }
  async setCredential() {
    this.token = $('caregiverToken').value.trim();
    try { sessionStorage.setItem('safewalk-caregiver-token', this.token); } catch { /* Remain in memory. */ }
    $('authError').textContent = ''; $('saveAuthButton').disabled = true;
    try { await this.loadState(); $('authDialog').close(); this.connectSocket(); }
    catch (error) { $('authError').textContent = error.message; }
    finally { $('saveAuthButton').disabled = false; }
  }
  async loadState() {
    const state = await this.api('/api/v1/portal/state');
    (state.devices || []).forEach(device => this.devices.set(device.device_id, device));
    (state.tickets || []).forEach(ticket => this.tickets.set(ticket.id, ticket));
    (state.incidents || []).forEach(incident => this.incidents.set(incident.id, incident));
    this.renderDevices(); this.renderSelected(); this.renderTickets(); this.renderMap(); this.renderIncidents(); this.renderStats();
    this.updated(state.generated_at);
  }
  disconnectSocket() {
    clearTimeout(this.reconnectTimer);
    if (this.socket) { this.socket.onclose = null; this.socket.close(); this.socket = null; }
    this.connected = false;
  }
  connectSocket() {
    this.disconnectSocket();
    const url = new URL('/api/v1/portal/live', location.href); url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(url); this.socket = socket;
    socket.onopen = () => socket.send(JSON.stringify({type: 'authenticate', token: this.token}));
    socket.onmessage = event => {
      let payload; try { payload = JSON.parse(event.data); } catch { return; }
      if (payload.type === 'connected' || payload.type === 'heartbeat') {
        this.connected = true; this.backoff = 1000; this.setConnection(true); this.updated(payload.server_time); return;
      }
      if (payload.type === 'telemetry') {
        const newDevice = !this.devices.has(payload.device_id); this.devices.set(payload.device_id, payload);
        if (newDevice) this.renderDevices();
        if (this.selected === payload.device_id) this.renderSelected();
      }
      if (payload.ticket) { this.tickets.set(payload.ticket.id, payload.ticket); this.renderTickets(); this.renderMap(); }
      if (payload.incident) {
        const isNew = !this.incidents.has(payload.incident.id); this.incidents.set(payload.incident.id, payload.incident);
        this.renderIncidents();
        if (isNew) this.toast(`${payload.incident.simulation ? 'SIMULATED' : 'REAL'} caregiver alert received. Emergency services have NOT been called.`);
        if (this.activeIncident?.id === payload.incident.id) this.openIncident(payload.incident.id);
      }
      this.renderStats(); this.updated(new Date().toISOString());
    };
    socket.onerror = () => this.setConnection(false, 'Reconnecting to hub');
    socket.onclose = event => {
      this.connected = false; this.setConnection(false, event.code === 1008 ? 'Access or origin rejected' : 'Reconnecting to hub');
      if (event.code === 1008) return;
      this.reconnectTimer = setTimeout(() => this.connectSocket(), this.backoff);
      this.backoff = Math.min(30000, this.backoff * 2);
    };
  }
  setConnection(connected, label = '') {
    $('hubConnection').classList.toggle('offline', !connected);
    $('hubConnection').querySelector('span').textContent = label || (connected ? 'Hub connected' : 'Hub offline');
  }
  updated(time) { $('updatedAt').textContent = `LAST SYNC ${shortTime(time)} · LIVE DATA, NOT A SAFETY CERTIFICATION`; }
  toast(message) { clearTimeout(this.toastTimer); $('toast').textContent = message; this.toastTimer = setTimeout(() => { $('toast').textContent = ''; }, 8500); }
  async busy(id, action) {
    const button = $(id); button.disabled = true;
    try { await action(); } catch (error) { this.toast(error.message); }
    finally { button.disabled = false; }
  }
  renderDevices() {
    const select = $('deviceSelect'); select.replaceChildren();
    if (!this.devices.size) select.append(new Option('No devices', ''));
    for (const [id, device] of this.devices) select.append(new Option(`${device.simulation ? 'TEST · ' : ''}${id.slice(0, 14)}`, id));
    if (!this.devices.has(this.selected)) this.selected = this.devices.keys().next().value || '';
    select.value = this.selected;
  }
  renderStats() {
    const active = [...this.devices.values()].filter(device => Date.now() - new Date(device.received_at).getTime() < 6000);
    const realDevices = active.filter(device => !device.simulation).length;
    const testDevices = active.length - realDevices;
    $('activeDevices').replaceChildren(document.createTextNode(String(active.length)), element('small', '', ' nodes'));
    $('navDeviceCount').textContent = String(active.length);
    $('devicesSub').textContent = active.length ? `${realDevices} live · ${testDevices} simulated` : 'No recent telemetry (6 s timeout)';
    const drafts = [...this.tickets.values()]; const realTickets = drafts.filter(item => !item.properties.simulation).length;
    $('hazardTotal').replaceChildren(document.createTextNode(String(realTickets)), element('small', '', ' reports'));
    $('hazardsSub').textContent = `${drafts.length - realTickets} test drafts · none submitted`;
    const incidents = [...this.incidents.values()]; const realIncidents = incidents.filter(item => !item.simulation).length;
    $('incidentTotal').replaceChildren(document.createTextNode(String(realIncidents)), element('small', '', ' events'));
    $('incidentsSub').textContent = `${incidents.length - realIncidents} simulated · EMS not contacted`;
    const device = this.devices.get(this.selected);
    const ms = device?.audio_latency_ms;
    $('latencyStat').replaceChildren(document.createTextNode(ms == null ? '—' : ms.toFixed(1)), element('small', '', ' ms'));
  }
  renderAge() {
    const device = this.devices.get(this.selected); if (!device) return;
    const age = Math.max(0, Math.floor((Date.now() - new Date(device.received_at).getTime()) / 1000));
    const live = age < 6;
    $('lastSeen').textContent = `${age}s AGO${live ? '' : ' · STALE'}`;
    $('povBadge').className = `tag ${live ? '' : 'warn'}`;
    $('povBadge').replaceChildren(element('i', 'dot'), document.createTextNode(this.paused ? 'VIEW PAUSED' : live ? device.simulation ? 'SIMULATED SESSION' : 'LIVE TELEMETRY' : 'STALE · NOT LIVE'));
  }
  renderSelected() {
    const device = this.devices.get(this.selected);
    if (!device) return;
    $('nodeLabel').textContent = `${device.device_id}${device.simulation ? ' / SCRIPTED TEST' : ' / EXPERIMENTAL AID'}`;
    $('simulationBadge').hidden = !device.simulation;
    $('tiltInfo').textContent = `PITCH ${device.pitch?.toFixed(1) ?? '—'}° / ROLL ${device.roll?.toFixed(1) ?? '—'}°${device.orientation_calibrated ? '' : ' · UNCALIBRATED'}`;
    $('gpsInfo').textContent = device.accuracy_m == null ? 'GPS · NOT AVAILABLE' : `GPS ±${device.accuracy_m.toFixed(0)}m${device.accuracy_m > 25 ? ' · TOO INACCURATE' : ''}`;
    $('latestGuidance').textContent = device.instruction?.text || 'No current guidance cue. This does NOT mean the path is clear.';
    const head = device.headspace?.value_cm; const ground = device.ground?.value_cm;
    $('headValue').textContent = head == null ? '—' : head.toFixed(0);
    $('groundValue').textContent = ground == null ? '—' : ground.toFixed(0);
    $('headDetail').textContent = head == null ? device.vision?.head_observation === 'CANDIDATE' ? 'Visual edge · height unverified' : 'No metric range sensor' : device.simulation ? 'Simulated lower-edge height' : 'Client-reported height · unverified';
    $('groundDetail').textContent = ground == null ? device.vision?.ground_observation === 'CANDIDATE' ? 'Visual change · depth unverified' : 'Drop depth unavailable' : device.simulation ? 'Simulated drop depth' : 'Client-reported drop · unverified';
    $('headSource').textContent = device.range_source === 'unavailable' ? 'UNAVAILABLE' : device.simulation ? 'SIMULATED' : 'REPORTED INPUT';
    $('groundSource').textContent = device.range_source === 'unavailable' ? 'NO SONAR' : device.simulation ? 'SIMULATED' : 'REPORTED INPUT';
    $('headGauge').style.strokeDashoffset = head == null ? '126' : String(126 * (1 - Math.min(1, head / 250)));
    $('groundGauge').style.strokeDashoffset = ground == null ? '126' : String(126 * (1 - Math.min(1, ground / 100)));
    const count = device.audio_cache_count || 0;
    $('kinLatency').textContent = device.audio_latency_ms == null ? '—' : device.audio_latency_ms.toFixed(1);
    $('voiceCount').replaceChildren(document.createTextNode(String(count)), element('span', '', ' / 40'));
    $('voiceCount').lastChild.style.cssText = 'font-size:12px;opacity:.6';
    $('voiceProgress').style.width = `${count / 40 * 100}%`;
    $('cacheTag').textContent = count === 40 ? '40 READY' : 'RAM CACHE';
    $('voiceKind').textContent = device.simulation ? 'No simulated latency claims' : 'Pack or system speech / not cloned';
    if (!this.paused) {
      if (device.frame?.startsWith('data:image/jpeg;base64,')) {
        const image = $('povImage');
        image.onload = () => this.renderBoxes(device, image.naturalWidth, image.naturalHeight);
        image.src = device.frame; image.hidden = false; $('povEmpty').hidden = true;
        $('frameInfo').textContent = device.simulation ? 'SYNTHETIC TEST FRAME · NOT CAMERA FOOTAGE' : 'CONSENTED JPEG SNAPSHOT · NOT A VIDEO CALL';
      } else {
        $('povImage').hidden = true; $('povEmpty').hidden = false; $('povOverlay').replaceChildren();
      }
    }
    this.renderAge();
  }
  renderBoxes(device, width, height) {
    const overlay = $('povOverlay'); overlay.replaceChildren(); overlay.setAttribute('viewBox', `0 0 ${width} ${height}`);
    for (const box of device.vision?.candidates || []) {
      const x = box.x_min * width, y = box.y_min * height;
      const color = box.kind === 'GROUND_VOID' ? '#ffbf87' : '#d3f989';
      overlay.append(svg('rect', {x, y, width: (box.x_max - box.x_min) * width, height: (box.y_max - box.y_min) * height,
        fill: `${color}12`, stroke: color, 'stroke-width': 1.5, rx: 3, 'stroke-dasharray': '5 4'}));
      const text = svg('text', {x: x + 5, y: Math.max(14, y - 7), fill: color, 'font-size': 10, 'font-family': 'monospace'});
      text.textContent = `UNVERIFIED · ${box.label.toUpperCase()}`; overlay.append(text);
    }
  }
  visibleTickets() { return [...this.tickets.values()].filter(item => $('showTests').checked || !item.properties.simulation).sort((a, b) => b.properties.created_at.localeCompare(a.properties.created_at)); }
  renderTickets() {
    const list = $('ticketList'); list.replaceChildren(); const tickets = this.visibleTickets(); $('ticketCount').textContent = String(tickets.length);
    if (!tickets.length) { list.append(element('div', 'empty-row', 'No repair drafts in this view. Reports create local, exportable GeoJSON; they are not automatically submitted to PWD.')); return; }
    for (const ticket of tickets) {
      const properties = ticket.properties; const row = element('article', 'ticket');
      const symbol = element('div', 'ticket-icon'); symbol.append(icon(properties.kind === 'GROUND_VOID' ? 'down' : 'up'));
      const body = element('div', 'ticket-body'); const heading = element('div', 'ticket-heading');
      heading.append(document.createTextNode(`${human(properties.kind)} report`), element('span', properties.simulation ? 'tag demo' : 'tag warn', properties.simulation ? 'SIMULATED' : 'UNVERIFIED'));
      const description = element('p', '', properties.description);
      const metadata = element('div', 'ticket-meta'); metadata.append(element('span', 'mono', ticket.id.slice(0, 8).toUpperCase()), element('span', '', shortTime(properties.created_at)), element('span', '', human(properties.status)));
      body.append(heading, description, metadata);
      const exportButton = element('button', 'export', 'GeoJSON ↗'); exportButton.setAttribute('aria-label', `Export ticket ${ticket.id}`);
      exportButton.onclick = () => { this.exportTicket(ticket.id).catch(error => this.toast(error.message)); };
      row.append(symbol, body, exportButton); list.append(row);
    }
  }
  async exportTicket(id) {
    const response = await this.api(`/api/v1/civicmesh/tickets/${encodeURIComponent(id)}/geojson`, {}, false);
    this.downloadBlob(await response.blob(), `ticket-${id}.geojson`);
  }
  renderMap() {
    const map = $('meshMap'); map.replaceChildren(); const items = this.visibleTickets();
    $('mapEmpty').hidden = !!items.length; if (!items.length) { $('mapScale').textContent = '—'; return; }
    const lat = items.reduce((sum, item) => sum + item.geometry.coordinates[1], 0) / items.length;
    const lon = items.reduce((sum, item) => sum + item.geometry.coordinates[0], 0) / items.length;
    const cosine = Math.max(.01, Math.cos(lat * Math.PI / 180));
    const points = items.map(item => ({item, x: (item.geometry.coordinates[0] - lon) * 111320 * cosine,
      y: -(item.geometry.coordinates[1] - lat) * 111320}));
    const spanX = Math.max(160, ...points.map(point => Math.abs(point.x) * 2 + 100));
    const spanY = Math.max(100, ...points.map(point => Math.abs(point.y) * 2 + 100));
    const metersPerPixel = Math.max(spanX / 310, spanY / 145);
    for (const point of points.slice(0, 100)) {
      const x = 190 + point.x / metersPerPixel, y = 100 + point.y / metersPerPixel;
      const color = point.item.properties.simulation ? '#baa3ef' : '#d3f989'; const group = svg('g');
      const title = svg('title'); title.textContent = `${human(point.item.properties.kind)} · ${point.item.properties.simulation ? 'TEST' : 'UNVERIFIED'} · ${point.item.geometry.coordinates.join(', ')}`;
      group.append(title, svg('circle', {cx: x, cy: y, r: Math.max(1, 45 / metersPerPixel), fill: 'none', stroke: color, 'stroke-opacity': '.45', 'stroke-dasharray': '3 4'}),
        svg('circle', {cx: x, cy: y, r: Math.max(1, 25 / metersPerPixel), fill: color, 'fill-opacity': '.12', stroke: color, 'stroke-opacity': '.6'}),
        svg('circle', {cx: x, cy: y, r: 3, fill: color})); map.append(group);
    }
    const label = svg('text', {x: 13, y: 192, fill: '#859b78', 'font-size': 8, 'font-family': 'monospace'});
    label.textContent = `REPORT LOCATIONS · CENTER ${lat.toFixed(4)}, ${lon.toFixed(4)} · NOT A STREET MAP`; map.append(label);
    $('mapScale').textContent = `${(metersPerPixel * 50).toFixed(0)} m / 50 px`;
  }
  renderIncidents() {
    const list = $('incidentList'); list.replaceChildren();
    const items = [...this.incidents.values()].filter(item => $('showTests').checked || !item.simulation).sort((a, b) => b.received_at.localeCompare(a.received_at)).slice(0, 4);
    if (!items.length) { list.append(element('div', 'empty-row', 'No incidents received. A high-G phone impact is not a clinically confirmed fall.')); return; }
    for (const incident of items) {
      const row = element('div', 'incident-row'); const symbol = element('div', 'incident-symbol'); symbol.append(icon('alert'));
      const body = element('div', 'incident-copy'); body.append(element('b', '', `${incident.simulation ? 'TEST · ' : ''}${human(incident.trigger)}`), element('small', '', `${shortTime(incident.received_at)} · ${human(incident.archive.status)} · no EMS dispatch`));
      const button = element('button', '', 'View SBAR'); button.onclick = () => this.openIncident(incident.id);
      row.append(symbol, body, button); list.append(row);
    }
  }
  openIncident(id) {
    this.activeIncident = this.incidents.get(id); if (!this.activeIncident) return;
    const incident = this.activeIncident; $('incidentTitle').textContent = `${incident.simulation ? 'TEST / ' : ''}SBAR · ${id.slice(0, 8)}`;
    const content = $('sbarContent'); content.replaceChildren();
    for (const key of ['situation', 'background', 'assessment', 'recommendation']) {
      const section = element('section', 'sbar-section'); section.append(element('h3', '', key.toUpperCase()), element('p', '', incident.sbar[key])); content.append(section);
    }
    $('playArchiveButton').disabled = incident.archive.status !== 'ARCHIVED';
    $('playArchiveButton').textContent = incident.archive.status === 'ARCHIVED' ? 'Load encrypted archive' : `Video: ${human(incident.archive.status)}`;
    if (!$('incidentDialog').open) $('incidentDialog').showModal();
  }
  async playArchive() {
    const response = await this.api(`/api/v1/emergency/incidents/${encodeURIComponent(this.activeIncident.id)}/video`, {}, false);
    if (this.videoUrl) URL.revokeObjectURL(this.videoUrl); this.videoUrl = URL.createObjectURL(await response.blob());
    $('incidentVideo').src = this.videoUrl; $('incidentVideo').hidden = false;
    await $('incidentVideo').play();
  }
  downloadJSON(data, filename) { if (data) this.downloadBlob(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}), filename); }
  downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob); const link = element('a'); link.href = url; link.download = filename;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async injectTicket() {
    const ticket = await this.api('/api/v1/civicmesh/tickets/create', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({latitude: 12.9165, longitude: 79.1325, kind: 'GROUND_VOID', description: 'SIMULATION: open drain slab report for exercising the Vellore PWD GeoJSON repair workflow. No real municipal report.', simulation: true})});
    this.tickets.set(ticket.id, ticket); this.renderTickets(); this.renderMap(); this.renderStats(); this.toast('Test repair draft created. Nothing has been submitted to PWD.');
  }
  demoCanvas(phase = 'head', elapsed = 0) {
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
    const c = canvas.getContext('2d'); c.fillStyle = '#132329'; c.fillRect(0, 0, 640, 480);
    const sky = c.createLinearGradient(0, 0, 0, 350); sky.addColorStop(0, '#263f49'); sky.addColorStop(1, '#59706b'); c.fillStyle = sky; c.fillRect(0, 0, 640, 350);
    c.fillStyle = '#26392e'; c.beginPath(); c.moveTo(0, 70); c.lineTo(245, 170); c.lineTo(245, 480); c.lineTo(0, 480); c.fill();
    c.fillStyle = '#334637'; c.beginPath(); c.moveTo(640, 40); c.lineTo(400, 170); c.lineTo(400, 480); c.lineTo(640, 480); c.fill();
    c.fillStyle = '#8b8b70'; c.beginPath(); c.moveTo(245, 200); c.lineTo(400, 200); c.lineTo(570, 480); c.lineTo(70, 480); c.fill();
    c.strokeStyle = '#b2b598'; c.lineWidth = 1; for (let y = 230; y < 480; y += 42) { c.beginPath(); c.moveTo(90, y); c.lineTo(550, y); c.stroke(); }
    if (phase === 'head') { c.fillStyle = '#7f8f6c'; c.fillRect(110, 80, 430, 36); c.strokeStyle = '#d3f989'; c.lineWidth = 3; c.strokeRect(108, 78, 434, 40); }
    else { c.fillStyle = '#111511'; c.beginPath(); c.ellipse(328, 367, 110, 35, 0, 0, Math.PI * 2); c.fill(); c.strokeStyle = '#dba77b'; c.lineWidth = 3; c.stroke(); }
    c.fillStyle = '#090e0ee8'; c.fillRect(0, 0, 640, 47); c.fillRect(0, 433, 640, 47);
    c.fillStyle = '#d8f391'; c.font = 'bold 16px monospace'; c.fillText('SIMULATION / NO CAMERA FOOTAGE', 20, 29);
    c.fillStyle = '#d3dcd0'; c.font = '12px monospace'; c.fillText(`SCRIPTED TEST INPUT · ${phase.toUpperCase()} · ${elapsed.toFixed(1)} s`, 20, 461);
    return canvas;
  }
  async recordTestClip() {
    const canvas = this.demoCanvas('ground');
    if (!canvas.captureStream || !window.MediaRecorder) return null;
    const stream = canvas.captureStream(12); let timer;
    try {
      const mimeType = ['video/webm;codecs=vp8', 'video/webm', 'video/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? {mimeType} : {}); const chunks = [];
      const completed = new Promise((resolve, reject) => {
        recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
        recorder.onstop = () => resolve(new Blob(chunks, {type: recorder.mimeType})); recorder.onerror = reject;
      });
      recorder.start();
      // Repaint so captureStream yields actual video frames, without camera permissions.
      let tick = 0; const context = canvas.getContext('2d');
      timer = setInterval(() => { context.fillStyle = '#090e0e'; context.fillRect(500, 440, 140, 30); context.fillStyle = '#c6e693'; context.font = '12px monospace'; context.fillText(`FRAME ${++tick}`, 510, 461); }, 83);
      await new Promise(resolve => setTimeout(resolve, 1300)); recorder.stop();
      const blob = await completed; return {blob, duration: 1300};
    } catch { return null; }
    finally { clearInterval(timer); stream.getTracks().forEach(track => track.stop()); }
  }
  async testSos() {
    const clip = await this.recordTestClip();
    const metadata = {event_id: crypto.randomUUID(), device_id: 'caregiver-test-node', trigger: 'CAREGIVER_TEST', occurred_at: new Date().toISOString(),
      latitude: 12.9165, longitude: 79.1325, accuracy_m: 5, peak_g: null, simulation: true, segment_durations_ms: clip ? [clip.duration] : []};
    const form = new FormData(); form.append('metadata', JSON.stringify(metadata)); if (clip) form.append('video_segments', clip.blob, 'synthetic-test.webm');
    const incident = await this.api('/api/v1/emergency/sos', {method: 'POST', body: form});
    this.incidents.set(incident.id, incident); this.renderIncidents(); this.renderStats(); this.openIncident(incident.id);
    this.toast(`SIMULATED SOS saved. Video: ${incident.archive.status}. No emergency service contacted.`);
  }
  stopDemo() { this.demoRunning = false; clearTimeout(this.demoTimer); $('demoButton').replaceChildren(icon('pulse'), document.createTextNode('Run simulation')); $('demoButton').setAttribute('aria-pressed', 'false'); }
  toggleDemo() {
    if (this.demoRunning) { this.stopDemo(); this.toast('Simulation stopped. Test records remain labelled and isolated from real proximity warnings.'); return; }
    this.demoRunning = true; this.demoStarted = Date.now(); this.demoTick = 0; this.demoWarned = false;
    this.selected = 'demo-specs-a';
    $('demoButton').replaceChildren(icon('pulse'), document.createTextNode('Stop simulation')); $('demoButton').setAttribute('aria-pressed', 'true');
    this.toast('60-second SCRIPTED simulation started: two test nodes, synthetic images, reported ranges. No actual camera or sensor data.');
    this.sendDemo();
  }
  async sendDemo() {
    if (!this.demoRunning) return;
    const began = performance.now(); const elapsed = (Date.now() - this.demoStarted) / 1000;
    if (elapsed >= 60) { this.stopDemo(); this.toast('Simulation complete. Use the Test SOS control to exercise encrypted video archiving and SBAR.'); return; }
    const phase = Math.floor(elapsed / 12) % 2 === 0 ? 'head' : 'ground';
    try {
      const payload = await this.api('/api/v1/telemetry/telemetry', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        device_id: 'demo-specs-a', sent_at: new Date().toISOString(), latitude: 12.9165, longitude: 79.1325, accuracy_m: 3,
        pitch: 0, roll: 0, orientation_calibrated: true, peak_g: 1, range_source: 'simulation', simulation: true,
        headspace_cm: phase === 'head' ? 165 : null, ground_cm: phase === 'ground' ? 45 : null,
        frame: this.demoCanvas(phase, elapsed).toDataURL('image/jpeg', .75), vision_enabled: false,
        boxes: [{x_min: .2, y_min: phase === 'head' ? .17 : .7, x_max: .8, y_max: phase === 'head' ? .25 : .85, label: phase === 'head' ? 'scripted overhead edge' : 'scripted ground void', confidence: 1}],
        audio_cache_count: 0, audio_latency_ms: null
      })});
      // If no WebSocket is available, show the actual API result, not invented state.
      this.devices.set('demo-specs-a', {...payload, frame: this.demoCanvas(phase, elapsed).toDataURL('image/jpeg', .75)});
      if (this.demoTick++ % 4 === 0) {
        const b = await this.api('/api/v1/telemetry/telemetry', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
          device_id: 'demo-specs-b', sent_at: new Date().toISOString(), latitude: 12.916815, longitude: 79.1325, accuracy_m: 3,
          simulation: true, vision_enabled: false, range_source: 'unavailable'
        })});
        this.devices.set('demo-specs-b', b);
        if (!this.demoWarned && b.instruction?.kind === 'CIVIC_WARNING') { this.demoWarned = true; this.toast(`TEST: User B received an unverified crowd warning about ${b.instruction.reported_distance_m.toFixed(0)} m from the hazard (before the 25 m zone).`); }
      }
      // Preserve an explicit User B (or real-phone) selection between ticks.
      if (!this.selected || !this.devices.has(this.selected)) this.selected = 'demo-specs-a';
      this.renderDevices(); this.renderSelected(); this.renderStats();
    } catch (error) { this.stopDemo(); this.toast(`Simulation stopped: ${error.message}`); return; }
    if (this.demoRunning) this.demoTimer = setTimeout(() => this.sendDemo(), Math.max(0, 800 - (performance.now() - began)));
  }
}

const portal = new CaregiverPortal();
portal.init().catch(error => portal.toast(error.message));
