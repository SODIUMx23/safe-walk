"""Operator-only CLI. Credentials are never exposed by an HTTP endpoint."""
import argparse
import os
import secrets
from pathlib import Path

from .config import Settings, secret


def main():
    parser = argparse.ArgumentParser(description="SafeWalk local operator utilities")
    parser.add_argument("command", choices=["credentials", "init-local"])
    parser.add_argument("--all", action="store_true", help="Also display infrastructure credentials on this operator terminal")
    args = parser.parse_args()
    if args.command == "init-local":
        target = Path(".env")
        content = "APP_ENV=development\n" + "\n".join(f"{key}={secrets.token_hex(32)}" for key in ("DEVICE_API_TOKEN", "CAREGIVER_API_TOKEN", "ARCHIVE_KEY")) + "\n"
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as file:
                file.write(content)
        except FileExistsError:
            parser.error(".env already exists; refusing to overwrite credentials or the archive encryption key")
        print("Created private .env with distinct local-development credentials. Do not commit it.")
        return
    settings = Settings().load_secrets()
    print("Device token:    " + (settings.device_api_token or "NOT CONFIGURED (development only)"))
    print("Caregiver token: " + (settings.caregiver_api_token or "NOT CONFIGURED (development only)"))
    if args.all:
        for key in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "MQTT_PASSWORD"):
            print(f"{key}: {secret(key) or 'NOT CONFIGURED'}")
    print("Keep these credentials private. Never publish terminal output or place tokens in URLs.")


if __name__ == "__main__":
    main()
