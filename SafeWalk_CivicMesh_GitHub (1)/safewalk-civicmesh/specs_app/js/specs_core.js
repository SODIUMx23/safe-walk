import {SpatialAudio, vibrate} from './audio_spatializer.js';
import {GestureEngine} from './gesture_engine.js';

const $ = id => document.getElementById(id);
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const normalizeAngle = n => ((n + 180) % 360 + 360) % 360 - 180;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const stored = (area, key, fallback = '') => { try { return area.getItem(key) || fallback; } catch { return fallback; } };
const save = (area, key, value) => { try { area.setItem(key, value); } catch { /* Private browsing can disable storage. */ } };

/** Ring of finalized clips, NOT a broken concatenation of headerless WebM chunks. */
export class RollingVideoBuffer {
  constructor(stream, onError = () => {}) {
    this.stream = stream; this.onError = onError; this.entries = []; this.enabled = false;
    this.recorder = null; this.timer = null; this.waiters = [];
    this.mimeType = ['video/webm;codecs=vp8', 'video/webm;codecs=vp9', 'video/mp4'].find(type => window.MediaRecorder?.isTypeSupported(type));
  }
  start() {
    if (!window.MediaRecorder) { this.onError(new Error('Blackbox unavailable: MediaRecorder is unsupported. SOS can still send without video.')); return false; }
    this.enabled = true; this.next(); return true;
  }
  next() {
    if (!this.enabled) return;
    const chunks = [];
    const began = Date.now();
    try {
      const options = {videoBitsPerSecond: 350000};
      if (this.mimeType) options.mimeType = this.mimeType;
      const recorder = new MediaRecorder(this.stream, options);
      this.recorder = recorder;
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = () => { this.enabled = false; this.onError(new Error('Blackbox recording failed. Caregiver alerts remain available without video.')); };
      recorder.onstop = () => {
        clearTimeout(this.timer);
        const end = Date.now();
        const blob = new Blob(chunks, {type: recorder.mimeType || this.mimeType || 'video/webm'});
        if (blob.size && end - began >= 150) this.entries.push({blob, start: began, end, duration: end - began});
        this.entries = this.entries.filter(entry => entry.end > end - 10000).slice(-7);
        this.recorder = null;
        this.waiters.splice(0).forEach(resolve => resolve());
        if (this.enabled) this.next();
      };
      recorder.start();
      this.timer = setTimeout(() => { if (recorder.state !== 'inactive') recorder.stop(); }, 2000);
    } catch (error) {
      this.enabled = false; this.onError(error); this.waiters.splice(0).forEach(resolve => resolve());
    }
  }
  async lock() {
    const recorder = this.recorder;
    if (recorder && recorder.state !== 'inactive') {
      const stopped = new Promise(resolve => this.waiters.push(resolve));
      clearTimeout(this.timer); recorder.stop();
      await Promise.race([stopped, sleep(3000)]);
    }
    const now = Date.now();
    // Blob references are immutable; the rolling recorder continues with fresh RAM entries.
    const locked = this.entries.filter(entry => entry.end > now - 10000).slice(-7);
    this.entries = [];
    return locked;
  }
  stop() {
    this.enabled = false; clearTimeout(this.timer);
    if (this.recorder?.state !== 'inactive') { try { this.recorder?.stop(); } catch { /* Already stopped. */ } }
    this.entries = [];
  }
}

