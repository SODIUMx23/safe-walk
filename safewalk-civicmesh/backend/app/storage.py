"""PostGIS/Timescale persistence with an explicit SQLite development adapter.

Camera frames and raw enrollment samples never enter the database. All stored
incident clips are AES-256-GCM encrypted before reaching MinIO or local disk.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import Settings, secret
from .services.ai_spatial import haversine_m

log = logging.getLogger(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pg = bool(settings.database_url)
        self.lock = threading.RLock()
        self.pool = None
        self.sqlite = None

    def start(self):
        if self.pg:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            self.pool = ConnectionPool(self.settings.database_url, min_size=1, max_size=8,
                                       kwargs={"row_factory": dict_row}, timeout=10, open=True)
            self.pool.wait(timeout=30)
            with self.connection() as conn:
                # Extensions/schema are installed by infra/db/init.sql, not by a web-app superuser.
                conn.execute("SELECT 1 FROM hazards LIMIT 1")
        else:
            self.sqlite = sqlite3.connect(self.settings.data_dir / "safewalk.sqlite3", check_same_thread=False, timeout=10)
            self.sqlite.row_factory = sqlite3.Row
            self.sqlite.execute("PRAGMA journal_mode=WAL")
            self.sqlite.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry (received_at TEXT NOT NULL, device_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS telemetry_time ON telemetry(received_at);
            CREATE TABLE IF NOT EXISTS hazards (id TEXT PRIMARY KEY, kind TEXT NOT NULL, latitude REAL NOT NULL,
                longitude REAL NOT NULL, simulation INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS hazard_reports (hazard_id TEXT, device_id TEXT, PRIMARY KEY(hazard_id,device_id));
            CREATE TABLE IF NOT EXISTS tickets (id TEXT PRIMARY KEY, hazard_id TEXT UNIQUE, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS voices (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            self.sqlite.commit()

    @contextmanager
    def connection(self):
        if self.pg:
            with self.pool.connection() as conn:
                with conn.transaction():
                    yield conn
        else:
            with self.lock:
                try:
                    yield self.sqlite
                    self.sqlite.commit()
                except Exception:
                    self.sqlite.rollback()
                    raise

    def sql(self, text):
        return text if self.pg else text.replace("%s", "?")

    def ping(self):
        with self.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True

    def close(self):
        if self.pool:
            self.pool.close()
        if self.sqlite:
            self.sqlite.close()

    def record_telemetry(self, device_id: str, payload: dict):
        cleaned = {k: v for k, v in payload.items() if k not in {"frame", "medical_background"}}
        with self.connection() as conn:
            conn.execute(self.sql("INSERT INTO telemetry(received_at,device_id,payload) VALUES (%s,%s,%s)"),
                         (now_iso(), device_id, json.dumps(cleaned)))

    def _nearby(self, conn, lat, lon, radius, simulation, kind=None):
        if self.pg:
            query = """SELECT payload FROM hazards WHERE active=TRUE AND expires_at>NOW() AND simulation=%s
                AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)"""
            args = [simulation, lon, lat, radius]
            if kind:
                query += " AND kind=%s"
                args.append(kind)
            rows = conn.execute(query + " ORDER BY expires_at DESC LIMIT 1000", args).fetchall()
        else:
            query = "SELECT payload FROM hazards WHERE active=1 AND expires_at>? AND simulation=?"
            args = [now_iso(), int(simulation)]
            if kind:
                query += " AND kind=?"
                args.append(kind)
            rows = conn.execute(query + " ORDER BY expires_at DESC LIMIT 2000", args).fetchall()
        result = []
        for row in rows:
            data = json_value(row["payload"])
            distance = haversine_m(lat, lon, data["latitude"], data["longitude"])
            if distance <= radius:
                result.append({**data, "distance_m": round(distance, 2)})
        return sorted(result, key=lambda x: x["distance_m"])

    def nearby(self, lat, lon, radius=100, simulation=False):
        with self.connection() as conn:
            return self._nearby(conn, lat, lon, radius, simulation)

    def report_hazard(self, *, kind, lat, lon, device_id, label, confidence, simulation=False, source="visual_candidate"):
        with self.connection() as conn:
            if self.pg:
                # Serializes same-kind report merge, including the empty-result race.
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("hazard:" + kind,))
            matches = self._nearby(conn, lat, lon, 12, simulation, kind)
            existing = matches[0] if matches else None
            stamp = now_iso()
            expiry = (datetime.now(timezone.utc) + timedelta(hours=self.settings.hazard_ttl_hours)).isoformat()
            if existing:
                data = {k: v for k, v in existing.items() if k != "distance_m"}
            else:
                data = {"id": str(uuid4()), "kind": kind, "latitude": lat, "longitude": lon,
                        "label": label, "confidence": confidence, "simulation": simulation,
                        "verification": "UNVERIFIED_REPORT", "reported_at": stamp, "evidence_count": 0,
                        "geofence_m": 25, "warning_distance_m": 45, "source": source, "active": True}
                if self.pg:
                    conn.execute("""INSERT INTO hazards(id,kind,geom,simulation,active,expires_at,payload)
                        VALUES (%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s,TRUE,%s,%s)""",
                                 (data["id"], kind, lon, lat, simulation, expiry, json.dumps(data)))
                else:
                    conn.execute("INSERT INTO hazards(id,kind,latitude,longitude,simulation,active,expires_at,payload) VALUES (?,?,?,?,?,1,?,?)",
                                 (data["id"], kind, lat, lon, int(simulation), expiry, json.dumps(data)))
            added = conn.execute(self.sql("INSERT INTO hazard_reports(hazard_id,device_id) VALUES (%s,%s) ON CONFLICT DO NOTHING"),
                                 (data["id"], device_id)).rowcount
            data["evidence_count"] += int(added > 0)
            data["confidence"] = max(data["confidence"], confidence)
            data["last_observed_at"], data["expires_at"] = stamp, expiry
            conn.execute(self.sql("UPDATE hazards SET expires_at=%s,payload=%s WHERE id=%s"), (expiry, json.dumps(data), data["id"]))
            return data, existing is None

    def get_hazard(self, hazard_id):
        try:
            hazard_id = str(UUID(str(hazard_id)))
        except ValueError:
            return None
        with self.connection() as conn:
            row = conn.execute(self.sql("SELECT payload FROM hazards WHERE id=%s"), (hazard_id,)).fetchone()
            return json_value(row["payload"]) if row else None

    def resolve_hazard(self, hazard_id):
        try:
            hazard_id = str(UUID(str(hazard_id)))
        except ValueError:
            return None
        with self.connection() as conn:
            row = conn.execute(self.sql("SELECT payload FROM hazards WHERE id=%s"), (hazard_id,)).fetchone()
            if not row:
                return None
            data = json_value(row["payload"])
            data.update(active=False, resolved_at=now_iso())
            conn.execute(self.sql("UPDATE hazards SET active=%s,payload=%s WHERE id=%s"), (False, json.dumps(data), hazard_id))
            return data

    def save_document(self, table, doc_id, data, hazard_id=None):
        if table not in {"tickets", "incidents", "voices"}:
            raise ValueError("Invalid document collection")
        with self.connection() as conn:
            if table == "tickets":
                conn.execute(self.sql("INSERT INTO tickets(id,hazard_id,created_at,payload) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING"),
                             (doc_id, hazard_id, now_iso(), json.dumps(data)))
                row = conn.execute(self.sql("SELECT payload FROM tickets WHERE id=%s OR hazard_id=%s"), (doc_id, hazard_id)).fetchone()
            else:
                conn.execute(self.sql(f"INSERT INTO {table}(id,created_at,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING"),
                             (doc_id, now_iso(), json.dumps(data)))
                row = conn.execute(self.sql(f"SELECT payload FROM {table} WHERE id=%s"), (doc_id,)).fetchone()
            return json_value(row["payload"])

    def get_document(self, table, doc_id):
        if table not in {"tickets", "incidents", "voices"}:
            raise ValueError("Invalid document collection")
        if table != "incidents":
            try:
                doc_id = str(UUID(str(doc_id)))
            except ValueError:
                return None
        with self.connection() as conn:
            row = conn.execute(self.sql(f"SELECT payload FROM {table} WHERE id=%s"), (doc_id,)).fetchone()
            return json_value(row["payload"]) if row else None

    def update_document(self, table, doc_id, data):
        if table not in {"tickets", "incidents", "voices"}:
            raise ValueError("Invalid document collection")
        with self.connection() as conn:
            conn.execute(self.sql(f"UPDATE {table} SET payload=%s WHERE id=%s"), (json.dumps(data), doc_id))

    def documents(self, table, limit=100):
        if table not in {"tickets", "incidents", "voices"}:
            raise ValueError("Invalid document collection")
        with self.connection() as conn:
            return [json_value(row["payload"]) for row in conn.execute(
                self.sql(f"SELECT payload FROM {table} ORDER BY created_at DESC LIMIT %s"), (limit,)).fetchall()]

    def prune(self):
        telemetry_cutoff = (datetime.now(timezone.utc) - timedelta(days=self.settings.telemetry_retention_days)).isoformat()
        incident_cutoff = (datetime.now(timezone.utc) - timedelta(days=self.settings.incident_retention_days)).isoformat()
        with self.connection() as conn:
            conn.execute(self.sql("DELETE FROM telemetry WHERE received_at<%s"), (telemetry_cutoff,))
            old = conn.execute(self.sql("SELECT payload FROM incidents WHERE created_at<%s"), (incident_cutoff,)).fetchall()
            conn.execute(self.sql("DELETE FROM incidents WHERE created_at<%s"), (incident_cutoff,))
            # Expired reports cannot continue warning indefinitely.
            false_value = "FALSE" if self.pg else "0"
            conn.execute(self.sql(f"UPDATE hazards SET active={false_value} WHERE expires_at<%s"), (now_iso(),))
            return [json_value(row["payload"]).get("archive", {}).get("object_key") for row in old]


class BlobStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None
        self.directory = settings.data_dir / "archives"
        self.directory.mkdir(parents=True, exist_ok=True)
        raw_key = secret("ARCHIVE_KEY")
        if not raw_key:
            key_path = settings.data_dir / ".archive-key"
            if not key_path.exists():
                # Exclusive creation avoids workers racing to replace the encryption key.
                try:
                    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as file:
                        file.write(os.urandom(32).hex())
                except FileExistsError:
                    pass
            raw_key = key_path.read_text().strip()
        try:
            self.key = bytes.fromhex(raw_key)
        except ValueError as exc:
            raise ValueError("ARCHIVE_KEY must be 64 hexadecimal characters") from exc
        if len(self.key) != 32:
            raise ValueError("ARCHIVE_KEY must be exactly 32 bytes")
        self.cipher = AESGCM(self.key)

    def start(self):
        if self.settings.minio_endpoint:
            from minio import Minio
            from urllib3 import PoolManager, Timeout
            self.client = Minio(self.settings.minio_endpoint,
                                access_key=secret("MINIO_ROOT_USER", "safewalk"),
                                secret_key=secret("MINIO_ROOT_PASSWORD"), secure=self.settings.minio_secure,
                                http_client=PoolManager(timeout=Timeout(connect=3, read=15), retries=2))
            if not self.client.bucket_exists(self.settings.minio_bucket):
                try:
                    self.client.make_bucket(self.settings.minio_bucket)
                except Exception:
                    if not self.client.bucket_exists(self.settings.minio_bucket):
                        raise

    def ping(self):
        return self.client.bucket_exists(self.settings.minio_bucket) if self.client else self.directory.is_dir()

    def _local_path(self, key):
        path = (self.directory / key).resolve()
        if self.directory.resolve() not in path.parents:
            raise ValueError("Invalid object key")
        return path

    def put(self, incident_id: str, data: bytes):
        # User-supplied identifiers never become object paths.
        object_key = f"incidents/{hashlib.sha256(incident_id.encode()).hexdigest()}.mp4.enc"
        nonce = os.urandom(12)
        encrypted = b"SWCM1" + nonce + self.cipher.encrypt(nonce, data, object_key.encode())
        if self.client:
            self.client.put_object(self.settings.minio_bucket, object_key, io.BytesIO(encrypted), len(encrypted),
                                   content_type="application/octet-stream")
        else:
            path = self._local_path(object_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(encrypted)
        return {"status": "ARCHIVED", "object_key": object_key, "store": "minio" if self.client else "local-development",
                "encrypted": True, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "content_type": "video/mp4"}

    def get(self, key):
        if self.client:
            response = self.client.get_object(self.settings.minio_bucket, key)
            try:
                content = response.read()
            finally:
                response.close()
                response.release_conn()
        else:
            content = self._local_path(key).read_bytes()
        if content[:5] != b"SWCM1":
            raise ValueError("Unrecognized encrypted archive")
        return self.cipher.decrypt(content[5:17], content[17:], key.encode())

    def delete(self, key):
        if not key:
            return
        if self.client:
            self.client.remove_object(self.settings.minio_bucket, key)
        else:
            self._local_path(key).unlink(missing_ok=True)
