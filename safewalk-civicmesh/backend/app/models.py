"""Strict API contracts: missing measurements stay missing, never zero-filled."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Box(Contract):
    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(ge=0, le=1)
    y_max: float = Field(ge=0, le=1)
    label: str = Field(default="obstacle", max_length=80)
    confidence: float = Field(default=0.5, ge=0, le=1)
    distance_m: float | None = Field(default=None, gt=0, le=100)

    @model_validator(mode="after")
    def ordered(self):
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("A bounding box must have positive width and height")
        return self


class Position(Contract):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=20000)

    @model_validator(mode="after")
    def pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together")
        return self


class Telemetry(Position):
    device_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    sent_at: datetime = Field(default_factory=utcnow)
    pitch: float = Field(default=0, ge=-90, le=90)
    roll: float = Field(default=0, ge=-180, le=180)
    heading_deg: float | None = Field(default=None, ge=0, le=360)
    orientation_calibrated: bool = False
    peak_g: float | None = Field(default=None, ge=0, le=100)
    headspace_cm: float | None = Field(default=None, ge=0, le=1000)
    ground_cm: float | None = Field(default=None, ge=0, le=1000)
    range_source: Literal["unavailable", "manual", "external_sensor", "simulation"] = "unavailable"
    boxes: list[Box] = Field(default_factory=list, max_length=12)
    frame: str | None = Field(default=None, max_length=420000)
    simulation: bool = False
    vision_enabled: bool = True
    rupee_guard: bool = False
    audio_cache_count: int = Field(default=0, ge=0, le=40)
    audio_latency_ms: float | None = Field(default=None, ge=0, le=30000)

    @model_validator(mode="after")
    def provenance(self):
        if self.sent_at.tzinfo is None:
            raise ValueError("sent_at must include a timezone")
        if self.range_source == "unavailable" and (self.headspace_cm is not None or self.ground_cm is not None):
            raise ValueError("Range inputs require explicit provenance; ground_cm means drop depth, not sonar range")
        if self.range_source == "simulation" and not self.simulation:
            raise ValueError("Simulated range inputs require simulation=true")
        return self


class FrameRequest(Contract):
    device_id: str = Field(default="scene-device", min_length=8, max_length=64)
    frame: str = Field(min_length=20, max_length=420000)
    pitch: float = Field(default=0, ge=-90, le=90)


class TicketRequest(Contract):
    hazard_id: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    kind: Literal["GROUND_VOID", "HEAD_LEVEL", "PATH_OBSTACLE"] = "GROUND_VOID"
    description: str = Field(default="Reported pedestrian hazard; on-site inspection required.", min_length=5, max_length=1000)
    simulation: bool = False

    @field_validator("hazard_id")
    @classmethod
    def uuid_hazard(cls, value):
        return str(UUID(value)) if value else value

    @model_validator(mode="after")
    def location(self):
        if not self.hazard_id and (self.latitude is None or self.longitude is None):
            raise ValueError("Provide hazard_id or both coordinates")
        return self


class EmergencyMetadata(Position):
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    device_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    trigger: Literal["PANIC", "HIGH_G_IMPACT", "CAREGIVER_TEST"]
    occurred_at: datetime = Field(default_factory=utcnow)
    peak_g: float | None = Field(default=None, ge=0, le=100)
    pitch: float | None = Field(default=None, ge=-180, le=180)
    roll: float | None = Field(default=None, ge=-180, le=180)
    medical_background: str | None = Field(default=None, max_length=1000)
    simulation: bool = False
    segment_durations_ms: list[float] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def consistent(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if self.trigger == "CAREGIVER_TEST" and not self.simulation:
            raise ValueError("Caregiver tests must be marked as simulation")
        if any(not 0 <= duration <= 15000 for duration in self.segment_durations_ms):
            raise ValueError("Invalid segment duration")
        return self