class SpecsNode {
  constructor() {
    this.deviceId = stored(localStorage, 'safewalk-device', crypto.randomUUID());
    save(localStorage, 'safewalk-device', this.deviceId);
    this.token = stored(sessionStorage, 'safewalk-device-token');
    $('apiToken').value = this.token;
    $('voiceProfile').value = stored(sessionStorage, 'safewalk-voice-profile', 'default');
    this.running = false; this.rupeeMode = false; this.stream = null; this.buffer = null;
    this.gps = null; this.geoWatch = null; this.rawBeta = null; this.baseline = null;
    this.orientation = {pitch: 0, roll: 0, heading: null, calibrated: false};
    this.peakG = null; this.lastImpactAt = 0; this.sendingSos = false; this.lastRupeeAt = 0;
    this.pack = null; this.loopTimer = null; this.telemetryController = null;
    this.audio = new SpatialAudio(status => {
      $('cacheStatus').textContent = `VOICE CACHE · ${status.count} / 40`;
    });
    this.onOrientation = event => this.handleOrientation(event);
    this.onMotion = event => this.handleMotion(event);
    this.gestures = new GestureEngine($('touchSurface'), {
      replay: () => this.audio.replay(), describe: () => this.describeScene(),
      rupee: () => this.toggleRupee(), panic: () => this.emergency('PANIC'),
      onError: error => this.error(error.message)
    });
    this.bind();
  }

