"""
Alert model.

Plain language: when someone scans a vehicle's QR code (e.g. it's
badly parked, blocking a driveway, or looks broken into), they pick
an issue type, describe what they see, and can optionally attach a
photo. Two independent AI-style checks then run on the report:

  1. Risk scoring -- how urgent is this? (ai_service.score_alert)
  2. Authenticity check -- does this look like a genuine report, or
     a prank/spam submission? (ai_service.assess_authenticity)

Both follow the same graceful-degradation pattern used throughout
this project: a real AI call is attempted only if configured, and a
transparent rule-based fallback always keeps the feature working.
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.db.session import Base


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)

    issue_type = Column(String, default="Other")  # e.g. Damage, Parking Issue, Emergency
    message = Column(Text, nullable=False)
    image_path = Column(String, nullable=True)  # web path to uploaded photo, if any
    reporter_contact = Column(String, nullable=True)  # optional, for follow-up

    risk_score = Column(Float, default=0.0)      # 0.0 (low) - 1.0 (critical)
    risk_label = Column(String, default="low")   # low / medium / high / critical
    matched_keywords = Column(String, default="")  # comma-separated, for transparency

    fraud_assessment = Column(String, default="needs_review")  # likely_genuine / needs_review / likely_prank
    fraud_reason = Column(Text, nullable=True)
    fraud_source = Column(String, default="rule_based")  # "ai" (real vision check ran) or "rule_based" (fallback)

    # Incident detection (Phase 4): links reports that likely describe
    # the same real-world event on the same vehicle.
    incident_id = Column(String, nullable=True, index=True)
    corroborating_reports = Column(Integer, default=1)

    # Evidence fusion (Phase 3): combined score across base risk,
    # authenticity, photo evidence, and corroboration.
    fused_risk_score = Column(Integer, nullable=True)   # 0-100
    fused_risk_label = Column(String, nullable=True)
    fusion_reasons = Column(Text, nullable=True)  # newline-joined, human-readable

    notified = Column(String, default="pending")  # pending / sent / failed / skipped

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    vehicle = relationship("Vehicle", back_populates="alerts")
