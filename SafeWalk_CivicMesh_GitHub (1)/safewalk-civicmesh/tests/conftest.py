import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    for variable in ('DEVICE_API_TOKEN', 'CAREGIVER_API_TOKEN', 'ARCHIVE_KEY', 'POSTGRES_PASSWORD',
                     'REDIS_PASSWORD', 'DATABASE_URL', 'REDIS_URL', 'MQTT_HOST', 'MINIO_ENDPOINT'):
        monkeypatch.delenv(variable, raising=False)
        monkeypatch.delenv(variable + '_FILE', raising=False)
    settings = Settings(_env_file=None, data_dir=tmp_path, app_env='development', database_url='',
                        redis_url='', mqtt_host='', minio_endpoint='', device_api_token='', caregiver_api_token='')
    with TestClient(create_app(settings)) as connection:
        yield connection
