# SafeWalk CivicMesh

**A self-hosted, mobile-first experimental assistive-technology application.** A true-black Specs PWA sends camera/IMU/GPS telemetry to a FastAPI hub; caregivers receive live snapshots, cautious spatial cues, civic repair drafts, and encrypted incident archives.

> **Not a medical device or a primary navigation aid.** Use a cane, guide, or trained mobility support. This code is runnable, but field safety, clinical accreditation, detector performance, accessibility certification, and production security have not been certified. Do not trial it unsupervised in traffic.

## What is actually implemented

| System | Working implementation | Important boundary |
|---|---|---|
| **HeadSpace** | Camera edge analysis, neutral-tilt calibration, an 18° upward visual sector, clock/pan geometry, and 140–190 cm reported-height fusion | A camera ray cannot establish absolute obstacle height. Wires, awnings, and tailgates can be missed. Visual cues remain unverified. |
| **Negative obstacle profiler** | Ground-contrast discontinuity candidates plus a ≥40 cm **reported drop-depth** threshold | A smartphone has no ground sonar here. Shadows are not depth. Missing/no-echo readings are never converted to a measured void. |
| **KinVoice** | Forty real, decoded RAM-cached audio primitives; stereo panning; consented recording-pack support; eSpeak/browser-speech fallback | A ten-second sample produces a **simulated spectral reference fingerprint**, not XTTS-v2 cloning. Scheduling is measured, not guaranteed below 40 ms. |
| **CivicMesh** | PostGIS proximity queries, report deduplication, 25 m geofences, warnings at 45 m, GeoJSON repair drafts, independent real/test namespaces | 45 m is 20 m before the 25 m boundary. GPS accuracy matters. A local PWD draft is **not** a municipal submission or acknowledgement. |
| **Blackbox Guard** | Approximately ten seconds of finalized RAM video segments, >3.5 g suspected-impact trigger, AES-256-GCM archives in MinIO, factual SBAR summaries | A phone impact is not a confirmed fall. Clinical summaries are unvalidated and contain no invented vitals. No hospital, ambulance, or 112 call is made. |
| **RupeeGuard** | OpenCV UPI QR parsing and Tesseract denomination-text OCR | It cannot verify a QR owner's identity, authenticate a banknote, or make a payment. |

There are no proprietary cloud APIs, required paid services, external frontend libraries, CDN assets, dummy database adapters, fabricated metric sensors, or unimplemented endpoint bodies. The OpenCV detector is a limited, deterministic baseline—not a general-purpose trained scene model.

## Real camera without Windows Docker/WSL: GitHub Codespaces

Follow **[CODESPACES_START.md](CODESPACES_START.md)**. Upload the extracted source to a private GitHub repository and choose **Code → Codespaces → Create**. The included `.devcontainer` installs dependencies and starts the **real camera/sensor PWA and authenticated Python backend** automatically. Open forwarded port 8000's HTTPS address in Android Chrome; no local certificate installation or Windows Docker is needed.

This changes hosting to GitHub's cloud and uses **SQLite + encrypted filesystem storage**, not the full PostgreSQL/MQTT/Redis/MinIO stack. Codespaces quotas/billing apply and first setup can take longer than five minutes. It is not GitHub Pages, the offline HTML simulation, or an always-on production deployment. The original Docker stack remains available below.

## Android phone + Windows laptop: start here

Follow **[MOBILE_DEMO_WINDOWS_ANDROID.md](MOBILE_DEMO_WINDOWS_ANDROID.md)** for the exact self-hosted setup and a three-minute demonstration script. It provides a Windows PowerShell launcher, trusted local HTTPS with mkcert/Caddy on port 8443, a phone URL QR, token setup, and a Private-network firewall rule. **No APK, Android Studio, or external relay is needed.**