  bind() {
    $('settingsButton').onclick = () => $('setupDialog').showModal();
    $('closeSetupButton').onclick = () => $('setupDialog').close();
    $('startButton').onclick = () => this.start();
    $('stopButton').onclick = () => this.stop();
    $('replayButton').onclick = () => this.audio.replay();
    $('describeButton').onclick = () => this.describeScene();
    $('rupeeButton').onclick = () => this.toggleRupee();
    $('calibrateButton').onclick = () => this.calibrate();
    $('sosButton').onclick = () => $('panicDialog').showModal();
    $('cancelPanicButton').onclick = () => $('panicDialog').close();
    $('confirmPanicButton').onclick = () => { $('panicDialog').close(); this.emergency('PANIC'); };
    $('enrollButton').onclick = () => this.enroll();
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && this.running) {
        this.stop(false);
        this.interrupted = true;
      } else if (!document.hidden && this.interrupted) {
        this.interrupted = false;
        this.error('Monitoring stopped when the app went into the background. Restart the session before relying on any cues.');
        this.cue('background', 'Monitoring was interrupted while the app was in the background.', 'warning');
      }
    });
    window.addEventListener('pagehide', () => this.stop(false));
    window.addEventListener('offline', () => {
      this.connection(false); this.cue('offline', 'The server is offline. Cloud guidance is unavailable.', 'warning');
    });
    window.addEventListener('online', () => { if (this.running) $('connectionStatus').textContent = 'RECONNECTING'; });
  }

  async init() {
    try {
      const response = await fetch('/api/v1/config', {signal: AbortSignal.timeout(5000)});
      const config = await response.json();
      if (!config.auth_required) $('devBanner').textContent = 'UNAUTHENTICATED DEVELOPMENT SERVER · DO NOT USE REAL PERSONAL DATA';
      if (config.mode !== 'production') $('tokenHelp').textContent = config.auth_required ? 'Use the device credential for this deployment.' : 'Development adapter active. No access token configured. Use only synthetic test data.';
    } catch { $('devBanner').textContent = 'OFFLINE · CLOUD GUIDANCE IS UNAVAILABLE'; }
    if ('serviceWorker' in navigator && window.isSecureContext) {
      navigator.serviceWorker.register('/specs/sw.js', {scope: '/specs/'}).catch(() => {});
    }
    $('setupDialog').showModal();
  }

  headers() { return this.token ? {Authorization: `Bearer ${this.token}`} : {}; }
  async request(path, options = {}, timeout = 12000) {
    const response = await fetch(path, {...options, headers: {...this.headers(), ...(options.headers || {})},
      signal: options.signal || AbortSignal.timeout(timeout), cache: 'no-store'});
    if (!response.ok) {
      let detail = `Server returned ${response.status}`;
      try { const payload = await response.json(); if (typeof payload.detail === 'string') detail = payload.detail; } catch { /* No JSON response. */ }
      const error = new Error(detail); error.status = response.status; throw error;
    }
    return response.json();
  }
  error(message) { $('critical').textContent = message; }
  connection(online) {
    $('statusDot').classList.toggle('on', online);
    $('connectionStatus').textContent = online ? 'CONNECTED · MONITORING' : this.running ? 'OFFLINE · NO CLOUD GUIDANCE' : 'NOT MONITORING';
    $('connectionStatus').classList.toggle('offline', this.running && !online);
  }
  cue(token, fallback, urgency = 'info', options = {}) {
    const text = this.pack?.tokens?.[token]?.text || fallback;
    return this.audio.speak({text, token_id: token, pan: 0, urgency}, options).catch(error => this.error(error.message));
  }

  async start() {
    if (this.running) { $('setupDialog').close(); return; }
    if (!$('consentSession').checked) { $('setupError').textContent = 'Please read and accept the camera/GPS and experimental-use notice.'; return; }
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      $('setupError').textContent = 'Camera access requires HTTPS (or localhost). Open this deployment directly in a secure browser tab.'; return;
    }
    this.token = $('apiToken').value.trim(); save(sessionStorage, 'safewalk-device-token', this.token);
    $('setupError').textContent = ''; $('startButton').disabled = true;
    // iOS sensor permissions must be requested inside this user gesture, before network awaits.
    const permissions = [];
    for (const constructor of [window.DeviceOrientationEvent, window.DeviceMotionEvent]) {
      if (typeof constructor?.requestPermission === 'function') {
        try { permissions.push(constructor.requestPermission().catch(() => 'denied')); } catch { permissions.push(Promise.resolve('denied')); }
      }
    }
    const audioUnlock = this.audio.unlock();
    try {
      const permissionResults = await Promise.all(permissions);
      await audioUnlock;
      this.stream = await navigator.mediaDevices.getUserMedia({audio: false,
        video: {facingMode: {ideal: 'environment'}, width: {ideal: 640}, height: {ideal: 480}, frameRate: {ideal: 15, max: 15}}});
      $('camera').srcObject = this.stream;
      await $('camera').play();
      this.running = true;
      this.autoImpact = $('consentImpact').checked;
      if ($('consentBlackbox').checked) {
        this.buffer = new RollingVideoBuffer(this.stream, error => this.error(error.message)); this.buffer.start();
      }
      window.addEventListener('deviceorientation', this.onOrientation);
      window.addEventListener('devicemotion', this.onMotion);
      this.startGps();
      this.stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => {
        if (this.running) { this.error('The camera stopped. Monitoring has been stopped.'); this.stop(false); this.cue('camera_lost', 'The camera is unavailable. Guidance is limited.', 'critical'); }
      }));
      $('stopButton').disabled = false;
      $('touchSurface').classList.add('active');
      $('setupDialog').close();
      $('critical').textContent = permissionResults.includes('denied') ? 'Motion/orientation permission denied. Head tilt and automatic impact alerts may be unavailable.' : '';
      this.showGuidance('Experimental guidance is active.', 'Calibrate your neutral tilt. Keep using your cane or guide.');
      this.cue('started', 'SafeWalk started. Keep using your cane or guide. Hazard detection is experimental.');
      this.loop();
      this.warmVoice().catch(error => this.error(`Voice cache unavailable: ${error.message}. Browser speech remains available.`));
    } catch (error) {
      this.stop(false);
      $('setupError').textContent = `Session could not start: ${error.message}`;
      if (!$('setupDialog').open) $('setupDialog').showModal();
    } finally { $('startButton').disabled = false; }
  }

  async warmVoice() {
    const profile = $('voiceProfile').value.trim() || 'default';
    this.pack = await this.request(`/api/v1/kinvoice/primitives?profile_id=${encodeURIComponent(profile)}`, {}, 90000);
    await this.audio.preload(this.pack, this.token);
    save(sessionStorage, 'safewalk-voice-profile', profile);
  }

  stop(announce = true) {
    const wasRunning = this.running;
    this.running = false; clearTimeout(this.loopTimer); this.telemetryController?.abort();
    this.buffer?.stop(); this.buffer = null;
    this.stream?.getTracks().forEach(track => track.stop()); this.stream = null;
    $('camera').srcObject = null;
    if (this.geoWatch !== null) navigator.geolocation?.clearWatch(this.geoWatch);
    this.geoWatch = null; this.gps = null;
    window.removeEventListener('deviceorientation', this.onOrientation);
    window.removeEventListener('devicemotion', this.onMotion);
    $('stopButton').disabled = true; $('touchSurface').classList.remove('active'); this.connection(false);
    if (wasRunning) {
      this.showGuidance('Monitoring is stopped.', 'Restart a session to receive new cues.');
      if (announce) this.cue('stopped', 'SafeWalk monitoring stopped.', 'info', {force: true});
    }
  }

  startGps() {
    if (!navigator.geolocation) { this.error('GPS is not supported. CivicMesh proximity warnings are unavailable.'); return; }
    this.geoWatch = navigator.geolocation.watchPosition(position => {
      this.gps = {latitude: position.coords.latitude, longitude: position.coords.longitude,
        accuracy_m: position.coords.accuracy, heading: Number.isFinite(position.coords.heading) ? position.coords.heading : null,
        receivedAt: Date.now()};
    }, () => {
      this.gps = null; this.error('GPS unavailable. CivicMesh distance warnings are disabled.');
      this.cue('gps_lost', 'GPS is unavailable. Civic hazard warnings are limited.', 'warning');
    }, {enableHighAccuracy: true, maximumAge: 2000, timeout: 12000});
  }
  currentGps() { return this.gps && Date.now() - this.gps.receivedAt < 20000 ? this.gps : null; }
  handleOrientation(event) {
    if (!Number.isFinite(event.beta) || !Number.isFinite(event.gamma)) return;
    this.rawBeta = event.beta;
    if (this.baseline === null) this.baseline = event.beta;
    this.orientation.pitch = clamp(normalizeAngle(event.beta - this.baseline), -90, 90);
    this.orientation.roll = clamp(event.gamma, -180, 180);
    this.orientation.heading = Number.isFinite(event.webkitCompassHeading) ? event.webkitCompassHeading : Number.isFinite(event.alpha) ? (360 - event.alpha) % 360 : null;
  }
  calibrate() {
    if (this.rawBeta === null) { this.error('Orientation readings are unavailable. HeadSpace perspective cues cannot be calibrated.'); return; }
    this.baseline = this.rawBeta; this.orientation.pitch = 0; this.orientation.calibrated = true;
    this.cue('calibrated', 'Neutral head position saved. Camera geometry is still approximate.'); vibrate();
  }
  handleMotion(event) {
    const acceleration = event.accelerationIncludingGravity;
    if (!acceleration || ![acceleration.x, acceleration.y, acceleration.z].every(Number.isFinite)) return;
    const g = Math.hypot(acceleration.x, acceleration.y, acceleration.z) / 9.80665;
    this.peakG = Math.max(this.peakG ?? 0, clamp(g, 0, 100));
    if (g > 3.5 && Date.now() - this.lastImpactAt > 60000) {
      this.lastImpactAt = Date.now();
      this.cue('impact', 'A strong phone impact was detected. Are you safe?', 'critical', {force: true});
      if (this.autoImpact) this.emergency('HIGH_G_IMPACT', g);
      else this.error('Strong phone impact detected. Auto-alert is off. If you need help, hold the canvas for two seconds or use Emergency.');
    }
  }

  frame() {
    const video = $('camera');
    if (!this.running || video.readyState < 2 || !video.videoWidth) return null;
    const canvas = $('frameCanvas');
    const scale = Math.min(640 / video.videoWidth, 480 / video.videoHeight, 1);
    canvas.width = Math.max(16, Math.round(video.videoWidth * scale)); canvas.height = Math.max(16, Math.round(video.videoHeight * scale));
    canvas.getContext('2d', {alpha: false}).drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', .72);
  }
  showGuidance(text, detail = '') { $('guidance').textContent = text; $('guidanceDetail').textContent = detail; }

  async loop() {
    if (!this.running) return;
    const began = performance.now();
    const gps = this.currentGps();
    const peak = this.peakG; this.peakG = null;
    const body = {
      device_id: this.deviceId, sent_at: new Date().toISOString(),
      latitude: gps?.latitude ?? null, longitude: gps?.longitude ?? null, accuracy_m: gps?.accuracy_m ?? null,
      pitch: this.orientation.pitch, roll: this.orientation.roll, orientation_calibrated: this.orientation.calibrated,
      heading_deg: gps?.heading ?? this.orientation.heading, peak_g: peak,
      headspace_cm: null, ground_cm: null, range_source: 'unavailable', boxes: [],
      frame: this.frame(), simulation: false, vision_enabled: true, rupee_guard: this.rupeeMode,
      audio_cache_count: this.audio.buffers.size, audio_latency_ms: this.audio.latencyMs
    };
    this.telemetryController = new AbortController();
    const deadline = setTimeout(() => this.telemetryController?.abort(), 10000);
    try {
      const payload = await this.request('/api/v1/telemetry/telemetry', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), signal: this.telemetryController.signal});
      if (!this.running) return;
      this.connection(true);
      $('headspaceValue').textContent = payload.headspace.value_cm === null ? '—' : `${payload.headspace.value_cm} cm`;
      $('groundValue').textContent = payload.ground.value_cm === null ? '—' : `${payload.ground.value_cm} cm`;
      $('headspaceDetail').textContent = payload.vision.head_observation === 'CANDIDATE' ? 'Visual edge · height unverified' : 'No metric range sensor';
      $('groundDetail').textContent = payload.vision.ground_observation === 'CANDIDATE' ? 'Visual change · depth unverified' : 'Drop depth unavailable';
      if (payload.instruction) {
        this.showGuidance(payload.instruction.text, `${payload.instruction.clock} · ${payload.instruction.source.replaceAll('_', ' ')} · not a clear-path guarantee`);
        this.audio.speak(payload.instruction).catch(error => this.error(error.message));
      }
      if (this.rupeeMode && body.frame && Date.now() - this.lastRupeeAt > 5000) this.scanRupee(body.frame);
    } catch (error) {
      if (!this.running) return;
      this.connection(false);
      if ([401, 403].includes(error.status)) {
        this.stop(false); this.error('Access denied. Update the device token in Settings.');
      } else if (error.status !== 409) {
        this.showGuidance('Cloud guidance is unavailable.', 'Use your cane or guide. No new hazard cues are being received.');
        this.cue('offline', 'The server is offline. Cloud guidance is unavailable.', 'warning');
      }
    } finally {
      clearTimeout(deadline);
      if (this.running) this.loopTimer = setTimeout(() => this.loop(), Math.max(0, 800 - (performance.now() - began)));
    }
  }

  async describeScene() {
    const frame = this.frame();
    if (!frame) { this.error('Start a camera session before requesting a scene description.'); return; }
    try {
      const result = await this.request('/api/v1/vision/describe', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device_id: this.deviceId, frame, pitch: this.orientation.pitch})});
      this.showGuidance(result.speech, 'OpenCV visual baseline · no metric depth');
      await this.audio.speak({text: result.speech, urgency: 'info', pan: 0}, {remember: false});
    } catch (error) { this.error(error.message); this.cue('scene_unavailable', 'A scene description is unavailable. Please check your connection and camera.', 'warning'); }
  }
  toggleRupee() {
    this.rupeeMode = !this.rupeeMode;
    $('rupeeButton').textContent = `Rupee Guard · ${this.rupeeMode ? 'On' : 'Off'}`;
    $('rupeeButton').setAttribute('aria-pressed', String(this.rupeeMode));
    $('modeLabel').textContent = this.rupeeMode ? 'RUPEE GUARD · AUTHENTICITY NOT VERIFIED' : 'EXPERIMENTAL PEDESTRIAN GUIDANCE';
    this.cue(this.rupeeMode ? 'rupee_on' : 'rupee_off', this.rupeeMode ? 'Rupee Guard on. Authenticity cannot be guaranteed.' : 'Rupee Guard off.');
    const frame = this.frame(); if (this.rupeeMode && frame) this.scanRupee(frame);
  }
  async scanRupee(frame) {
    this.lastRupeeAt = Date.now();
    try {
      const result = await this.request('/api/v1/rupeeguard/check', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device_id: this.deviceId, frame, pitch: this.orientation.pitch})});
      if (!this.rupeeMode) return;
      this.showGuidance(result.speech, 'Read-only check · no transaction · no authenticity guarantee');
      await this.audio.speak({text: result.speech, urgency: 'info', pan: 0}, {remember: false});
    } catch (error) { this.error(`Rupee Guard: ${error.message}`); }
  }

  async emergency(trigger, peakG = null) {
    if (this.sendingSos) return;
    this.sendingSos = true; this.token = $('apiToken').value.trim();
    $('sosButton').disabled = true; this.error('Sending caregiver alert. Emergency services have NOT been called.'); vibrate('critical');
    const gps = this.currentGps();
    const metadata = {event_id: crypto.randomUUID(), device_id: this.deviceId, trigger,
      occurred_at: new Date().toISOString(), peak_g: peakG, pitch: this.orientation.pitch, roll: this.orientation.roll,
      latitude: gps?.latitude ?? null, longitude: gps?.longitude ?? null, accuracy_m: gps?.accuracy_m ?? null,
      simulation: false, segment_durations_ms: []};
    try {
      const entries = this.buffer ? await this.buffer.lock() : [];
      metadata.segment_durations_ms = entries.map(entry => entry.duration);
      const form = new FormData(); form.append('metadata', JSON.stringify(metadata));
      entries.forEach((entry, index) => form.append('video_segments', entry.blob, `segment-${index}.${entry.blob.type.includes('mp4') ? 'mp4' : 'webm'}`));
      let result;
      try {
        result = await this.request('/api/v1/emergency/sos', {method: 'POST', body: form}, 60000);
      } catch (error) {
        if ([401, 403].includes(error.status)) throw error;
        // Same event ID is idempotent. Retry without video if the large upload failed.
        const fallback = new FormData(); metadata.segment_durations_ms = []; fallback.append('metadata', JSON.stringify(metadata));
        result = await this.request('/api/v1/emergency/sos', {method: 'POST', body: fallback}, 15000);
      }
      this.error(`Caregiver hub received alert ${result.id.slice(0, 8)}. Video: ${result.archive.status}. No ambulance or emergency service has been called.`);
      this.cue('sos_sent', 'The alert reached the caregiver hub. Emergency services have not been called.', 'critical', {force: true});
    } catch (error) {
      this.error(`ALERT NOT CONFIRMED: ${error.message}. Call your caregiver or 112 if in immediate danger.`);
      this.cue('sos_failed', 'The alert could not be delivered. Call your caregiver or one one two.', 'critical', {force: true});
    } finally { this.sendingSos = false; $('sosButton').disabled = false; }
  }

  async enroll() {
    const sample = $('audioSample').files[0];
    if (!sample || !$('voiceConsent').checked) { $('voiceStatus').textContent = 'Select a 10-second sample and obtain the speaker’s consent.'; return; }
    this.token = $('apiToken').value.trim();
    $('enrollButton').disabled = true; $('voiceStatus').textContent = 'Validating reference sample. This does not clone a voice.';
    try {
      await this.audio.unlock();
      const form = new FormData(); form.append('audio', sample); form.append('consent', 'true');
      const profile = await this.request('/api/v1/kinvoice/enroll_voice', {method: 'POST', body: form}, 90000);
      $('voiceProfile').value = profile.profile_id; this.pack = profile;
      save(sessionStorage, 'safewalk-voice-profile', profile.profile_id);
      await this.audio.preload(profile, this.token);
      $('voiceStatus').textContent = 'Reference fingerprint saved; raw sample discarded. Cached voice is still synthetic. Upload the 40 consented recordings to enable loved-one playback.';
    } catch (error) { $('voiceStatus').textContent = error.message; }
    finally { $('enrollButton').disabled = false; }
  }
}

const node = new SpecsNode();
node.init().catch(error => node.error(error.message));
