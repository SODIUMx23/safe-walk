import io
import json
import shutil
import subprocess
import wave
from datetime import datetime, timezone
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.services.kinvoice import PRIMITIVES
from backend.app.services.vision import analyze_frame, decode_frame
from backend.app.storage import BlobStore


def wav_sample(seconds=10):
    t = np.arange(int(seconds * 16000)) / 16000
    signal = ((np.sin(2 * np.pi * 190 * t) + .4 * np.sin(2 * np.pi * 370 * t)) * 8000).astype('<i2')
    output = io.BytesIO()
    with wave.open(output, 'wb') as file:
        file.setnchannels(1); file.setsampwidth(2); file.setframerate(16000); file.writeframes(signal.tobytes())
    return output.getvalue()


def test_auth_roles_and_camera_state_are_protected(tmp_path, monkeypatch):
    for key in ('DEVICE_API_TOKEN_FILE','CAREGIVER_API_TOKEN_FILE','ARCHIVE_KEY_FILE','POSTGRES_PASSWORD_FILE','REDIS_PASSWORD_FILE'):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None, data_dir=tmp_path, device_api_token='d'*40, caregiver_api_token='c'*40,
                        database_url='',redis_url='',mqtt_host='',minio_endpoint='')
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/portal/state').status_code == 401
        assert client.get('/api/v1/portal/state',headers={'Authorization':'Bearer '+'d'*40}).status_code == 403
        assert client.get('/api/v1/portal/state',headers={'Authorization':'Bearer '+'c'*40}).status_code == 200
        with client.websocket_connect('/api/v1/portal/live') as ws:
            ws.send_json({'token':'c'*40})
            assert ws.receive_json()['type'] == 'connected'


def test_encrypted_local_archive_roundtrip_and_tamper_detection(tmp_path, monkeypatch):
    monkeypatch.delenv('ARCHIVE_KEY_FILE', raising=False); monkeypatch.delenv('ARCHIVE_KEY', raising=False)
    store = BlobStore(Settings(_env_file=None,data_dir=tmp_path))
    payload = b'private incident video bytes'
    record = store.put('incident-example',payload)
    encrypted = (tmp_path/'archives'/record['object_key']).read_bytes()
    assert payload not in encrypted
    assert store.get(record['object_key']) == payload
    damaged = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    (tmp_path/'archives'/record['object_key']).write_bytes(damaged)
    with pytest.raises(Exception):
        store.get(record['object_key'])


def test_unknown_light_and_depth_do_not_become_metric_measurements():
    dark = np.zeros((480,640,3),np.uint8)
    result = analyze_frame(dark)
    assert result['quality'] == 'LOW_LIGHT'
    assert result['metric_depth_available'] is False
    assert result['candidates'] == []


def test_jpeg_roundtrip_and_reject_non_jpeg():
    import base64
    image = np.full((480,640,3),120,np.uint8)
    _, jpeg = cv2.imencode('.jpg',image)
    decoded, raw = decode_frame(base64.b64encode(jpeg).decode())
    assert decoded.shape == (480,640,3)
    with pytest.raises(ValueError):
        decode_frame(base64.b64encode(b'not a jpeg').decode())


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is a documented system dependency')
def test_voice_enrollment_is_explicitly_not_cloning(client):
    result = client.post('/api/v1/kinvoice/enroll_voice', data={'consent':'true'},
                         files={'audio':('sample.wav',wav_sample(),'audio/wav')})
    assert result.status_code == 201
    data = result.json()
    assert data['is_voice_clone'] is False
    assert len(data['simulated_embedding']) == 32
    assert len(data['tokens']) == 40
    assert data['raw_sample_retained'] is False
    assert 'NOT_CLONING' in data['kind']


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is a documented system dependency')
def test_blackbox_actual_media_is_archived_and_retrievable(client, tmp_path):
    path = tmp_path/'test.webm'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=green:s=320x240:r=12',
                    '-t','1','-c:v','libvpx','-threads','1','-y',str(path)],check=True,timeout=15)
    meta = {'event_id':str(uuid4()),'device_id':'test-specs-media','trigger':'CAREGIVER_TEST',
            'simulation':True,'occurred_at':datetime.now(timezone.utc).isoformat(),'segment_durations_ms':[1000]}
    response = client.post('/api/v1/emergency/sos',data={'metadata':json.dumps(meta)},
                           files={'video_segments':('test.webm',path.read_bytes(),'video/webm')})
    assert response.status_code == 201
    data = response.json()
    assert data['archive']['status'] == 'ARCHIVED'
    video = client.get(f"/api/v1/emergency/incidents/{data['id']}/video")
    assert video.status_code == 200
    assert video.headers['content-type'] == 'video/mp4'
    assert b'ftyp' in video.content[:40]


def test_primitive_dictionary_contains_exactly_forty_entries():
    assert len(PRIMITIVES) == 40
    assert {'halt_void','duck','step_right','step_left'} <= PRIMITIVES.keys()