After installing Docker/Compose and mkcert, from this project folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_mobile_demo.ps1
```

The phone must trust the public CA generated on your own laptop. Never transfer CA/server private keys or publish the generated `certs` / `phone-setup` directories. Do not bypass browser certificate errors or substitute plain LAN HTTP for the trusted HTTPS setup.

## 1. Run the complete Docker stack

Requirements: Docker Engine with Compose v2, Linux/amd64 recommended, internet for the first build, approximately 6 GB free RAM recommended for builds and 10 GB free disk. MinIO and the Apache-only Timescale extension are built from checksum-verified open-source releases; the first build is slower than pulling binary images.

```bash
docker compose up --build -d
docker compose ps
docker compose exec backend python -m backend.app.cli credentials
```

**No `.env` or default password is required.** The one-shot initializer creates distinct, random secrets in a Docker volume. Copy the **caregiver token** into the portal's Access settings and the **device token** into the mobile Specs settings.

- Caregiver portal: **http://localhost:8000/portal/**
- Specs PWA: **http://localhost:8000/specs/**
- OpenAPI: **http://localhost:8000/docs**
- Readiness: **http://localhost:8000/health/ready**
- MinIO console: **http://localhost:9002** (loopback-only). Operator credentials: `docker compose exec backend python -m backend.app.cli credentials --all`.

Infrastructure ports bind **127.0.0.1** on the host: Mosquitto **1883 / 9001**, PostgreSQL **5432**, MinIO **9000 / 9002**, Redis **6379**. FastAPI exposes **8000**. Containers communicate on their private Compose network.

**A phone connecting to a server's LAN IP needs trusted HTTPS.** Put the backend behind your HTTPS reverse proxy, forward WebSocket upgrades, set an upload limit of at least 40 MB, and allow at least 70 seconds for incident uploads. A plain `http://192.168...` camera page is not a secure context. Open the PWA directly in a tab or install it; embedded browser previews may not delegate camera/motion permissions. Browsers must support the relevant APIs; iOS and Android capabilities differ.

Optional host/retention settings are documented in `.env.example`. Empty `WS_ALLOWED_ORIGINS` means the WebSocket Origin must match the request Host. If a proxy rewrites Host, preserve the original Host or set an exact comma-separated origin list. CORS is wildcard as requested, with cookies disabled; **bearer authorization is still required** in production.

Never delete the `app-secrets` volume without backing up the archive key. Removing it makes old encrypted clips unreadable. `docker compose down` retains data; `docker compose down -v` is intentionally destructive.

## 2. Run directly with Uvicorn

Python **3.13** is the tested interpreter. On Debian/Ubuntu, install the media/OCR dependencies:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg espeak-ng tesseract-ocr tesseract-ocr-eng
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -c requirements.lock
python -m backend.app.cli init-local
python -m backend.app.cli credentials
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

`init-local` creates a private `.env` with separate random access tokens and an archive key, and refuses to overwrite an existing file. **Do not copy the production `.env.example` for a standalone run.** In standalone development the complete SQLite/geodesic adapter and encrypted local filesystem store are used; there is no pretend Redis/MQTT/MinIO connection. Docker uses the actual services and production mode rejects missing dependencies/credentials. If system eSpeak is absent, audio explicitly falls back to browser TTS; ffmpeg is required for uploaded media, and Tesseract is required for currency OCR.

Local development without configured credentials is possible for isolated synthetic-data tests only, and both interfaces display a persistent warning. Never expose that mode publicly with personal data.

## 3. Use the Specs node

1. Mount the phone securely with its **back camera facing the path**. The geometry assumes a fixed portrait mount; changes in orientation, camera FOV, or mount height invalidate geometric assumptions.
2. Open `/specs/` over trusted HTTPS. Read the limitations, enter the device token, and explicitly consent to camera/GPS telemetry.
3. Separately opt into the RAM blackbox and automatic **suspected-impact** alerts. Neither is required to send a manual caregiver alert.
4. Tap **Enable & start session** and grant camera/location/motion permissions. Camera constraints request 640×480 and up to 15 FPS; the server gets a resized JPEG every **800 ms**, not a 15 FPS video call.
5. Hold a neutral, forward-looking pose and tap **Calibrate neutral tilt**. Relative device `beta` is an approximation, not a calibrated head-pose tracker.
6. Keep the application foregrounded. **Monitoring stops when the page becomes hidden.** Mobile browsers do not guarantee background camera, IMU, or speech execution.

| Gesture on the tactile canvas | Action |
|---|---|
| Single tap | Replay a recent cue (older than 30 seconds is rejected as stale) |
| Double tap | Describe the current frame using the honest OpenCV baseline |
| Two-finger tap | Toggle read-only RupeeGuard scanning |
| Two-second hold | Haptic countdown, then real caregiver SOS |

Accessible alternative buttons are always available. When the canvas has keyboard focus: Space replays, Enter describes, R toggles RupeeGuard, and holding S for two seconds sends SOS. Camera video is visually hidden; the primary background is exactly `#000000`. Speech uses local decoded audio with `StereoPannerNode`, or Web Speech with pitch **1.1**, rate **1.05**. Haptics are best effort; some browsers do not implement vibration.

