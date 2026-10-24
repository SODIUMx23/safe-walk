import test from 'node:test';
import assert from 'node:assert/strict';
import {CLOCK_PAN, panForClock, SpatialAudio} from '../specs_app/js/audio_spatializer.js';

Object.defineProperty(globalThis, 'navigator', {value: {vibrate: () => true}, configurable: true});
test('clock pan anchors are exactly -0.7, 0, +0.7', () => {
  assert.equal(panForClock("10 o'clock"), -.7);
  assert.equal(panForClock("12 o'clock"), 0);
  assert.equal(panForClock("2 o'clock"), .7);
  assert.equal(panForClock('unknown'), 0);
  assert.ok(Object.isFrozen(CLOCK_PAN));
});
test('cached audio uses StereoPannerNode and measured scheduling status', async () => {
  globalThis.window = {speechSynthesis: {cancel() {}}};
  let actualPan = null; let start = null;
  const node = {connect() {return this;}, disconnect() {}};
  const source = {...node, start(time) {start = time;}, stop() {}};
  const audio = new SpatialAudio();
  audio.context = {state: 'running', currentTime: 12, destination: {},
    createBufferSource: () => source, createGain: () => ({...node, gain: {value: 1}}),
    createStereoPanner: () => ({...node, pan: {setValueAtTime(value) {actualPan = value;}}})};
  audio.buffers.set('halt', {buffer: {}, text: 'Papa, halt.'});
  assert.equal(await audio.speak({text: 'Papa, halt.',token_id:'halt',urgency:'critical',pan:-.7}), true);
  assert.equal(actualPan, -.7);
  assert.equal(start, 12.005);
  assert.ok(audio.status().scheduling_latency_ms >= 5);
  assert.equal(audio.status().audible_latency_measured, false);
  assert.equal(await audio.speak({text:'Low-priority info',urgency:'info'}), false);
});
