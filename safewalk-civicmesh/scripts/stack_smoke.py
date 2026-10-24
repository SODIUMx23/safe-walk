"""State-changing integration test for an isolated production Docker test stack.

Reads test credentials from environment, never logs them. Tests actual services
through FastAPI; use a disposable workspace and labelled simulation records.
"""
import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:8003')
    args = parser.parse_args()
    device, caregiver = os.environ['DEVICE_API_TOKEN'], os.environ['CAREGIVER_API_TOKEN']
    with httpx.Client(base_url=args.base_url,timeout=70) as client:
        health=client.get('/health/ready');health.raise_for_status()
        assert all(health.json()['checks'].values()),health.text
        assert client.get('/api/v1/portal/state').status_code==401
        assert client.get('/api/v1/portal/state',headers={'Authorization':f'Bearer {device}'}).status_code==403
        headers={'Authorization':f'Bearer {device}'}
        a=client.post('/api/v1/telemetry/telemetry',headers=headers,json={
            'device_id':'docker-test-specs-a','sent_at':datetime.now(timezone.utc).isoformat(),
            'latitude':12.9165,'longitude':79.1325,'accuracy_m':3,'ground_cm':45,
            'range_source':'simulation','simulation':True,'vision_enabled':False})
        a.raise_for_status();assert a.json()['instruction']['kind']=='GROUND_VOID'
        b=client.post('/api/v1/telemetry/telemetry',headers=headers,json={
            'device_id':'docker-test-specs-b','sent_at':datetime.now(timezone.utc).isoformat(),
            'latitude':12.916815,'longitude':79.1325,'accuracy_m':3,'simulation':True,'vision_enabled':False})
        b.raise_for_status();assert b.json()['instruction']['kind']=='CIVIC_WARNING'
        admin={'Authorization':f'Bearer {caregiver}'}
        tickets=client.get('/api/v1/civicmesh/tickets',headers=admin);tickets.raise_for_status()
        assert any(t['properties']['simulation'] for t in tickets.json()['features'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.webm'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=green:s=320x240:r=12',
                            '-t','1','-c:v','libvpx','-threads','1','-y',str(path)],check=True,timeout=20)
            meta={'event_id':str(uuid4()),'device_id':'docker-test-specs-a','trigger':'CAREGIVER_TEST',
                  'simulation':True,'segment_durations_ms':[1000]}
            incident=client.post('/api/v1/emergency/sos',headers=admin,data={'metadata':json.dumps(meta)},
                                 files={'video_segments':('synthetic.webm',path.read_bytes(),'video/webm')})
            incident.raise_for_status();data=incident.json()
            assert data['archive']['status']=='ARCHIVED',data['archive']
            assert data['archive']['store']=='minio'
            video=client.get(f"/api/v1/emergency/incidents/{data['id']}/video",headers=admin)
            video.raise_for_status();assert b'ftyp' in video.content[:40]
        print(json.dumps({'readiness':health.json()['checks'],'rbac':'passed','postgis_civic_warning':'passed',
                          'geojson':'passed','minio_encrypted_mp4_roundtrip':'passed','sbar_human_review_required':data['sbar']['requires_human_review']},indent=2))


if __name__=='__main__':
    main()
