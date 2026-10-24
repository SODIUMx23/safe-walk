import asyncio
import json

import pytest

from backend.app.services.hub import EventHub


@pytest.mark.asyncio
async def test_full_subscriber_queue_drops_old_frame_without_growing_ram():
    hub = EventHub()
    queue = asyncio.Queue(maxsize=2)
    hub.clients.add(queue)
    for number in range(20):
        await hub.publish({'type':'telemetry','device_id':'test-hub-device','sequence':number})
    assert queue.qsize() == 2
    assert (await queue.get())['sequence'] == 18
    assert (await queue.get())['sequence'] == 19
    assert hub.latest['test-hub-device']['sequence'] == 19
    await hub.close()


@pytest.mark.asyncio
async def test_failed_redis_resubscribe_recovers_instead_of_busy_looping():
    class Subscriber:
        def __init__(self, failure):
            self.failure, self.subscribed, self.closed = failure, False, False
        async def subscribe(self, channel):
            if self.failure:
                raise ConnectionError('synthetic disconnect')
            self.subscribed = True
        async def listen(self):
            if self.failure:
                raise ConnectionError('synthetic disconnect')
            yield {'type':'message','data':json.dumps({'type':'ticket','sequence':1})}
            await asyncio.Event().wait()
        async def aclose(self):
            self.closed = True
    class Redis:
        def __init__(self):
            self.created = 0
        def pubsub(self):
            self.created += 1
            return Subscriber(failure=self.created < 2)
    redis = Redis()
    hub = EventHub(redis)
    hub.pubsub = Subscriber(failure=True)
    hub.pubsub.subscribed = True
    queue = asyncio.Queue(maxsize=2)
    hub.clients.add(queue)
    hub.task = asyncio.create_task(hub._listen())
    try:
        event = await asyncio.wait_for(queue.get(), timeout=8)
        assert event == {'type':'ticket','sequence':1}
        assert redis.created == 2
    finally:
        await hub.close()
