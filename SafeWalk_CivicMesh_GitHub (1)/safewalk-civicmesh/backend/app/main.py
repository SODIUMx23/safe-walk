"""SafeWalk CivicMesh: open-source, experimental assistive telemetry hub."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import shutil
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .config import ROOT, Settings
from .middleware import GuardMiddleware
from .models import EmergencyMetadata, FrameRequest, Telemetry, TicketRequest
from .services.ai_spatial import calculate_clock_and_pan, classify_hazard_elevation, generate_kinvoice_speech, project_angles
from .services.civic import repair_ticket
from .services.hub import EventHub, MQTTBridge, RateLimiter
from .services.kinvoice import PRIMITIVES, TEXT_TO_TOKEN, VoiceService
from .services.media import normalize_blackbox
from .services.triage_agent import generate_sbar
from .services.vision import analyze_frame, decode_frame, inspect_rupee
from .storage import BlobStore, Repository, now_iso

log = logging.getLogger("safewalk")


def _valid_token(provided, expected):
    return isinstance(provided, str) and bool(expected) and hmac.compare_digest(provided, expected)


def _role(token, settings):
    if _valid_token(token, settings.caregiver_api_token):
        return "caregiver"
    if _valid_token(token, settings.device_api_token):
        return "device"
    if not settings.production and not (settings.device_api_token or settings.caregiver_api_token):
        return "development"
    return None


async def authenticate(request: Request):
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    role = _role(token, request.app.state.settings)
    if not role:
        raise HTTPException(401, "A valid bearer credential is required", headers={"WWW-Authenticate": "Bearer"})
    identity = token or (request.client.host if request.client else "local")
    # Navigation/audio traffic cannot exhaust the independent SOS allowance.
    if request.url.path == "/api/v1/emergency/sos":
        await request.app.state.limiter.check(identity, "sos", 12, 60)
    else:
        await request.app.state.limiter.check(identity)
    return role


async def caregiver(role=Depends(authenticate)):
    if role not in {"caregiver", "development"}:
        raise HTTPException(403, "Caregiver credential required")
    return role


async def read_bounded(file: UploadFile, limit: int):
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, "Uploaded file exceeds its size limit")
    return content


def _instruction(text, *, kind="INFO", pan=0.0, clock="12 o'clock", urgency="info", source="system", confidence=None):
    return {"id": str(uuid4()), "text": text, "token_id": TEXT_TO_TOKEN.get(text), "kind": kind,
            "pan": pan, "clock": clock, "urgency": urgency, "source": source, "confidence": confidence,
            "generated_at": now_iso(), "expires_in_s": 8}


async def _maintenance(app):
    ticks = 0
    while True:
        await asyncio.sleep(60)
        cutoff = time.time() - 300
        for device, event in list(app.state.hub.latest.items()):
            if event.get("received_unix", 0) < cutoff:
                app.state.hub.latest.pop(device, None)
        ticks += 1
        if ticks % 60 == 0:
            try:
                old_keys = await asyncio.to_thread(app.state.repo.prune)
                for key in old_keys:
                    await asyncio.to_thread(app.state.blobs.delete, key)
            except Exception:
                log.exception("Retention maintenance failed; operator review required")


def create_app(settings: Settings | None = None):
    configuration = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        cfg = configuration.load_secrets()
        app.state.settings = cfg
        app.state.repo = Repository(cfg)
        app.state.blobs = BlobStore(cfg)
        app.state.redis = None
        app.state.broker = MQTTBridge(cfg)
        app.state.hub = None
        maintenance = None
        try:
            await asyncio.to_thread(app.state.repo.start)
            await asyncio.to_thread(app.state.blobs.start)
            if cfg.redis_url:
                from redis.asyncio import Redis
                app.state.redis = Redis.from_url(cfg.redis_url, decode_responses=True,
                                                 socket_timeout=4, socket_connect_timeout=4)
                await app.state.redis.ping()
            app.state.hub = EventHub(app.state.redis)
            await app.state.hub.start()
            app.state.limiter = RateLimiter(app.state.redis)
            app.state.voice = VoiceService(cfg, app.state.repo)
            app.state.vision_slots = asyncio.Semaphore(2)
            app.state.devices = OrderedDict()
            app.state.broker.start()
            maintenance = asyncio.create_task(_maintenance(app))
            if not cfg.production:
                log.warning("DEVELOPMENT mode: SQLite/filesystem adapters may be active; never expose unauthenticated development mode publicly")
            yield
        finally:
            if maintenance:
                maintenance.cancel()
                await asyncio.gather(maintenance, return_exceptions=True)
            if app.state.hub:
                await app.state.hub.close()
            app.state.broker.close()
            if app.state.redis:
                await app.state.redis.aclose()
            app.state.repo.close()

    app = FastAPI(title="SafeWalk CivicMesh", version="1.0.0", lifespan=lifespan,
                  description="Experimental aid. Monocular camera cues are not sonar/depth measurements. Use a cane or guide.")
    app.add_middleware(GuardMiddleware, maximum=configuration.max_request_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/portal/")

    @app.get("/health/live")
    def live():
        return {"status": "alive", "application": "SafeWalk CivicMesh"}

    @app.get("/health/ready")
    async def ready():
        checks = {}
        for name, function in (("database", app.state.repo.ping), ("archive_store", app.state.blobs.ping)):
            try:
                checks[name] = await asyncio.to_thread(function)
            except Exception:
                checks[name] = False
        if app.state.redis:
            try:
                checks["redis"] = bool(await app.state.redis.ping())
            except Exception:
                checks["redis"] = False
        checks["mqtt"] = app.state.broker.connected if configuration.mqtt_host else not configuration.production
        good = all(checks.values())
        return JSONResponse({"status": "ready" if good else "degraded", "checks": checks,
                             "mode": configuration.app_env,
                             "capabilities": {"ffmpeg": bool(shutil.which("ffmpeg")), "currency_ocr": bool(shutil.which("tesseract")),
                                              "espeak_cache": bool(shutil.which("espeak-ng") or shutil.which("espeak")),
                                              "metric_sonar": False, "voice_cloning": False}}, status_code=200 if good else 503)

    @app.get("/api/v1/config")
    def public_config():
        return {"name": "SafeWalk CivicMesh", "mode": configuration.app_env,
                "auth_required": bool(configuration.device_api_token or configuration.caregiver_api_token),
                "telemetry_interval_ms": 800, "high_g_threshold": 3.5, "upward_sector_deg": 18,
                "head_height_band_cm": [140, 190], "minimum_reported_drop_cm": 40,
                "civic_geofence_m": 25, "civic_warning_distance_m": 45,
                "claims": {"metric_camera_depth": False, "phone_sonar": False, "clinical_accreditation": False,
                           "automatic_external_dispatch": False, "sub_40ms_guarantee": False},
                "safety_notice": "Experimental assistive cues only. Keep using a cane or guide. No scene-clear guarantee; no emergency service is called."}

    @app.post("/api/v1/telemetry/telemetry", dependencies=[Depends(authenticate)])
    async def telemetry(body: Telemetry):
        sent_unix = body.sent_at.timestamp()
        if abs(time.time() - sent_unix) > 120:
            raise HTTPException(422, "Stale or future telemetry: synchronize the phone clock (maximum skew 120 seconds)")
        states = app.state.devices
        state = states.get(body.device_id)
        if state is None:
            state = {"lock": asyncio.Lock(), "streak": 0, "kind": None, "last_sent": 0}
            states[body.device_id] = state
            while len(states) > 256:
                oldest = next(iter(states))
                if states[oldest]["lock"].locked():
                    raise HTTPException(503, "Device capacity reached; retry shortly")
                states.popitem(last=False)
        states.move_to_end(body.device_id)
        async with state["lock"]:
            if sent_unix <= state["last_sent"]:
                raise HTTPException(409, "Out-of-order telemetry ignored")
            state["last_sent"] = sent_unix
            vision = {"candidates": [], "quality": "NO_FRAME", "metric_depth_available": False,
                      "description": "No camera frame has been evaluated.", "head_observation": "UNAVAILABLE", "ground_observation": "UNAVAILABLE"}
            frame_data = None
            if body.frame:
                try:
                    async with app.state.vision_slots:
                        image, _ = await asyncio.to_thread(decode_frame, body.frame)
                        if body.vision_enabled:
                            vision = await asyncio.to_thread(analyze_frame, image, body.pitch, body.orientation_calibrated,
                                                             configuration.camera_vertical_fov_deg)
                    frame_data = body.frame if body.frame.startswith("data:") else "data:image/jpeg;base64," + body.frame
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
            candidates = []
            metric = body.range_source != "unavailable"
            boxes = [box.model_dump() for box in body.boxes]
            if metric and not boxes:
                boxes = [{"x_min": .4, "y_min": .3, "x_max": .6, "y_max": .7, "label": "reported range hazard", "confidence": .8, "distance_m": None}]
            for box in boxes:
                kind = classify_hazard_elevation(box, body.pitch, body.headspace_cm if metric else None, body.ground_cm if metric else None)
                candidates.append({**box, "kind": kind, "source": f"{body.range_source}_range_report" if metric else "client_report"})
            candidates.extend(vision["candidates"])
            ranking = {"GROUND_VOID": 3, "HEAD_LEVEL": 2, "PATH_OBSTACLE": 1}
            selected = max(candidates, key=lambda c: (ranking[c["kind"]], c["confidence"])) if candidates else None
            if selected:
                state["streak"] = state["streak"] + 1 if state["kind"] == selected["kind"] else 1
                state["kind"] = selected["kind"]
            else:
                state.update(kind=None, streak=0)
            instruction = None
            visual = selected is not None and selected["source"] == "visual_candidate"
            if selected and (not visual or state["streak"] >= 3):
                clock, pan = calculate_clock_and_pan(selected)
                urgency = "critical" if selected["kind"] in {"HEAD_LEVEL", "GROUND_VOID"} else "warning"
                text = generate_kinvoice_speech(selected["label"], selected["kind"], clock, selected.get("distance_m"), urgency)
                instruction = _instruction(text, kind=selected["kind"], pan=pan, clock=clock, urgency=urgency,
                                           source=selected["source"], confidence=selected["confidence"])
                instruction["angles"] = project_angles(selected, body.pitch, configuration.camera_horizontal_fov_deg,
                                                       configuration.camera_vertical_fov_deg)
            gps_good = body.latitude is not None and body.accuracy_m is not None and body.accuracy_m <= 25
            reported_hazard = None
            if selected and selected["kind"] in {"GROUND_VOID", "HEAD_LEVEL"} and gps_good and (not visual or state["streak"] >= 5):
                hazard, created = await asyncio.to_thread(app.state.repo.report_hazard, kind=selected["kind"],
                    lat=body.latitude, lon=body.longitude, device_id=body.device_id, label=selected["label"],
                    confidence=selected["confidence"], simulation=body.simulation, source=selected["source"])
                reported_hazard = hazard["id"]
                if created:
                    ticket = repair_ticket(latitude=body.latitude, longitude=body.longitude, kind=hazard["kind"],
                                           description=f"Unverified {selected['label']}; inspect on site. Source: {selected['source']}.",
                                           hazard_id=hazard["id"], simulation=body.simulation)
                    ticket = await asyncio.to_thread(app.state.repo.save_document, "tickets", ticket["id"], ticket, hazard["id"])
                    await app.state.hub.publish({"type": "hazard", "hazard": hazard, "ticket": ticket})
                    app.state.broker.publish("civicmesh/hazard", hazard)
            nearby = await asyncio.to_thread(app.state.repo.nearby, body.latitude, body.longitude, 60, body.simulation) if gps_good else []
            prewarnings = [hazard for hazard in nearby if hazard["distance_m"] <= hazard["warning_distance_m"]]
            if not instruction and prewarnings:
                instruction = _instruction(PRIMITIVES["mesh_warning"], kind="CIVIC_WARNING", urgency="warning", source="crowd_report")
                instruction["hazard_id"] = prewarnings[0]["id"]
                instruction["reported_distance_m"] = prewarnings[0]["distance_m"]
            fall_suspected = body.peak_g is not None and body.peak_g > 3.5
            if fall_suspected and instruction is None:
                instruction = _instruction(PRIMITIVES["impact"], kind="IMPACT", urgency="critical", source="phone_imu")
            summary = body.model_dump(mode="json", exclude={"frame", "boxes"})
            summary.update({"received_at": now_iso(), "vision": vision, "instruction": instruction,
                            "fall_suspected": fall_suspected, "reported_hazard_id": reported_hazard,
                            "headspace": {"value_cm": body.headspace_cm, "source": body.range_source, "meaning": "reported lower-edge height above pavement"},
                            "ground": {"value_cm": body.ground_cm, "source": body.range_source, "meaning": "reported drop depth below pavement"},
                            "nearby_hazards": prewarnings, "clear_path_certified": False})
            await asyncio.to_thread(app.state.repo.record_telemetry, body.device_id, summary)
            await app.state.hub.publish({"type": "telemetry", **summary, "frame": frame_data, "received_unix": time.time()})
            app.state.broker.publish("devices/telemetry", summary)
            return {**summary, "telemetry_interval_ms": 800, "gps_usable_for_mesh": gps_good}

    @app.get("/api/v1/civicmesh/hazards", dependencies=[Depends(authenticate)])
    async def hazards(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180),
                      radius_m: float = Query(default=100, gt=0, le=2000), simulation: bool = False):
        features = await asyncio.to_thread(app.state.repo.nearby, latitude, longitude, radius_m, simulation)
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "id": item["id"],
                  "geometry": {"type": "Point", "coordinates": [item["longitude"], item["latitude"]]}, "properties": item} for item in features]}

    @app.post("/api/v1/civicmesh/tickets/create", dependencies=[Depends(caregiver)], status_code=201)
    async def create_ticket(body: TicketRequest):
        hazard = await asyncio.to_thread(app.state.repo.get_hazard, body.hazard_id) if body.hazard_id else None
        if body.hazard_id and not hazard:
            raise HTTPException(404, "Hazard not found")
        lat, lon = (hazard["latitude"], hazard["longitude"]) if hazard else (body.latitude, body.longitude)
        ticket = repair_ticket(latitude=lat, longitude=lon, kind=hazard["kind"] if hazard else body.kind,
                               description=body.description, hazard_id=body.hazard_id,
                               simulation=hazard["simulation"] if hazard else body.simulation)
        saved = await asyncio.to_thread(app.state.repo.save_document, "tickets", ticket["id"], ticket, body.hazard_id)
        await app.state.hub.publish({"type": "ticket", "ticket": saved})
        return saved

    @app.get("/api/v1/civicmesh/tickets", dependencies=[Depends(caregiver)])
    async def ticket_queue():
        return {"type": "FeatureCollection", "features": await asyncio.to_thread(app.state.repo.documents, "tickets")}

    @app.get("/api/v1/civicmesh/tickets/{ticket_id}/geojson", dependencies=[Depends(caregiver)])
    async def ticket_export(ticket_id: str):
        item = await asyncio.to_thread(app.state.repo.get_document, "tickets", ticket_id)
        if not item:
            raise HTTPException(404, "Ticket not found")
        return Response(json.dumps(item, indent=2), media_type="application/geo+json",
                        headers={"Content-Disposition": f'attachment; filename="ticket-{item["id"]}.geojson"'})

    @app.post("/api/v1/civicmesh/hazards/{hazard_id}/resolve", dependencies=[Depends(caregiver)])
    async def resolve_hazard(hazard_id: str):
        item = await asyncio.to_thread(app.state.repo.resolve_hazard, hazard_id)
        if not item:
            raise HTTPException(404, "Hazard not found")
        await app.state.hub.publish({"type": "hazard_resolved", "hazard": item})
        return item

    @app.post("/api/v1/vision/describe", dependencies=[Depends(authenticate)])
    async def describe(body: FrameRequest):
        try:
            async with app.state.vision_slots:
                image, _ = await asyncio.to_thread(decode_frame, body.frame)
                result = await asyncio.to_thread(analyze_frame, image, body.pitch, False, configuration.camera_vertical_fov_deg)
            return {"speech": result["description"], "analysis": result, "model": "OpenCV deterministic baseline", "metric_depth_available": False}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/v1/rupeeguard/check", dependencies=[Depends(authenticate)])
    async def rupeeguard(body: FrameRequest):
        try:
            async with app.state.vision_slots:
                image, _ = await asyncio.to_thread(decode_frame, body.frame)
                return await asyncio.to_thread(inspect_rupee, image)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            log.warning("Currency/QR inspection failed: %s", type(exc).__name__)
            raise HTTPException(503, "QR/currency inspection unavailable; no transaction has been made") from exc

    @app.get("/api/v1/kinvoice/primitives", dependencies=[Depends(authenticate)])
    async def primitives(profile_id: str = "default"):
        try:
            return await asyncio.to_thread(app.state.voice.pack, profile_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/v1/kinvoice/primitives/{profile_id}/{token}.wav", dependencies=[Depends(authenticate)])
    async def primitive_audio(profile_id: str, token: str):
        path = await asyncio.to_thread(app.state.voice.audio_path, profile_id, token)
        if not path:
            raise HTTPException(404, "Audio primitive unavailable")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/kinvoice/enroll_voice", dependencies=[Depends(authenticate)], status_code=201)
    async def enroll_voice(audio: Annotated[UploadFile, File()], consent: Annotated[bool, Form()] = False):
        if not consent:
            raise HTTPException(422, "Explicit informed consent of the voice owner is required")
        await app.state.limiter.check("voice-enroll", "voice", 6, 600)
        content = await read_bounded(audio, 6 * 1024 * 1024)
        try:
            return await asyncio.to_thread(app.state.voice.enroll, content)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/v1/kinvoice/recordings", dependencies=[Depends(authenticate)])
    async def recordings(profile_id: Annotated[str, Form()], archive: Annotated[UploadFile, File()],
                         consent: Annotated[bool, Form()] = False):
        if not consent:
            raise HTTPException(422, "The speaker must consent to these recordings and this use")
        content = await read_bounded(archive, 30 * 1024 * 1024)
        try:
            return await asyncio.to_thread(app.state.voice.install_recordings, profile_id, content)
        except Exception as exc:
            raise HTTPException(422, str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "Invalid recording ZIP") from exc

    @app.post("/api/v1/emergency/sos", dependencies=[Depends(authenticate)], status_code=201)
    async def sos(metadata: Annotated[str, Form()], video_segments: Annotated[list[UploadFile] | None, File()] = None):
        try:
            incident_meta = EmergencyMetadata.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(422, json.loads(exc.json())) from exc
        previous = await asyncio.to_thread(app.state.repo.get_document, "incidents", incident_meta.event_id)
        if previous:
            return previous
        files = video_segments or []
        if len(files) > 8:
            raise HTTPException(413, "At most eight rolling video segments are accepted")
        contents, total = [], 0
        for file in files:
            value = await read_bounded(file, 5 * 1024 * 1024)
            total += len(value)
            if total > configuration.max_video_bytes:
                raise HTTPException(413, "Rolling buffer exceeds 18 MB")
            contents.append(value)
        marker = str(uuid4())
        incident = {**incident_meta.model_dump(mode="json"), "id": incident_meta.event_id,
                    "received_at": now_iso(), "processing_id": marker,
                    "archive": {"status": "PROCESSING" if contents else "NOT_PROVIDED"},
                    "emergency_services_contacted": False, "caregiver_hub_received": True}
        incident["sbar"] = generate_sbar(incident)
        saved = await asyncio.to_thread(app.state.repo.save_document, "incidents", incident["id"], incident)
        if saved.get("processing_id") != marker:
            return saved
        # Publish before transcoding so caregiver notification is not held up by a codec.
        await app.state.hub.publish({"type": "incident", "incident": incident})
        app.state.broker.publish("emergency/incident", incident)
        if contents:
            try:
                clip, media_info = await asyncio.to_thread(normalize_blackbox, contents, incident_meta.segment_durations_ms)
                incident["archive"] = {**await asyncio.to_thread(app.state.blobs.put, incident["id"], clip), **media_info}
            except Exception as exc:
                log.warning("Blackbox normalization/archive failed: %s", type(exc).__name__)
                incident["archive"] = {"status": "FAILED", "error": "Video could not be validated or archived; the incident and SBAR are saved."}
            await asyncio.to_thread(app.state.repo.update_document, "incidents", incident["id"], incident)
            await app.state.hub.publish({"type": "incident", "incident": incident})
        return incident

    @app.get("/api/v1/emergency/incidents", dependencies=[Depends(caregiver)])
    async def incidents():
        return {"incidents": await asyncio.to_thread(app.state.repo.documents, "incidents")}

    @app.get("/api/v1/emergency/incidents/{incident_id}/video", dependencies=[Depends(caregiver)])
    async def incident_video(incident_id: str):
        incident = await asyncio.to_thread(app.state.repo.get_document, "incidents", incident_id)
        archive = incident.get("archive", {}) if incident else {}
        if archive.get("status") != "ARCHIVED":
            raise HTTPException(404, "No playable archive is available for this incident")
        try:
            content = await asyncio.to_thread(app.state.blobs.get, archive["object_key"])
        except Exception as exc:
            raise HTTPException(503, "The encrypted archive is currently unavailable") from exc
        return Response(content, media_type="video/mp4", headers={"Content-Disposition": 'inline; filename="incident.mp4"'})

    @app.get("/api/v1/portal/state", dependencies=[Depends(caregiver)])
    async def portal_state():
        return {"devices": list(app.state.hub.latest.values()),
                "tickets": await asyncio.to_thread(app.state.repo.documents, "tickets"),
                "incidents": await asyncio.to_thread(app.state.repo.documents, "incidents"),
                "generated_at": now_iso()}

    @app.websocket("/api/v1/portal/live")
    async def portal_live(socket: WebSocket):
        origin = socket.headers.get("origin")
        if origin:
            allowed = [entry.strip() for entry in configuration.ws_allowed_origins.split(",") if entry.strip()]
            same = urlparse(origin).netloc == socket.headers.get("host")
            if (allowed and origin not in allowed) or (not allowed and not same):
                await socket.close(code=1008)
                return
        await socket.accept()
        queue = None
        tasks = set()
        try:
            first = await asyncio.wait_for(socket.receive_text(), timeout=5)
            if len(first) > 2048:
                await socket.close(code=1009)
                return
            auth = json.loads(first)
            if not isinstance(auth, dict) or _role(auth.get("token", ""), configuration) not in {"caregiver", "development"}:
                await socket.close(code=1008)
                return
            if len(app.state.hub.clients) >= 50:
                await socket.close(code=1013)
                return
            queue = asyncio.Queue(maxsize=12)
            app.state.hub.clients.add(queue)
            await socket.send_json({"type": "connected", "server_time": now_iso()})

            async def send_events():
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        event = {"type": "heartbeat", "server_time": now_iso()}
                    await socket.send_json(event)

            async def receive_events():
                while True:
                    text = await socket.receive_text()
                    if len(text) > 2048:
                        await socket.close(code=1009)
                        return
            tasks = {asyncio.create_task(send_events()), asyncio.create_task(receive_events())}
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (WebSocketDisconnect, asyncio.TimeoutError, json.JSONDecodeError, asyncio.CancelledError):
            pass
        finally:
            if queue is not None:
                app.state.hub.clients.discard(queue)
            for task in tasks:
                task.cancel()
            if tasks:
                # ASGI disconnect/shutdown cancellation must not strand sender tasks.
                from anyio import CancelScope
                with CancelScope(shield=True):
                    await asyncio.gather(*tasks, return_exceptions=True)

    app.mount("/specs", StaticFiles(directory=ROOT / "specs_app", html=True), name="specs")
    app.mount("/portal", StaticFiles(directory=ROOT / "caregiver_portal", html=True), name="portal")
    return app


app = create_app()
