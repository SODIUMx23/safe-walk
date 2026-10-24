"""Local municipal repair drafts in interoperable GeoJSON (never fake submission)."""
from datetime import datetime, timezone
from uuid import uuid4


def repair_ticket(*, latitude, longitude, kind, description, hazard_id=None, simulation=False):
    in_vellore = 12.70 <= latitude <= 13.10 and 78.80 <= longitude <= 79.40
    stamp = datetime.now(timezone.utc).isoformat()
    identifier = str(uuid4())
    return {
        "type": "Feature", "id": identifier,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "ticket_id": identifier, "hazard_id": hazard_id, "kind": kind,
            "description": description, "created_at": stamp, "simulation": simulation,
            "intended_department": "Vellore Public Works Department (PWD)",
            "jurisdiction_checked": in_vellore,
            "status": "DEMO_NOT_SUBMITTED" if simulation else "LOCAL_DRAFT_NOT_SUBMITTED" if in_vellore else "REQUIRES_JURISDICTION_REVIEW",
            "submission_receipt": None, "human_inspection_required": True,
            "geofence_m": 25, "advance_warning_m": 20, "warning_distance_from_hazard_m": 45,
            "verification": "UNVERIFIED_REPORT", "priority": "INSPECTION_REQUESTED",
            "dispatch_note": "No municipal integration is configured; export this GeoJSON and submit through an authorized channel.",
        },
    }
