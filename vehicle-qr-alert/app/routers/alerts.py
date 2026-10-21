import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Form, UploadFile, File
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.core.deps import get_current_user
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.alert import Alert
from app.schemas.alert import AlertOut, ISSUE_TYPES
from app.services.qr_service import hash_token
from app.services.ai_service import score_alert, assess_authenticity, fuse_evidence
from app.services.incident_service import find_or_create_incident
from app.services.notification_service import notify_owner_of_alert, NotificationResult

router = APIRouter(prefix="/alerts", tags=["alerts"])

UPLOAD_DIR = "app/static/uploads"
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


@router.get("/issue-types", response_model=list[str])
def get_issue_types():
    """Lets the frontend fetch the dropdown options from one source of truth."""
    return ISSUE_TYPES


@router.post("/report", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def report_alert(
    qr_token: str = Form(...),
    issue_type: str = Form(...),
    message: str = Form(...),
    reporter_contact: str | None = Form(None),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """
    Public endpoint (no login required) -- this is what runs when
    someone scans a QR sticker on a car and reports something. We
    match the scanned token's hash against the stored hash to find
    the right vehicle, without ever storing the raw token ourselves.

    Pipeline for every report:
      1. Base risk score from the message text (score_alert)
      2. Authenticity check -- genuine, needs review, or likely prank
         (assess_authenticity) -- tries real vision AI, falls back to
         a rule-based heuristic
      3. Incident detection -- does this match another recent report
         on the same vehicle? (find_or_create_incident)
      4. Evidence fusion -- combine all of the above into one
         confidence-adjusted score with a visible reasons list
         (fuse_evidence)

    A "likely_prank" authenticity result never suppresses the alert --
    it still reaches the owner, just clearly labeled, so a real
    emergency is never silently dropped because of a false positive.
    """
    token_hash = hash_token(qr_token)
    vehicle = db.query(Vehicle).filter(Vehicle.qr_token_hash == token_hash).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Invalid or unrecognized QR code")

    if issue_type not in ISSUE_TYPES:
        raise HTTPException(status_code=400, detail=f"issue_type must be one of {ISSUE_TYPES}")

    image_path = None
    image_bytes = None
    image_media_type = None
    if image is not None and image.filename:
        if image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="Image must be JPEG, PNG, or WEBP")
        image_bytes = await image.read()
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail="Image must be under 5MB")
        image_media_type = image.content_type

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        ext = os.path.splitext(image.filename)[1].lower() or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
            f.write(image_bytes)
        image_path = f"/static/uploads/{filename}"

    # 1. Base risk from message text
    risk = score_alert(message)

    # 2. Authenticity check (real vision AI if configured, else heuristic)
    authenticity = assess_authenticity(
        message=message,
        issue_type=issue_type,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
    )

    # 3. Incident detection -- group with recent similar reports on this vehicle
    incident = find_or_create_incident(db, vehicle_id=vehicle.id, message=message, issue_type=issue_type)

    # 4. Evidence fusion -- combine everything into one score
    fused = fuse_evidence(
        base_risk=risk,
        authenticity=authenticity,
        corroborating_reports=incident.corroborating_reports,
        has_image=image_path is not None,
    )

    alert = Alert(
        vehicle_id=vehicle.id,
        issue_type=issue_type,
        message=message,
        image_path=image_path,
        reporter_contact=reporter_contact,
        risk_score=risk.score,
        risk_label=risk.label,
        matched_keywords=",".join(risk.matched_keywords),
        fraud_assessment=authenticity.label,
        fraud_reason=authenticity.reason,
        fraud_source=authenticity.source,
        incident_id=incident.incident_id,
        corroborating_reports=incident.corroborating_reports,
        fused_risk_score=fused.score,
        fused_risk_label=fused.label,
        fusion_reasons="\n".join(fused.reasons),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    owner = db.query(User).filter(User.id == vehicle.owner_id).first()

    if settings.NOTIFY_ONLY_ON_VERIFIED and authenticity.label != "likely_genuine":
        # Strict mode: only AI/rule-confirmed genuine reports reach the
        # owner. Everything else is suppressed on purpose -- it still
        # exists in the dashboard for the owner to review manually,
        # but no SMS/notification goes out for it.
        notif = NotificationResult(
            status="skipped",
            channel="sms",
            detail=(
                f"Suppressed: authenticity check returned '{authenticity.label}', "
                "not confirmed genuine (NOTIFY_ONLY_ON_VERIFIED=true)."
            ),
        )
    else:
        notif = notify_owner_of_alert(
            phone=owner.phone if owner else None,
            vehicle_label=f"{vehicle.make} {vehicle.model} ({vehicle.plate_number})",
            risk_label=fused.label,  # fused score is the more accurate signal
            message=message,
        )
    alert.notified = notif.status
    db.commit()
    db.refresh(alert)

    return alert


@router.get("/vehicle/{vehicle_id}", response_model=list[AlertOut])
def get_alerts_for_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id, Vehicle.owner_id == current_user.id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    return (
        db.query(Alert)
        .filter(Alert.vehicle_id == vehicle_id)
        .order_by(Alert.fused_risk_score.desc(), Alert.created_at.desc())
        .all()
    )
