"""Bounded real-time event fanout, MQTT, and Redis-backed rate limiting."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from uuid import uuid4

from fastapi import HTTPException

from ..config import secret

log = logging.getLogger(__name__)


class EventHub:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.clients: set[asyncio.Queue] = set()
        self.latest: OrderedDict[str, dict] = OrderedDict()
        self.task = None
        self.pubsub = None

    async def start(self):
        if self.redis:
            self.pubsub = self.redis.pubsub()
            await self.pubsub.subscribe("safewalk:events")
            self.task = asyncio.create_task(self._listen())

    async def _listen(self):
        while True:
            try:
                if self.pubsub is None:
                    self.pubsub = self.redis.pubsub()
                if not self.pubsub.subscribed:
                    await self.pubsub.subscribe("safewalk:events")
                async for message in self.pubsub.listen():
                    if message["type"] == "message":
                        self.dispatch(json.loads(message["data"]))
                # A closed/empty subscriber must not become a busy loop.
                await asyncio.sleep(.25)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("Redis subscriber disconnected; retrying with local fallback")
                if self.pubsub is not None:
                    try:
                        await self.pubsub.aclose()
                    except Exception:
                        log.debug("Subscriber close failed during recovery")
                self.pubsub = None
                await asyncio.sleep(2)

    def dispatch(self, event):
        if event.get("type") == "telemetry":
            device = event["device_id"]
            self.latest[device] = event
            self.latest.move_to_end(device)
            while len(self.latest) > 100:
                self.latest.popitem(last=False)
        for queue in tuple(self.clients):
            if queue.full():
                # Drop old frames rather than grow RAM or block a safety request.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    async def publish(self, event):
        if self.redis:
            try:
                subscribers = await self.redis.publish("safewalk:events", json.dumps(event))
                if subscribers:
                    return
            except Exception:
                log.warning("Redis publish unavailable; using local fanout")
        self.dispatch(event)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.pubsub:
            await self.pubsub.aclose()
        self.latest.clear()


class RateLimiter:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.local: OrderedDict[str, tuple[float, int]] = OrderedDict()

    async def check(self, identity: str, category="api", maximum=240, window=60):
        digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
        bucket = int(time.time() // window)
        key = f"safewalk:rate:{category}:{digest}:{bucket}"
        if self.redis:
            try:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.incr(key)
                    pipe.expire(key, window + 1)
                    result = await pipe.execute()
                count = result[0]
            except Exception:
                log.warning("Redis limiter unavailable; bounded local limiter engaged")
                count = self._increment(key, window)
        else:
            count = self._increment(key, window)
        if count > maximum:
            raise HTTPException(429, "Rate limit reached", headers={"Retry-After": str(window)})

    def _increment(self, key, window):
        now = time.monotonic()
        entry = self.local.get(key)
        count = entry[1] + 1 if entry and entry[0] > now else 1
        self.local[key] = (now + window, count)
        self.local.move_to_end(key)
        while len(self.local) > 4096:
            self.local.popitem(last=False)
        return count


class MQTTBridge:
    def __init__(self, settings):
        self.settings = settings
        self.client = None
        self.connected = False

    def start(self):
        if not self.settings.mqtt_host:
            return
        import paho.mqtt.client as mqtt
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="safewalk-" + uuid4().hex[:12])
        self.client.username_pw_set(self.settings.mqtt_user, secret("MQTT_PASSWORD"))
        if self.settings.mqtt_tls:
            self.client.tls_set()
        self.client.on_connect = self._connected
        self.client.on_disconnect = self._disconnected
        self.client.max_queued_messages_set(100)
        self.client.reconnect_delay_set(1, 30)
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=45)
        self.client.loop_start()

    def _connected(self, client, userdata, flags, reason_code, properties):
        self.connected = reason_code == 0

    def _disconnected(self, client, userdata, flags, reason_code, properties):
        self.connected = False

    def publish(self, category, event):
        if self.client:
            # Do not put frames, audio, medical history, SBAR, or credentials on MQTT.
            allowed = {key: event[key] for key in ("id", "device_id", "kind", "simulation", "received_at", "peak_g") if key in event}
            self.client.publish(f"safewalk/{category}", json.dumps(allowed), qos=1, retain=False)

    def close(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
