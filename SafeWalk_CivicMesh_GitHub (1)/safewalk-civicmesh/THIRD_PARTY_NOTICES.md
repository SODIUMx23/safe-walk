# Third-party components and license boundaries

SafeWalk application source is MIT. Dependencies and container software retain their own copyrights and licenses; the application license does not relicense them. No upstream source is copied into this repository except at image build time. Consult the LICENSE/COPYING files distributed inside each dependency/image for exact terms and version-specific notices.

| Component | License / source |
|---|---|
| FastAPI | MIT · https://github.com/fastapi/fastapi |
| Starlette / Uvicorn | BSD-3-Clause · https://github.com/Kludex/starlette · https://github.com/Kludex/uvicorn |
| Pydantic / pydantic-settings | MIT · https://github.com/pydantic/pydantic |
| NumPy | BSD-3-Clause · https://numpy.org/doc/stable/license.html |
| OpenCV | Apache-2.0 · https://github.com/opencv/opencv |
| PostgreSQL | PostgreSQL License · https://www.postgresql.org/about/licence/ |
| PostGIS | GPL-2.0-or-later · https://postgis.net |
| TimescaleDB 2.31.0 **APACHE_ONLY build** | Apache-2.0 portion ONLY · https://github.com/timescale/timescaledb/tree/2.31.0 |
| Eclipse Mosquitto | EPL-2.0 / EDL-1.0 · https://mosquitto.org/license/ |
| Paho MQTT Python | EPL-2.0 / EDL-1.0 · https://github.com/eclipse-paho/paho.mqtt.python |
| Redis 8.2 | **AGPLv3 option selected** from Redis's tri-license · https://github.com/redis/redis/tree/8.2 |
| Redis Python client | MIT · https://github.com/redis/redis-py |
| MinIO server, RELEASE.2025-10-15T17-29-55Z | AGPL-3.0 · https://github.com/minio/minio/tree/RELEASE.2025-10-15T17-29-55Z |
| MinIO Python SDK | Apache-2.0 · https://github.com/minio/minio-py |
| psycopg | LGPL-3.0 · https://www.psycopg.org |
| cryptography | Apache-2.0 / BSD-3-Clause · https://cryptography.io |
| FFmpeg Debian package / x264 | GPL and LGPL components; selected codec build is GPL-enabled · https://ffmpeg.org/legal.html |
| eSpeak NG | GPL-3.0-or-later · https://github.com/espeak-ng/espeak-ng |
| Tesseract OCR | Apache-2.0 · https://github.com/tesseract-ocr/tesseract |
| Python / CPython | PSF License · https://docs.python.org/3/license.html |
| Go toolchain | BSD-3-Clause · https://go.dev/LICENSE |
| Tini | MIT · https://github.com/krallin/tini |
| Optional Playwright test tooling | Apache-2.0 · https://github.com/microsoft/playwright |
| Caddy local HTTPS proxy | Apache-2.0 · https://github.com/caddyserver/caddy |
| mkcert local certificate helper | BSD-3-Clause · https://github.com/FiloSottile/mkcert |
| Docker Engine / Compose | Apache-2.0 · https://github.com/moby/moby · https://github.com/docker/compose |
| Debian / Alpine container packages | Mixed free/open-source licenses; retain package copyright files |

## Deliberate choices

- Redis **7.4** is not used: its RSAL/SSPL options are not OSI licenses. Redis >=8 offers an AGPL option.
- Timescale is compiled with `-DAPACHE_ONLY=1`. Do not replace it with a Timescale community/TSL image while claiming that all deployed server modules have OSI licenses. Compression/retention policy features requiring the Timescale License are not used.
- MinIO is built from a checksum-verified AGPL source release, not replaced by a proprietary S3 service. Comply with AGPL source/network obligations for any modifications.
- No XTTS-v2 pretrained model weights are bundled, downloaded, or falsely labelled open-source. The reference-vector simulation is real code, not a voice-cloning model.
- GitHub Codespaces is an optional proprietary development-hosting platform with GitHub account, quota and billing terms. It is not claimed to be open-source or required by the application. The same application remains runnable on your own Linux server; no GitHub-specific API is used for camera processing, storage or navigation.
- Docker Desktop is an optional Windows/macOS development host with separate Docker subscription/licensing terms; it is not claimed to be open-source. The delivered application/services run with open-source Docker Engine/Compose on Linux and do not depend on Desktop. Windows/Android are user-selected host platforms, not open-source application components.
- Web Audio, MediaRecorder, DeviceMotion, Geolocation, Pointer Events, and Web Speech are browser APIs. Browser/OS implementations and platform voices may be proprietary. Use self-hosted eSpeak or consented recordings for the speech pack; a browser TTS fallback is not an open-source-voice guarantee.

This is a dependency notice, not a legal compatibility determination. Review image redistribution, codec, attribution, medical/assistive-product, privacy, and AGPL obligations for your particular deployment. Keep all upstream notices when redistributing images or modified components.