Stereo is **not** individually calibrated 3-D localization. Use open-ear or bone-conduction headphones at a safe volume and preserve environmental hearing. Cached scheduling overhead and Web Audio base latency are not an acoustic latency measurement.

## 4. Caregiver workflow and hardware-free tests

The portal has no invented live values. Unknown measurements remain **—**, stale nodes are marked after six seconds, and latency stays unknown until the device reports an actual cache scheduling measurement.

- **Connect Specs node:** opens the PWA.
- **Run simulation:** a 60-second explicitly scripted two-node test. Synthetic frames and declared ranges are labelled **SIMULATED**. User A publishes a test hazard; User B receives the 45 m prewarning. Tests cannot warn real sessions.
- **Inject test ticket:** creates an actual, exportable GeoJSON draft with `DEMO_NOT_SUBMITTED` status.
- **Test SOS:** creates a labelled clinical-handoff simulation and, when supported, records a synthetic canvas clip to exercise the real transcoder and encrypted archive. It never accesses a camera or calls emergency services.
- **View SBAR:** opens the four factual handoff sections. Archived clips are downloaded only after caregiver authorization and decrypted server-side.
- **GeoJSON:** exports a ticket; no API credential is placed in the download URL.

The digital twin panel is a local metric coordinate plot of reported ticket locations, **not a street map or a navigable route**. No proprietary mapping service or external tile network is used.

## 5. Sensor and geometry contract

API boxes contain normalized `x_min`, `y_min`, `x_max`, `y_max` in [0,1]. The centroid controls continuous pan `clamp(2*cx-1,-1,1)`, with coarse clock sectors:

| Centroid x | Clock | Pan |
|---:|---|---:|
| 0.15 | 10 o'clock | -0.7 |
| 0.325 | 11 o'clock | -0.35 |
| 0.5 | 12 o'clock | 0 |
| 0.675 | 1 o'clock | +0.35 |
| 0.85 | 2 o'clock | +0.7 |

Image edges reach ±1 pan while the clock labels saturate at 10/2. Optical yaw is computed separately from the configured horizontal FOV; clock bins are not precise compass bearings. Relative elevation is `pitch + atan((1-2*cy)*tan(verticalFOV/2))`; the upward sector is [0°,18°]. A reported metric hazard overrides perspective so a range report is not ignored just because its box is outside that sector.

- `headspace_cm`: **reported lower-edge height above pavement**, not distance from the phone. 140–190 cm is the requested head-height band, not a personalized safe clearance.
- `ground_cm`: **reported drop depth relative to pavement**, not absolute phone-to-ground range. A value ≥40 is a void report.
- `range_source`: `unavailable`, `manual`, `external_sensor`, or `simulation`. Non-null metric inputs require explicit provenance. `simulation` requires `simulation=true`.
- A phone-only session always sends metric range inputs as **null**. Visual candidates have no fabricated centimeter readings or distances.
- All reports remain **unverified**, even if a client claims a measured range. The app cannot authenticate an external sensor or field observer.

Visual candidates require three consistent frames for an alert and five for automatic civic reporting. Civic reporting additionally needs a fresh GPS fix with reported accuracy ≤25 m. Reports of the same kind within 12 m merge; repeated reports from one device do not become independent votes. Reports expire after 24 hours unless observed again. A poor or absent GPS fix disables proximity warnings; it does not produce a made-up location.

## 6. KinVoice: simulated enrollment vs actual loved-one playback

`POST /api/v1/kinvoice/enroll_voice` accepts multipart `audio` and explicit `consent=true`. It validates an 8–12 second sample, computes a real normalized 32-bin spectral reference fingerprint, discards the raw sample, and returns forty token definitions. The response prominently states **NOT CLONING**. No XTTS weights are bundled or silently downloaded.

For an actual loved one's voice, record each phrase returned by `GET /api/v1/kinvoice/primitives`. Name the files by token ID, e.g. `halt_void.wav`, `headspace.wav`, `step_right.wav`. The pack must contain all forty IDs once, each 0.15–10 seconds. The backend supports WAV/MP3/OGG/M4A/WebM input and converts to mono PCM WAV.

With the speaker's informed consent:

