# Validation record

Performed on **24 October 2026** in an isolated Linux/amd64 sandbox. All camera/GPS/impact and clinical tests used synthetic input. No real pedestrian, patient, voice identity, municipal report, or emergency dispatch was involved.

## Completed checks

| Check | Result |
|---|---|
| Python 3.13 backend/unit/API suite | **71 passed**, including bounded event queues, Redis recovery, five local-HTTPS/package-privacy checks, and five Codespaces configuration checks |
| Node 20 gesture/audio suite | **8 passed** |
| JavaScript parser checks (all frontend modules/service worker) | Passed |
| Docker Compose configuration | Base + optional local-HTTPS override validated with Compose 2.26.1 |
| Local HTTPS proxy | Actual Caddy **2.11.7** started healthy, local test CA chain verified without disabling client certificate checks; an untrusted client correctly rejected the certificate |
| Secure WebSocket proxy | Authenticated **WSS** connection preserved Origin/Host and received an actual Redis-fanned telemetry event through Caddy |
| Production stack through HTTPS | Readiness, RBAC, PostGIS early warning, GeoJSON, encrypted MinIO MP4 roundtrip, and human-review SBAR all passed through verified localhost TLS |
| Windows launcher validation | Parsed with PowerShell **7.6.8** on Linux; mocked Windows networking/mkcert/Compose exercised auto-IP, production/loopback flags, proxy recreation, SkipBuild, and rejection of loopback/nonlocal/URL input. **Not a real Windows run.** |
| Phone QR / package privacy | Launcher QR generated using actual OpenCV and independently decoded to the phone URL only, no token; generated certificates/phone credentials excluded by packager tests |
| Backend image | Built successfully from Python 3.13 Bookworm |
| TimescaleDB/PostGIS image | Built successfully from PostgreSQL 16 Bookworm, checksum-verified Timescale 2.31.0 with **APACHE_ONLY=1** |
| MinIO image | Built successfully from checksum-verified AGPL source, RELEASE.2025-10-15T17-29-55Z, Go 1.26 |
| Full Compose startup | All five long-running services reported **healthy**; secret initializer exited 0 |
| Actual PostgreSQL extensions | PostgreSQL **16.15**, TimescaleDB **2.31.0**, PostGIS **3.6.4** |
| Telemetry persistence | Actual Timescale hypertable insert/query path exercised with restricted application role |
| Redis / MQTT | Actual Redis **8.2.10** and Mosquitto **2.0.22** connected; authenticated WebSocket fanout via Redis and QoS-1 MQTT telemetry/privacy filtering exercised |
| CivicMesh A → B | Actual PostGIS-backed report + 35 m proximity warning before the 25 m zone; GeoJSON draft generated |
| Authorization | Missing token rejected; device token denied caregiver state; caregiver token accepted |
| Actual MinIO media path | Synthetic WebM → ffmpeg MP4 → AES-GCM → private MinIO → authenticated decrypt/download; playable MP4 verified |
| Desktop browser | Chromium, 1440 px layout, authenticated-event protocol in development mode, live simulated POV, User B selection retained across simulation ticks, GeoJSON injection, SBAR dialog, archived video playback |
| Mobile browser | Chromium mobile emulation, 390 px, fake camera/GPS, camera start/stop, neutral orientation calibration, **40 / 40 decoded audio primitives** |
| Mobile blackbox gestures | Actual two-second pointer hold → RAM buffer lock → upload → encrypted archive |
| Automatic impact path | Synthetic DeviceMotion >3.5 g → labelled simulated incident → archived video and SBAR |
| Responsive overflow | No horizontal overflow at tested desktop/mobile widths |
| Uncaught browser JavaScript errors | **0** |

Reproduce unit/API checks with `pytest` and `npm test`; see README for optional browser tooling. `scripts/browser_smoke.py` is deliberately restricted to an isolated tokenless development test server. `scripts/stack_smoke.py` exercises a disposable production stack using operator-supplied `DEVICE_API_TOKEN` and `CAREGIVER_API_TOKEN` environment variables without logging them.

## GitHub Codespaces profile — local validation, not a live cloud deployment

The added devcontainer uses `mcr.microsoft.com/devcontainers/python:1-3.13-bookworm`; its manifest was checked and returned HTTP 200. All three setup/start/info shell scripts passed Bash syntax validation. On Linux/Python 3.13, the setup installed its actual dependencies, generated distinct app credentials without overwriting existing secrets, and prepared forty eSpeak files.

Both the supervised foreground launcher and the lifecycle/background startup path were exercised; the background path reached authenticated readiness. Duplicate-start detection and forwarded-URL generation were checked. The operator-info helper printed application credentials only in captured private output and did not expose a test platform-token sentinel.

A browser test against the **authenticated real application** passed role checks, a WebSocket connection, `getUserMedia` with a synthetic camera, emulated orientation/GPS, forty decoded audio buffers, actual video upload/transcoding, AES-GCM local-filesystem archive retrieval/playback, and simulated factual SBAR. Uncaught JavaScript errors: **0**. These tests did not use or replace the app with the standalone offline HTML simulation.

**Not performed:** creating a real GitHub repository/Codespace, private-port GitHub sign-in on an Android phone, or testing GitHub's actual HTTPS/WebSocket forwarding and browser permission policies. This profile uses SQLite/encrypted filesystem storage, not the full production infrastructure. GitHub quotas/billing and provisioning time remain user/account dependent.

## Build issue found and corrected

The initial upstream `postgis/postgis:16-3.5` image referenced an expired Bullseye PGDG repository. The delivered database Dockerfile instead uses maintained `postgres:16-bookworm`, installs PostGIS, and compiles the Apache-only Timescale extension. The corrected image was built and used in the full-stack tests.

Timescale's optional background worker policies are disabled in this Apache-only build (`timescaledb.max_background_workers=0`); retention is handled by the app. This avoids invoking the extension's non-Apache internal job-history policy. Redis's host-level `vm.overcommit_memory` warning is an operator tuning item; it did not prevent the tested workload. The host Python test stack emitted an upstream Starlette/httpx deprecation warning; there were no test failures.

## Not validated / not claimed

- No clinical accreditation, medical-device certification, regulatory approval, diagnosis accuracy, emergency-response SLA, or real-world paramedic workflow validation.
- No outdoor detector benchmark, negative-obstacle sensitivity/recall, thin-wire detection guarantee, metric monocular depth validation, or safe-crossing guarantee.
- No smartphone sonar, actual cloned voice, guaranteed <40 ms audible latency, or individualized 3-D localization.
- No real Windows/Android installation or Android CA-installation/network/firewall test. PowerShell runtime checks used mocked Windows-only commands on Linux, not Windows PowerShell 5.1 or a physical phone.
- No real iOS/Safari device lab, Android hardware sensor calibration, mount-specific FOV measurement, screen-reader certification, battery-life benchmark, or GPS accuracy field study. Emulation is not real-device validation.
- No penetration test, independent supply-chain/security review, sustained multi-device load test, high-availability deployment, disaster-recovery drill, or multi-tenant identity system. TLS/WSS were validated locally on Linux with a test CA, not across a real laptop/phone Wi-Fi network or public production PKI.
- No actual PWD submission, municipal acknowledgement, ambulance call, caregiver response verification, or external emergency-services integration.

These boundaries are displayed/documented rather than hidden behind fabricated sensor values, simulated clinical claims, or silent success responses. Treat this as a tested, production-oriented **experimental implementation**, not a safety-certified deployment.
