"""Factual SBAR handoff generation. This is not an accredited clinical tool."""
from __future__ import annotations

from datetime import datetime, timezone


def generate_sbar(incident: dict) -> dict:
    trigger = incident.get("trigger", "PANIC")
    simulated = bool(incident.get("simulation"))
    if trigger == "HIGH_G_IMPACT":
        situation = "Phone IMU reported a high-G impact. A pedestrian fall is suspected, NOT confirmed."
    elif trigger == "CAREGIVER_TEST":
        situation = "SIMULATION: caregiver initiated a test incident. No real injury was reported."
    else:
        situation = "The pedestrian activated the panic gesture. The reason and injury status are unknown."
    if simulated and not situation.startswith("SIMULATION"):
        situation = "SIMULATION: " + situation
    lat, lon = incident.get("latitude"), incident.get("longitude")
    accuracy = incident.get("accuracy_m")
    location = "Location unavailable."
    if lat is not None and lon is not None:
        uncertainty = f"; reported accuracy ±{accuracy:.0f} m" if accuracy is not None else "; accuracy unknown"
        location = f"Phone GPS {lat:.6f}, {lon:.6f}{uncertainty}."
    background = incident.get("medical_background") or "No medical history, medications, allergies, or baseline observations were provided."
    peak = incident.get("peak_g")
    assessment = [f"Phone-reported peak acceleration: {peak:.2f} g (not a clinical measurement)." if peak is not None
                  else "Peak phone acceleration unavailable.",
                  "Consciousness, breathing, pulse, blood pressure, pain, bleeding, and injury are NOT assessed.",
                  "Phone movement or a dropped phone can trigger this event; sensor data cannot diagnose trauma."]
    recommendation = ("Contact the pedestrian and designated caregiver; arrange assessment by a qualified responder. "
                      "If there is immediate danger or a suspected medical emergency in India, call 112 and follow the dispatcher's instructions. "
                      "This application has not called emergency services or a hospital. Do not use this note as a diagnosis or treatment order.")
    result = {
        "format": "SBAR", "version": "1.0", "clinical_status": "UNVALIDATED_MACHINE_GENERATED_HANDOFF",
        "requires_human_review": True, "generated_at": datetime.now(timezone.utc).isoformat(),
        "incident_id": incident.get("id", incident.get("event_id")), "simulation": simulated,
        "situation": situation + " " + location,
        "background": background,
        "assessment": " ".join(assessment),
        "recommendation": recommendation,
        "emergency_services_contacted": False,
    }
    result["text"] = "\n\n".join(f"{key.upper()}\n{result[key]}" for key in ("situation", "background", "assessment", "recommendation"))
    return result
