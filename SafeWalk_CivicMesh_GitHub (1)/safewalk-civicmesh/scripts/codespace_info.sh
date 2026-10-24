#!/usr/bin/env bash
# Operator-only instructions. Never exposes a GitHub access token.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python || ! -f .env ]]; then
  echo 'Wait for setup to finish, or run: bash scripts/setup_codespace.sh' >&2; exit 1
fi
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  domain="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  base="https://${CODESPACE_NAME}-8000.${domain}"
  printf 'Laptop dashboard: %s/portal/\nPhone camera app: %s/specs/\n' "$base" "$base"
  echo 'Keep port 8000 Private; sign into your GitHub account in Android Chrome if asked.'
else
  echo 'Not in a Codespace: local dashboard http://localhost:8000/portal/ and Specs http://localhost:8000/specs/'
  echo 'For a phone, use the actual HTTPS forwarded address from your Codespace PORTS tab, not phone localhost.'
fi
printf '\nThese are SafeWalk app credentials, NOT GitHub credentials. Keep this terminal private.\n'
.venv/bin/python -m backend.app.cli credentials
printf '\nPaste the device token into phone Specs Settings; caregiver token into dashboard Access settings.\n'
