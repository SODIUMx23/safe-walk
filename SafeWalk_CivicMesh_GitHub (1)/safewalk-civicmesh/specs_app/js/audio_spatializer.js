/** Stereo guidance. This is two-channel panning, not calibrated 3-D localization. */
export const CLOCK_PAN = Object.freeze({10: -.7, 11: -.35, 12: 0, 1: .35, 2: .7});
export const panForClock = clock => CLOCK_PAN[parseInt(clock, 10)] ?? 0;
const clamp = value => Math.max(-1, Math.min(1, Number.isFinite(value) ? value : 0));
const PRIORITY = {info: 1, warning: 2, critical: 3};

export function vibrate(urgency = 'info') {
  try {
    if (typeof navigator.vibrate === 'function') {
      navigator.vibrate(urgency === 'critical' ? [130, 75, 130, 75, 130] : urgency === 'warning' ? [65, 50, 65] : [25]);
    }
  } catch { /* Vibration is optional and may be blocked by the browser. */ }
}

export class SpatialAudio {
  constructor(onStatus = () => {}) {
    this.context = null;
    this.buffers = new Map();
    this.currentSource = null;
    this.currentUtterance = null;
    this.priority = 0;
    this.last = null;
    this.lastText = '';
    this.lastAt = 0;
    this.latencyMs = null;
    this.onStatus = onStatus;
    this.packKind = 'BROWSER_TTS_NOT_CLONED';
  }

  async unlock() {
    const Constructor = window.AudioContext || window.webkitAudioContext;
    if (Constructor && !this.context) this.context = new Constructor({latencyHint: 'interactive'});
    if (this.context?.state === 'suspended') await this.context.resume();
    if (this.context) {
      // A user-gesture-initiated silent source unlocks iOS output without a loud cue.
      const source = this.context.createBufferSource();
      source.buffer = this.context.createBuffer(1, 1, this.context.sampleRate);
      source.connect(this.context.destination);
      source.start();
    }
  }

  async preload(pack, credential = '') {
    if (!this.context) return 0;
    this.buffers.clear();
    this.packKind = pack.kind;
    const entries = Object.entries(pack.tokens || {});
    let cursor = 0;
    const worker = async () => {
      while (cursor < entries.length) {
        const [id, entry] = entries[cursor++];
        if (!entry.audio_url?.startsWith('/api/v1/kinvoice/primitives/')) continue;
        try {
          const response = await fetch(entry.audio_url, {headers: credential ? {Authorization: `Bearer ${credential}`} : {}, cache: 'no-store', signal: AbortSignal.timeout(12000)});
          if (!response.ok) continue;
          const decoded = await this.context.decodeAudioData(await response.arrayBuffer());
          this.buffers.set(id, {buffer: decoded, text: entry.text});
          this.onStatus(this.status());
        } catch { /* This individual phrase falls back to browser speech. */ }
      }
    };
    await Promise.all(Array.from({length: Math.min(4, entries.length)}, worker));
    this.onStatus(this.status());
    return this.buffers.size;
  }

  status() {
    return {count: this.buffers.size, scheduling_latency_ms: this.latencyMs, voice_kind: this.packKind,
      audio_base_latency_ms: this.context?.baseLatency ? this.context.baseLatency * 1000 : null,
      audible_latency_measured: false};
  }

  stop() {
    if (this.currentSource) {
      try { this.currentSource.onended = null; this.currentSource.stop(); } catch { /* Already ended. */ }
      this.currentSource = null;
    }
    window.speechSynthesis?.cancel();
    this.currentUtterance = null;
    this.priority = 0;
  }

  async speak(instruction, {force = false, remember = true} = {}) {
    if (!instruction?.text) return false;
    const priority = PRIORITY[instruction.urgency] || 1;
    const now = performance.now();
    if (!force && this.lastText === instruction.text && now - this.lastAt < 8000) return false;
    if (!force && this.priority > priority) return false;
    if (remember) this.last = {...instruction, savedAt: Date.now()};
    this.lastText = instruction.text;
    this.lastAt = now;
    this.stop();
    this.priority = priority;
    vibrate(instruction.urgency);
    const cached = this.buffers.get(instruction.token_id);
    const pan = clamp(typeof instruction.pan === 'number' ? instruction.pan : panForClock(instruction.clock));
    if (this.context?.state === 'suspended') {
      try { await this.context.resume(); } catch { /* Fall through to TTS. */ }
    }
    if (cached && cached.text === instruction.text && this.context?.state === 'running') {
      const began = performance.now();
      const source = this.context.createBufferSource();
      source.buffer = cached.buffer;
      const gain = this.context.createGain();
      gain.gain.value = .85;
      if (typeof this.context.createStereoPanner === 'function') {
        const panner = this.context.createStereoPanner();
        panner.pan.setValueAtTime(pan, this.context.currentTime);
        source.connect(panner).connect(gain).connect(this.context.destination);
      } else source.connect(gain).connect(this.context.destination);
      this.currentSource = source;
      source.onended = () => {
        source.disconnect(); gain.disconnect();
        if (this.currentSource === source) { this.currentSource = null; this.priority = 0; }
      };
      const scheduled = this.context.currentTime + .005;
      source.start(scheduled);
      // Scheduling overhead is NOT physical end-to-end / bone-conduction latency.
      this.latencyMs = Math.round((performance.now() - began + 5) * 10) / 10;
      this.onStatus(this.status());
      return true;
    }
    if (!('speechSynthesis' in window)) { this.priority = 0; return false; }
    const utterance = new SpeechSynthesisUtterance(instruction.text);
    utterance.pitch = 1.1;
    utterance.rate = 1.05;
    utterance.volume = .85;
    const voices = window.speechSynthesis.getVoices();
    utterance.voice = voices.find(v => v.localService && /^en[-_]IN/i.test(v.lang)) ||
      voices.find(v => v.localService && /^en/i.test(v.lang)) || voices.find(v => /^en/i.test(v.lang)) || null;
    if (utterance.voice) utterance.lang = utterance.voice.lang;
    const done = () => { if (this.currentUtterance === utterance) { this.currentUtterance = null; this.priority = 0; } };
    utterance.onend = done;
    utterance.onerror = done;
    this.currentUtterance = utterance;
    this.latencyMs = null;
    this.onStatus(this.status());
    window.speechSynthesis.speak(utterance);
    return true;
  }

  replay() {
    const fresh = this.last && Date.now() - this.last.savedAt <= 30000;
    return this.speak(fresh ? this.last : {text: 'No recent guidance is available. This does not mean the path is clear.', urgency: 'info'}, {force: true, remember: false});
  }
}