1. Enroll the ten-second reference through Specs settings or the multipart API; save `profile_id`.
2. Upload a ZIP of the forty actual recordings to `POST /api/v1/kinvoice/recordings` with fields `profile_id`, `archive`, and `consent=true`.
3. Set that profile ID in Specs settings and start a session. The forty recordings are decoded and held in **local AudioBuffer RAM**, not fetched on each cue.

A reference-only profile uses self-hosted **eSpeak**, not the speaker's identity. Browser TTS may use a device/platform voice and is not guaranteed open-source or offline; use the eSpeak/recorded pack when an entirely self-hosted speech path is required. Dynamic descriptions not matching a fixed primitive use TTS and cannot inherit a recorded speaker's voice.

## 7. REST and streaming interfaces

All data APIs require `Authorization: Bearer …` outside isolated tokenless development. Device and caregiver keys are intentionally distinct. This is one trusted caregiver workspace, **not a multi-tenant identity platform**.

| Method / endpoint | Permission / result |
|---|---|
| `POST /api/v1/telemetry/telemetry` | Device/caregiver; validated telemetry, cautious spatial cue, nearby reports |
| `GET /api/v1/civicmesh/hazards` | Device/caregiver; `latitude`, `longitude`, optional `radius_m`, `simulation`; GeoJSON |
| `POST /api/v1/civicmesh/tickets/create` | Caregiver; location or existing `hazard_id`; PWD draft |
| `GET /api/v1/civicmesh/tickets` | Caregiver; GeoJSON queue |
| `GET /api/v1/civicmesh/tickets/{id}/geojson` | Caregiver; authenticated export |
| `POST /api/v1/civicmesh/hazards/{id}/resolve` | Caregiver; stop future warnings (not a claim of municipal repair) |
| `POST /api/v1/vision/describe` | Current JPEG; limited scene description |
| `POST /api/v1/rupeeguard/check` | Current JPEG; read-only OCR/UPI checks |
| `GET /api/v1/kinvoice/primitives` | Forty token definitions; optional `profile_id` |
| `POST /api/v1/kinvoice/enroll_voice` | Consented reference sample, explicit simulated embedding |
| `POST /api/v1/kinvoice/recordings` | Consented forty-recording ZIP |
| `POST /api/v1/emergency/sos` | Multipart JSON `metadata` plus zero to eight `video_segments`; idempotent `event_id` |
| `GET /api/v1/emergency/incidents` | Caregiver; SBAR incidents |
| `GET /api/v1/emergency/incidents/{id}/video` | Caregiver; authenticated, decrypted MP4 |
| `GET /api/v1/portal/state` | Caregiver; initial state |
| `WS /api/v1/portal/live` | Caregiver; first message `{"type":"authenticate","token":"…"}` within five seconds |

Public endpoints expose capability declarations and health only, not credentials or patient data. Raw camera images and medical histories never go onto MQTT. The broker carries small QoS-1 event notifications; Redis handles bounded rate counters and multi-worker event fanout.

## 8. Blackbox implementation details

A MediaRecorder stream is finalized about every two seconds into an independently playable segment. The RAM ring retains the most recent ~10 seconds. This avoids the common invalid-WebM bug of concatenating old headerless `dataavailable` chunks. At an incident the active segment is finalized and immutable Blob references are locked; recording continues into a fresh ring.

The server validates every segment with ffprobe, uses ffmpeg to combine and normalize the latest available ten seconds into MP4, removes audio, then encrypts with a random nonce and AES-256-GCM before writing to a private MinIO bucket. Small capture gaps are possible at segment boundaries; a session that just started has less than ten seconds of history. Unsupported recorders still send SOS without video. If media validation/storage fails, the incident and SBAR remain saved and archive status explicitly becomes `FAILED`.

The clinical incident is published before transcoding so live caregiver notification is not held up by a codec. A repeated `event_id` does not create duplicate incidents. If a large upload fails, the PWA retries the same ID without video. A `PROCESSING` incident left by a worker crash needs operator review; this build is not an emergency-dispatch SLA or a durable clinical job platform.

SBAR assessments state that consciousness, breathing, pulse, blood pressure, bleeding, and injuries are **not assessed**. Background is only what was actually provided. India **112** is informational and must be contacted separately if needed.

## 9. Security, privacy, and operations

