from pydantic import BaseModel

# Predefined issue categories shown as a dropdown on the report page.
# Kept as a plain list (not a DB-enforced enum) so adding a new
# category later is a one-line change, not a migration.
ISSUE_TYPES = [
    "Parking Issue",
    "Vehicle Damage",
    "Suspicious Activity / Theft",
    "Emergency / Accident",
    "Other",
]


class AlertOut(BaseModel):
    id: int
    vehicle_id: int
    issue_type: str
    message: str
    image_path: str | None = None

    # Base (message-only) risk signal
    risk_score: float
    risk_label: str
    matched_keywords: str

    # Authenticity / fraud check
    fraud_assessment: str
    fraud_reason: str | None = None
    fraud_source: str = "rule_based"  # "ai" if the real vision check ran, "rule_based" if it fell back

    # Incident detection -- other reports likely describing the same event
    incident_id: str | None = None
    corroborating_reports: int = 1

    # Evidence fusion -- combined, confidence-adjusted risk
    fused_risk_score: int | None = None
    fused_risk_label: str | None = None
    fusion_reasons: str | None = None

    notified: str

    class Config:
        from_attributes = True
