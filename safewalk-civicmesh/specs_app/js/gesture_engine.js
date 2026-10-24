/** Pointer-based gesture arbitration: no ghost single-tap on a double/two-finger tap. */
export class GestureEngine {
  constructor(surface, actions) {
    this.surface = surface;
    this.actions = actions;
    this.pointers = new Map();
    this.timers = [];
    this.tapTimer = null;
    this.lastTapAt = 0;
    this.keyTimer = null;
    this.handlers = {
      pointerdown: e => this.down(e), pointermove: e => this.move(e),
      pointerup: e => this.up(e), pointercancel: () => this.cancel(),
      lostpointercapture: e => { if (this.pointers.has(e.pointerId)) this.cancel(); },
      contextmenu: e => e.preventDefault(), keydown: e => this.keyDown(e), keyup: e => this.keyUp(e),
      blur: () => this.cancel()
    };
    Object.entries(this.handlers).forEach(([event, handler]) => surface.addEventListener(event, handler, {passive: false}));
  }

  buzz(pattern) { try { navigator.vibrate?.(pattern); } catch { /* Optional API. */ } }
  clearHold() { this.timers.forEach(clearTimeout); this.timers = []; this.buzz(0); }
  invoke(name) { Promise.resolve(this.actions[name]?.()).catch(error => this.actions.onError?.(error)); }

  down(event) {
    if (event.button !== 0 || event.target.closest('button,a,input,select,textarea')) return;
    event.preventDefault();
    if (!this.pointers.size) {
      this.started = performance.now(); this.invalid = false; this.longFired = false; this.twoFinger = false;
    }
    this.pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    try { this.surface.setPointerCapture(event.pointerId); } catch { /* Old browsers can still track surface touches. */ }
    if (this.pointers.size > 1) {
      this.clearHold();
      clearTimeout(this.tapTimer); this.lastTapAt = 0;
      this.twoFinger = this.pointers.size === 2 && performance.now() - this.started < 180;
      if (this.pointers.size > 2 || !this.twoFinger) this.invalid = true;
    } else {
      [500, 1000, 1500].forEach(delay => this.timers.push(setTimeout(() => { if (!this.invalid) this.buzz(20); }, delay)));
      this.timers.push(setTimeout(() => {
        if (this.invalid || this.pointers.size !== 1) return;
        this.longFired = true; this.lastTapAt = 0; clearTimeout(this.tapTimer);
        this.buzz([80, 40, 80]); this.invoke('panic');
      }, 2000));
    }
  }

  move(event) {
    const origin = this.pointers.get(event.pointerId);
    if (!origin) return;
    event.preventDefault();
    if (Math.hypot(event.clientX - origin.x, event.clientY - origin.y) > 25) {
      this.invalid = true; this.clearHold();
    }
  }

  up(event) {
    if (!this.pointers.has(event.pointerId)) return;
    this.move(event);
    this.pointers.delete(event.pointerId);
    if (this.pointers.size) return;
    this.clearHold();
    const elapsed = performance.now() - this.started;
    if (this.invalid || this.longFired) return;
    if (this.twoFinger) { if (elapsed < 420) this.invoke('rupee'); return; }
    if (elapsed > 450) return;
    const now = performance.now();
    if (this.lastTapAt && now - this.lastTapAt <= 330) {
      clearTimeout(this.tapTimer); this.lastTapAt = 0; this.invoke('describe');
    } else {
      this.lastTapAt = now;
      this.tapTimer = setTimeout(() => { this.lastTapAt = 0; this.invoke('replay'); }, 340);
    }
  }

  keyDown(event) {
    if (event.repeat) return;
    const key = event.key.toLowerCase();
    if (key === ' ' || key === 'enter' || key === 'r' || key === 's') event.preventDefault();
    if (key === ' ') this.invoke('replay');
    if (key === 'enter') this.invoke('describe');
    if (key === 'r') this.invoke('rupee');
    if (key === 's') {
      this.buzz(20);
      this.keyTimer = setTimeout(() => { this.keyTimer = null; this.buzz([80, 40, 80]); this.invoke('panic'); }, 2000);
    }
  }
  keyUp(event) { if (event.key.toLowerCase() === 's') { clearTimeout(this.keyTimer); this.keyTimer = null; } }
  cancel() { this.clearHold(); clearTimeout(this.keyTimer); this.keyTimer = null; this.pointers.clear(); this.invalid = true; }
  destroy() {
    this.cancel(); clearTimeout(this.tapTimer);
    Object.entries(this.handlers).forEach(([event, handler]) => this.surface.removeEventListener(event, handler));
  }
}
