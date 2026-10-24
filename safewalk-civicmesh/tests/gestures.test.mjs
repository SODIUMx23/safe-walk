import test from 'node:test';
import assert from 'node:assert/strict';
import {GestureEngine} from '../specs_app/js/gesture_engine.js';

Object.defineProperty(globalThis, 'navigator', {value: {vibrate: () => true}, configurable: true});
class Surface {
  addEventListener() {} removeEventListener() {} setPointerCapture() {}
}
function fixture(t) {
  t.mock.timers.enable({apis: ['setTimeout']});
  const events = [];
  const engine = new GestureEngine(new Surface(), {
    replay: () => events.push('replay'), describe: () => events.push('describe'),
    rupee: () => events.push('rupee'), panic: () => events.push('panic')
  });
  const pointer = (id = 1, x = 100) => ({button: 0, pointerId: id, clientX: x, clientY: 100,
    target: {closest: () => null}, preventDefault() {}});
  t.after(() => engine.destroy());
  return {engine, events, pointer};
}

test('single tap is deferred and replays once', t => {
  const {engine, events, pointer} = fixture(t);
  engine.down(pointer()); engine.up(pointer());
  assert.deepEqual(events, []);
  t.mock.timers.tick(350);
  assert.deepEqual(events, ['replay']);
});
test('double tap cancels single-tap replay', t => {
  const {engine, events, pointer} = fixture(t);
  engine.down(pointer()); engine.up(pointer());
  engine.down(pointer()); engine.up(pointer());
  t.mock.timers.tick(400);
  assert.deepEqual(events, ['describe']);
});
test('two-finger tap toggles only RupeeGuard', t => {
  const {engine, events, pointer} = fixture(t);
  engine.down(pointer(1)); engine.down(pointer(2));
  engine.up(pointer(1)); assert.deepEqual(events, []);
  engine.up(pointer(2)); t.mock.timers.tick(500);
  assert.deepEqual(events, ['rupee']);
});
test('two second hold fires exactly one panic and no replay', t => {
  const {engine, events, pointer} = fixture(t);
  engine.down(pointer()); t.mock.timers.tick(2001); engine.up(pointer());
  t.mock.timers.tick(500);
  assert.deepEqual(events, ['panic']);
});
test('dragging cancels a panic hold', t => {
  const {engine, events, pointer} = fixture(t);
  engine.down(pointer()); engine.move(pointer(1, 150)); t.mock.timers.tick(2200); engine.up(pointer(1, 150));
  assert.deepEqual(events, []);
});
test('cancellation prevents an eventual panic', t => {
  const {engine, events, pointer} = fixture(t);
  engine.down(pointer()); engine.cancel(); t.mock.timers.tick(2200);
  assert.deepEqual(events, []);
});
