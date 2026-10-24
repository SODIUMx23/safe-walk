"""Codespaces configuration safety: real app, no simulated replacement or tokenless server."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_codespace_uses_tested_python_and_automatic_native_start():
    config = json.loads((ROOT / '.devcontainer/devcontainer.json').read_text())
    assert config['image'] == 'mcr.microsoft.com/devcontainers/python:1-3.13-bookworm'
    assert config['remoteUser'] == 'vscode'
    assert config['postCreateCommand'] == 'bash scripts/setup_codespace.sh'
    assert config['postStartCommand'] == 'bash scripts/start_codespace.sh'
    assert config['waitFor'] == 'postCreateCommand'


def test_codespace_forwards_http_listener_not_mismatched_tls():
    config = json.loads((ROOT / '.devcontainer/devcontainer.json').read_text())
    assert config['forwardPorts'] == [8000]
    assert config['portsAttributes']['8000']['protocol'] == 'http'
    assert config['portsAttributes']['8000']['onAutoForward'] == 'openBrowser'


def test_codespace_setup_keeps_original_secrets_and_requires_authentication():
    setup = (ROOT / 'scripts/setup_codespace.sh').read_text()
    assert 'if [[ ! -f .env ]]' in setup
    assert 'backend.app.cli init-local' in setup
    assert 'len(s.device_api_token)' in setup and 's.device_api_token == s.caregiver_api_token' in setup
    assert 'VoiceService(s, None).ensure_default()' in setup
    assert 'rm -rf' not in setup and 'docker compose' not in setup


def test_codespace_start_uses_actual_app_and_exact_forwarded_origin():
    start = (ROOT / 'scripts/start_codespace.sh').read_text()
    assert 'uvicorn backend.app.main:app' in start
    assert '--host 0.0.0.0 --port 8000 --env-file .env' in start
    assert 'WS_ALLOWED_ORIGINS="https://${CODESPACE_NAME}-8000.${domain}"' in start
    assert "config.get('auth_required')" in start
    assert 'flock -x 9' in start
    assert "b'backend.app.main:app'" in start
    assert 'offline_mode' not in start and 'Quick_Demo' not in start


def test_codespace_info_never_prints_platform_credentials():
    info = (ROOT / 'scripts/codespace_info.sh').read_text()
    assert 'backend.app.cli credentials' in info
    assert 'GITHUB_TOKEN' not in info
    assert '/portal/' in info and '/specs/' in info
    assert '${CODESPACE_NAME}-8000.${domain}' in info
    assert 'Bearer' not in info
