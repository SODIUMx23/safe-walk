import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4


def telemetry(**updates):
    return {"device_id": "test-specs-a", "sent_at": datetime.now(timezone.utc).isoformat(),
            "vision_enabled": False, **updates}


def test_health_and_apps(client):
    assert client.get('/health/ready').status_code == 200
    assert client.get('/specs/').status_code == 200
    assert client.get('/portal/').status_code == 200
    assert client.get('/specs/manifest.webmanifest').json()['display'] == 'standalone'
    for name in ('icon-192.png', 'icon-512.png'):
        assert client.get('/specs/' + name).status_code == 200


def test_missing_sensors_are_not_fabricated(client):
    response = client.post('/api/v1/telemetry/telemetry', json=telemetry())
    assert response.status_code == 200
    data = response.json()
    assert data['headspace']['value_cm'] is None
    assert data['ground']['value_cm'] is None
    assert data['instruction'] is None
    assert data['clear_path_certified'] is False
    assert data['gps_usable_for_mesh'] is False


def test_unknown_range_provenance_is_rejected(client):
    assert client.post('/api/v1/telemetry/telemetry', json=telemetry(ground_cm=45)).status_code == 422


def test_negative_void_creates_deduplicated_geoticket_and_user_b_warning(client):
    original = telemetry(latitude=12.9165, longitude=79.1325, accuracy_m=4,
                         ground_cm=45, range_source='manual')
    a = client.post('/api/v1/telemetry/telemetry', json=original)
    assert a.status_code == 200
    assert a.json()['instruction']['kind'] == 'GROUND_VOID'
    assert a.json()['instruction']['pan'] == 0
    hazard_id = a.json()['reported_hazard_id']
    assert hazard_id
    repeated = client.post('/api/v1/telemetry/telemetry', json=telemetry(latitude=12.9165, longitude=79.1325,
                            accuracy_m=4, ground_cm=45, range_source='manual'))
    assert repeated.json()['reported_hazard_id'] == hazard_id
    b = client.post('/api/v1/telemetry/telemetry', json=telemetry(device_id='test-specs-b', latitude=12.916815,
                                                               longitude=79.1325, accuracy_m=4))
    data = b.json()
    assert data['instruction']['kind'] == 'CIVIC_WARNING'
    assert 25 < data['instruction']['reported_distance_m'] < 45
    tickets = client.get('/api/v1/civicmesh/tickets').json()['features']
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket['geometry']['coordinates'] == [79.1325, 12.9165]  # GeoJSON is lon,lat
    assert ticket['properties']['status'] == 'LOCAL_DRAFT_NOT_SUBMITTED'
    assert ticket['properties']['submission_receipt'] is None
    hazards = client.get('/api/v1/civicmesh/hazards', params={'latitude':12.9165,'longitude':79.1325}).json()
    assert len(hazards['features']) == 1
    assert hazards['features'][0]['properties']['evidence_count'] == 1  # one phone is not two voters
    assert client.get(f"/api/v1/civicmesh/tickets/{ticket['id']}/geojson").status_code == 200


def test_simulated_hazard_cannot_warn_real_user(client):
    client.post('/api/v1/telemetry/telemetry', json=telemetry(latitude=12.9165,longitude=79.1325,
                 accuracy_m=3,ground_cm=45,range_source='simulation',simulation=True))
    real = client.post('/api/v1/telemetry/telemetry', json=telemetry(device_id='real-specs-b', latitude=12.9165,
                      longitude=79.1325,accuracy_m=3))
    assert real.json()['nearby_hazards'] == []
    assert real.json()['instruction'] is None


def test_poor_gps_cannot_publish_geohazard(client):
    result = client.post('/api/v1/telemetry/telemetry', json=telemetry(latitude=12.9165,longitude=79.1325,
                         accuracy_m=100,ground_cm=50,range_source='manual')).json()
    assert result['instruction']['kind'] == 'GROUND_VOID'
    assert result['reported_hazard_id'] is None


def test_stale_and_out_of_order_telemetry(client):
    body = telemetry()
    assert client.post('/api/v1/telemetry/telemetry', json=body).status_code == 200
    assert client.post('/api/v1/telemetry/telemetry', json=body).status_code == 409
    body['sent_at'] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert client.post('/api/v1/telemetry/telemetry', json=body).status_code == 422


def test_fall_is_only_suspected_above_threshold(client):
    at = client.post('/api/v1/telemetry/telemetry', json=telemetry(peak_g=3.5)).json()
    above = client.post('/api/v1/telemetry/telemetry', json=telemetry(peak_g=3.501)).json()
    assert at['fall_suspected'] is False
    assert above['fall_suspected'] is True
    assert above['instruction']['kind'] == 'IMPACT'


def test_sos_sbar_no_invented_vitals_and_idempotent(client):
    meta = {'event_id': str(uuid4()), 'device_id':'test-specs-a','trigger':'HIGH_G_IMPACT','peak_g':3.7,
            'occurred_at':datetime.now(timezone.utc).isoformat()}
    first = client.post('/api/v1/emergency/sos', data={'metadata':json.dumps(meta)})
    assert first.status_code == 201
    result = first.json()
    assert result['archive']['status'] == 'NOT_PROVIDED'
    assert result['sbar']['requires_human_review'] is True
    assert result['sbar']['emergency_services_contacted'] is False
    assert 'NOT confirmed' in result['sbar']['situation']
    assert 'NOT assessed' in result['sbar']['assessment']
    second = client.post('/api/v1/emergency/sos', data={'metadata':json.dumps(meta)})
    assert second.json()['id'] == result['id']
    assert len(client.get('/api/v1/emergency/incidents').json()['incidents']) == 1


def test_invalid_video_does_not_erase_sos(client):
    meta = {'device_id':'test-specs-a','trigger':'PANIC'}
    result = client.post('/api/v1/emergency/sos', data={'metadata':json.dumps(meta)},
                         files=[('video_segments',('bad.webm',b'not video','video/webm'))])
    assert result.status_code == 201
    assert result.json()['archive']['status'] == 'FAILED'
    assert result.json()['caregiver_hub_received'] is True


def test_test_trigger_requires_simulation_flag(client):
    result = client.post('/api/v1/emergency/sos', data={'metadata':json.dumps({'device_id':'test-specs-a','trigger':'CAREGIVER_TEST'})})
    assert result.status_code == 422


def test_voice_sample_requires_consent(client):
    result = client.post('/api/v1/kinvoice/enroll_voice', files={'audio':('sample.wav',b'invalid','audio/wav')})
    assert result.status_code == 422


def test_out_of_jurisdiction_ticket_is_not_falsely_submitted(client):
    response = client.post('/api/v1/civicmesh/tickets/create', json={'latitude':12.9716,'longitude':77.5946,
                            'description':'Unverified ground discontinuity in Bengaluru.'})
    assert response.status_code == 201
    assert response.json()['properties']['status'] == 'REQUIRES_JURISDICTION_REVIEW'


def test_oversize_frame_and_nonfinite_values_rejected(client):
    assert client.post('/api/v1/telemetry/telemetry', json=telemetry(frame='a'*420001)).status_code == 422
    assert client.post('/api/v1/telemetry/telemetry', json=telemetry(pitch=91)).status_code == 422


def test_cors_is_wildcard_without_cookies(client):
    response = client.options('/api/v1/telemetry/telemetry', headers={'Origin':'https://another.example','Access-Control-Request-Method':'POST'})
    assert response.headers['access-control-allow-origin'] == '*'
    assert 'access-control-allow-credentials' not in response.headers