- Production startup rejects short/equal tokens or missing PostgreSQL/Redis/MQTT/MinIO configuration.
- Backend runs non-root, without Linux capabilities. Infrastructure ports and console are loopback-only.
- Size-bounded HTTP/media inputs, validated JPEG dimensions, bounded queues, rate limiting, stale telemetry rejection, and explicit source provenance are implemented.
- SOS has a separate rate bucket so navigation/audio traffic cannot exhaust its allowance.
- Application video encryption is independent of MinIO's transport/at-rest settings. **Back up the database, object store, and archive key together, separately protected.**
- API responses are `no-store`. The service worker caches only the public Specs shell: never tokens, frames, API responses, voice samples, or medical clips.
- Enrollment samples are discarded after processing. Consented recording packs and reference fingerprints remain until the operator removes the profile; treat these as personal data.
- Default maintenance runs hourly: seven-day telemetry retention, thirty-day incidents/clips, and expiring civic reports. Volume snapshots/backups need their own deletion policy.
- Logs do not intentionally include camera images, SBAR text, QR data, or credentials. Protect operator terminals and secret volumes.
- Disable public development mode, enable trusted TLS and infrastructure firewalling, preserve WebSocket Origin/Host, and add your reverse-proxy framing policy in real deployments.
- Conduct a threat model, dependency/image vulnerability scan, load/backpressure tests, backup-restore drill, data-consent review, mobile/assistive-reader audit, and supervised field validation before any real-world deployment. Add a suitable identity provider and per-device authorization before multi-family or municipal use.

## 10. Tests

```bash
pip install -r requirements-dev.txt -c requirements.lock
pytest
npm test
npm run check
```

Python tests cover geometry, pan, elevation/drop thresholds, report deduplication, real/test separation, poor GPS, stale ordering, RBAC, WebSocket auth, consent, encrypted media roundtrips, actual ffmpeg archiving, SBAR non-diagnosis, and jurisdiction status. Node's built-in test runner covers gesture arbitration and cached stereo audio.

Optional full-browser smoke test (isolated **development test server only**, no real data):

```bash
pip install playwright==1.64.1
playwright install --with-deps chromium
# In an empty test workspace, run tokenless development Uvicorn on localhost:8000.
python scripts/browser_smoke.py --base-url http://localhost:8000
```

The browser suite uses fake camera/GPS, explicitly marks intercepted telemetry/SOS as simulated, exercises the 40-clip RAM cache, long-press and >3.5 g auto-alerts, plays an archived MP4, and checks desktop/mobile overflow and uncaught JavaScript errors. It writes screenshots/results into the git-ignored `artifacts/` directory.

See **VALIDATION.md** for the actual checks performed in this delivery and any unverified deployment areas.

## Source layout

```text
specs_app/
  index.html
  js/audio_spatializer.js
  js/gesture_engine.js
  js/specs_core.js
  manifest.webmanifest, sw.js, icon.svg, icon-192.png, icon-512.png
caregiver_portal/
  index.html, portal.js
backend/
  Dockerfile
  app/main.py, config.py, models.py, middleware.py, storage.py, cli.py
  app/services/ai_spatial.py, vision.py, kinvoice.py, media.py
  app/services/triage_agent.py, civic.py, hub.py
infra/
  db/Dockerfile, init.sql, init.sh
  minio/Dockerfile
  mosquitto/mosquitto.conf, entrypoint.sh
  secrets/init.sh
  caddy/Caddyfile
tests/
  test_spatial_engine.py, test_api.py, test_security_and_media.py, test_hub.py, conftest.py
  test_mobile_setup.py, test_codespaces_setup.py, gestures.test.mjs, audio.test.mjs
scripts/browser_smoke.py, stack_smoke.py, package_source.py, start_mobile_demo.ps1
scripts/setup_codespace.sh, start_codespace.sh, codespace_info.sh
.devcontainer/devcontainer.json, CODESPACES_START.md
docker-compose.yml, docker-compose.https.yml, MOBILE_DEMO_WINDOWS_ANDROID.md
requirements.txt, requirements-dev.txt, requirements.lock
package.json, pytest.ini, .env.example, .dockerignore, .gitignore
```

## Licensing

Application code: **MIT**, see LICENSE. Third-party components retain their licenses; see THIRD_PARTY_NOTICES.md. Timescale is explicitly compiled with `APACHE_ONLY=1` (no non-OSI Timescale License modules). Redis 8.2 is used under its **AGPLv3 option**, not the non-OSI Redis 7.4 licenses. MinIO is built from AGPLv3 source. No XTTS pretrained weights are distributed. Building/redistributing combined images and network-hosting modified AGPL components carries obligations; review them for your distribution.
