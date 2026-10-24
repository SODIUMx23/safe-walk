#!/usr/bin/env bash
# Authenticated standalone setup for a GitHub Codespace, not the production stack.
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${SAFEWALK_PYTHON:-python3}"
"$PYTHON" - <<'PY'
import sys
if sys.version_info[:2] != (3, 13):
    raise SystemExit('Use the included Python 3.13 devcontainer. In Codespaces, rebuild the container using .devcontainer/devcontainer.json.')
PY

missing=0
for binary in ffmpeg ffprobe espeak-ng tesseract; do
  command -v "$binary" >/dev/null || missing=1
done
if [[ "$missing" == 1 ]]; then
  if [[ "$EUID" == 0 ]]; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg espeak-ng tesseract-ocr tesseract-ocr-eng libglib2.0-0
  else
    sudo -n apt-get update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg espeak-ng tesseract-ocr tesseract-ocr-eng libglib2.0-0
  fi
fi

"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt -c requirements.lock
if [[ ! -f .env ]]; then
  .venv/bin/python -m backend.app.cli init-local
fi

# Never overwrite an existing key, turn off authentication, or attach to an
# existing production database merely to make the development setup succeed.
.venv/bin/python - <<'PY'
import os
from dotenv import dotenv_values
from backend.app.config import Settings
from backend.app.services.kinvoice import VoiceService
values = dotenv_values('.env')
for name in ('DEVICE_API_TOKEN', 'CAREGIVER_API_TOKEN', 'ARCHIVE_KEY'):
    if os.getenv(name + '_FILE') or (name in os.environ and os.environ[name] != values.get(name)):
        raise SystemExit('A secret environment override conflicts with this standalone .env profile. Preserve existing keys and resolve the configuration explicitly.')
s = Settings().load_secrets()
if s.production or any((s.database_url, s.redis_url, s.mqtt_host, s.minio_endpoint)):
    raise SystemExit('Existing settings select external/production services. Preserve that configuration; use a fresh Codespace/repository for this standalone profile.')
if min(len(s.device_api_token), len(s.caregiver_api_token)) < 32 or s.device_api_token == s.caregiver_api_token:
    raise SystemExit('Two distinct access tokens of at least 32 characters are required. Do not expose an unauthenticated Codespace.')
try:
    key = bytes.fromhex((values.get('ARCHIVE_KEY') or ''))
except ValueError:
    key = b''
if len(key) != 32:
    raise SystemExit('The existing .env needs its original 64-hex-character archive key. Do not regenerate keys for existing footage.')
VoiceService(s, None).ensure_default()
print('Prepared: authenticated backend, SQLite, encrypted filesystem storage, ffmpeg, OCR, and forty real eSpeak phrases.')
print('No PostgreSQL, MQTT, Redis or MinIO service is started in this Codespaces profile.')
PY
printf '\nSetup complete. Start with: bash scripts/start_codespace.sh\n'
