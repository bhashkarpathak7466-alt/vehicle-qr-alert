"""
Incident detection service.

Plain-language summary:
If three different people scan the same car's QR code within a short
window and describe similar-sounding damage, that's very likely ONE
real-world incident being reported three times -- not three separate
problems. Grouping them together is valuable for two reasons:
  1. It tells the owner "3 people reported this" instead of showing
     three disconnected rows, which is both clearer and more
     trustworthy than a single anonymous report.
  2. That corroboration is itself evidence the report is genuine --
     it feeds into the risk-fusion step (see ai_service.fuse_evidence).

Implementation note (kept honest on purpose): this uses simple
keyword-overlap similarity (Jaccard similarity on significant words),
not embeddings or a trained semantic model. It's a legitimate,
explainable heuristic, but a production version comparing meaning
rather than word-overlap would use sentence embeddings + a vector
similarity search instead. That upgrade is a drop-in replacement for
`jaccard_similarity()` below -- the grouping logic around it doesn't
need to change.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

SIMILARITY_THRESHOLD = 0.22
SAME_ISSUE_TYPE_BONUS = 0.15
INCIDENT_WINDOW_HOURS = 6

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "to", "of", "in",
    "on", "at", "it", "its", "this", "that", "with", "for", "has", "have",
    "just", "very", "there", "here", "some", "looks", "looking", "see",
    "seeing", "please",
}


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """0.0 (nothing in common) to 1.0 (same significant words)."""
    words_a, words_b = _significant_words(text_a), _significant_words(text_b)
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


@dataclass
class IncidentMatch:
    incident_id: str
    corroborating_reports: int  # total reports in this incident, INCLUDING the new one
    is_new_incident: bool


def find_or_create_incident(db: Session, vehicle_id: int, message: str, issue_type: str) -> IncidentMatch:
    """
    Looks at recent alerts (within INCIDENT_WINDOW_HOURS) for the same
    vehicle and checks whether this new report is likely describing
    the same real-world event as one already on file.
    """
    from app.models.alert import Alert  # local import avoids a circular import

    cutoff = datetime.now(timezone.utc) - timedelta(hours=INCIDENT_WINDOW_HOURS)
    recent = (
        db.query(Alert)
        .filter(Alert.vehicle_id == vehicle_id, Alert.created_at >= cutoff)
        .all()
    )

    best_alert = None
    best_score = 0.0
    for alert in recent:
        score = jaccard_similarity(message, alert.message)
        if alert.issue_type == issue_type:
            score += SAME_ISSUE_TYPE_BONUS
        if score > best_score:
            best_score = score
            best_alert = alert

    if best_alert is not None and best_score >= SIMILARITY_THRESHOLD:
        incident_id = best_alert.incident_id or str(uuid.uuid4())
        prior_count = sum(1 for a in recent if a.incident_id == incident_id)
        # best_alert may not have had an incident_id yet if it predates
        # this feature being enabled -- backfill it so future matches work.
        if not best_alert.incident_id:
            best_alert.incident_id = incident_id
            db.add(best_alert)
            prior_count = 1
        return IncidentMatch(incident_id=incident_id, corroborating_reports=prior_count + 1, is_new_incident=False)

    return IncidentMatch(incident_id=str(uuid.uuid4()), corroborating_reports=1, is_new_incident=True)
