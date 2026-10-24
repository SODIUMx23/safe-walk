"""Local HTTPS configuration and source-package privacy regression checks."""
from pathlib import Path

import yaml

from scripts import package_source

ROOT = Path(__file__).resolve().parents[1]


def test_generated_phone_credentials_and_keys_are_never_packaged(tmp_path, monkeypatch):
    for name in ('certs/safewalk.pem', 'certs/safewalk-key.pem',
                 'phone-setup/SafeWalk-CA.crt', 'phone-setup/DEVICE_TOKEN.txt',
                 'phone-setup/PHONE_QR.png', '.env', '.env.private',
                 'data/archive.key', 'artifacts/recording.mp4'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'PRIVATE GENERATED DATA')
    for name in ('.env.example', 'scripts/start_mobile_demo.ps1',
                 'docker-compose.https.yml', 'infra/caddy/Caddyfile'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('public source', encoding='utf-8')
    monkeypatch.setattr(package_source, 'ROOT', tmp_path)
    names = {path.relative_to(tmp_path).as_posix() for path in package_source.source_files()}
    assert names == {'.env.example', 'scripts/start_mobile_demo.ps1',
                     'docker-compose.https.yml', 'infra/caddy/Caddyfile'}


def test_generated_phone_directories_ignored_by_git_and_docker():
    for filename in ('.gitignore', '.dockerignore'):
        entries = {line.strip().rstrip('/') for line in (ROOT / filename).read_text().splitlines()}
        assert {'certs', 'phone-setup'} <= entries


def test_https_proxy_mounts_certs_read_only_and_waits_for_backend():
    service = yaml.safe_load((ROOT / 'docker-compose.https.yml').read_text())['services']['https']
    assert service['image'].startswith('caddy:2')
    assert service['ports'] == ['8443:8443']
    assert './certs:/certs:ro' in service['volumes']
    assert './infra/caddy/Caddyfile:/etc/caddy/Caddyfile:ro' in service['volumes']
    assert service['depends_on']['backend']['condition'] == 'service_healthy'
    assert 'NET_BIND_SERVICE' in service['cap_add']
    assert service['security_opt'] == ['no-new-privileges:true']


def test_caddy_uses_local_tls_without_changing_websocket_host():
    config = (ROOT / 'infra/caddy/Caddyfile').read_text()
    directives = '\n'.join(line.split('#', 1)[0] for line in config.splitlines())
    assert 'tls /certs/safewalk.pem /certs/safewalk-key.pem' in directives
    assert 'reverse_proxy backend:8000' in directives
    assert 'auto_https off' in directives
    assert 'header_up Host' not in directives


def test_windows_launcher_requires_production_and_loopback_http():
    launcher = (ROOT / 'scripts/start_mobile_demo.ps1').read_text()
    assert '$env:BACKEND_BIND = "127.0.0.1"' in launcher
    assert '$env:APP_ENV = "production"' in launcher
    assert '"--force-recreate"' in launcher
    assert '-Profile Private -RemoteAddress LocalSubnet' in launcher
    assert 'rootCA-key.pem' not in '\n'.join(
        line for line in launcher.splitlines() if line.lstrip().startswith('Copy-Item'))
    base = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    assert base['services']['backend']['ports'] == ['${BACKEND_BIND:-0.0.0.0}:${BACKEND_PORT:-8000}:8000']
