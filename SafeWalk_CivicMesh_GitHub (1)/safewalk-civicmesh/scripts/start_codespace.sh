#!/usr/bin/env bash
# Codespaces lifecycle hook: start the real authenticated app, without Docker.
# --foreground is also available for supervised runs / process managers.
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "${1:-}" != "" && "${1:-}" != "--foreground" ]]; then
  echo 'Usage: bash scripts/start_codespace.sh [--foreground]' >&2; exit 2
fi
if [[ ! -x .venv/bin/python || ! -f .env ]]; then
  echo 'First run: bash scripts/setup_codespace.sh' >&2; exit 1
fi
mkdir -p data
exec 9>data/.codespace-start.lock
flock -x 9
PID_FILE="$ROOT/data/codespace-server.pid"
LOG_FILE="$ROOT/data/codespace-server.log"
if [[ -s "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if .venv/bin/python - "$old_pid" "$ROOT" <<'PY'
import os, sys
try:
    pid = int(sys.argv[1])
    command = open(f'/proc/{pid}/cmdline', 'rb').read()
    same = os.path.realpath(f'/proc/{pid}/cwd') == os.path.realpath(sys.argv[2])
    assert same and b'backend.app.main:app' in command
except (ValueError, OSError, AssertionError):
    raise SystemExit(1)
PY
  then
    echo 'SafeWalk is already running. Open port 8000 in the PORTS tab.'
    echo 'Run bash scripts/codespace_info.sh to display the addresses and private app credentials.'
    exit 0
  fi
fi

# Uvicorn reads .env for both the app settings and archive-key environment.
# Reject tokenless/external-service profiles before exposing a port.
.venv/bin/python - <<'PY'
import os
from dotenv import dotenv_values
from backend.app.config import Settings
values = dotenv_values('.env')
for name in ('DEVICE_API_TOKEN', 'CAREGIVER_API_TOKEN', 'ARCHIVE_KEY'):
    if os.getenv(name + '_FILE') or (name in os.environ and os.environ[name] != values.get(name)):
        raise SystemExit('A secret environment override conflicts with this standalone .env profile. Preserve existing keys and resolve the configuration explicitly.')
s = Settings().load_secrets()
if s.production or any((s.database_url, s.redis_url, s.mqtt_host, s.minio_endpoint)):
    raise SystemExit('This launcher is for the authenticated SQLite/filesystem Codespaces profile, not the production services.')
if min(len(s.device_api_token), len(s.caregiver_api_token)) < 32 or s.device_api_token == s.caregiver_api_token:
    raise SystemExit('Refusing to start without distinct, strong device/caregiver credentials.')
try:
    assert len(bytes.fromhex((values.get('ARCHIVE_KEY') or ''))) == 32
except (ValueError, AssertionError):
    raise SystemExit('Preserve and restore the original ARCHIVE_KEY in .env before starting.')
import socket
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(('0.0.0.0', 8000))
except OSError:
    raise SystemExit('Port 8000 is occupied by another process. Check it before starting another server.')
finally:
    sock.close()
PY

if [[ -n "${CODESPACE_NAME:-}" ]]; then
  domain="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  export WS_ALLOWED_ORIGINS="https://${CODESPACE_NAME}-8000.${domain}"
fi
server=(.venv/bin/python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --env-file .env --proxy-headers --no-access-log)
if [[ "${1:-}" == '--foreground' ]]; then
  printf '%s\n' "$$" > "$PID_FILE"
  flock -u 9
  exec 9>&-
  exec "${server[@]}"
fi

# Codespaces lifecycle hooks must return; the server remains in the Codespace.
# No credentials are printed into lifecycle logs or put into URLs.
nohup "${server[@]}" 9>&- </dev/null >"$LOG_FILE" 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" > "$PID_FILE"
flock -u 9
exec 9>&-

.venv/bin/python - "$server_pid" "$LOG_FILE" <<'PY'
import json, os, sys, time, urllib.request
pid, logfile = int(sys.argv[1]), sys.argv[2]
for attempt in range(120):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        raise SystemExit(f'Server exited. Read {logfile}; do not post credentials from .env.')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2) as response:
            health = json.load(response)
        with urllib.request.urlopen('http://127.0.0.1:8000/api/v1/config', timeout=2) as response:
            config = json.load(response)
        if health.get('status') == 'ready' and config.get('auth_required'):
            print('SafeWalk is ready at http://localhost:8000 — open forwarded port 8000 in the PORTS tab.')
            print('Keep the port Private. Its browser-facing app.github.dev address uses HTTPS.')
            print('Run bash scripts/codespace_info.sh to display your phone address and private app credentials.')
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit(f'Server did not become ready. Read {logfile}. Do not start duplicate servers.')
PY
