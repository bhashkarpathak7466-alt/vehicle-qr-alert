"""
End-to-end walkthrough test using FastAPI's TestClient.
This exercises the full flow in-process: register -> login ->
add vehicle (QR generated) -> report alert (risk scored + notified).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Fresh DB for a clean test run
db_path = "test_vehicle_qr_alert.db"
if os.path.exists(db_path):
    os.remove(db_path)
os.environ["DATABASE_URL"] = f"sqlite:///./{db_path}"

from fastapi.testclient import TestClient
from app.main import app
from app.services.notification_service import get_sent_log

client = TestClient(app)


def section(title):
    print(f"\n=== {title} ===")


section("1. Health check")
r = client.get("/health")
print(r.status_code, r.json())
assert r.status_code == 200

section("2. Register user")
r = client.post("/auth/register", json={
    "full_name": "Priya Sharma",
    "email": "priya@example.com",
    "phone": "+919812345678",
    "password": "secret123",
})
print(r.status_code, r.json())
assert r.status_code == 201

section("3. Login")
r = client.post("/auth/login", data={"username": "priya@example.com", "password": "secret123"})
token = r.json()["access_token"]
print(r.status_code, "token acquired:", token[:25] + "...")
assert r.status_code == 200
headers = {"Authorization": f"Bearer {token}"}

section("4. Add vehicle (generates QR code)")
r = client.post("/vehicles/", json={
    "make": "Maruti", "model": "Swift", "plate_number": "UK07AB1234", "color": "Red"
}, headers=headers)
vehicle = r.json()
print(r.status_code, {k: (v[:30] + "..." if k == "qr_code_base64_png" else v) for k, v in vehicle.items()})
assert r.status_code == 201
assert len(vehicle["qr_code_base64_png"]) > 100  # actual PNG data present

# In real life, the raw token would be embedded IN the QR image, given
# to the owner once, and printed as a sticker. For this test, we
# regenerate it by calling the same service the router used, to
# simulate "someone scanning the sticker and reporting an issue."
# (We can't decode our own QR PNG without an extra library, so instead
# we prove the flow using the hash-matching logic directly.)
from app.services.qr_service import generate_raw_token, hash_token
from app.db.session import SessionLocal
from app.models.vehicle import Vehicle

db = SessionLocal()
db_vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle["id"]).first()
# Simulate: overwrite with a known raw token so we can "scan" it in this test
known_raw_token = generate_raw_token()
db_vehicle.qr_token_hash = hash_token(known_raw_token)
db.commit()
db.close()

section("5a. Report LOW-risk, likely-prank alert (too short, no context)")
r = client.post("/alerts/report", data={
    "qr_token": known_raw_token,
    "issue_type": "Parking Issue",
    "message": "lol jk",
    "reporter_contact": "neighbor@example.com",
})
print(r.status_code, r.json())
assert r.status_code == 201
prank_alert = r.json()
assert prank_alert["fraud_assessment"] == "likely_prank"

section("5b. Report LOW-risk alert (parked wrong)")
r = client.post("/alerts/report", data={
    "qr_token": known_raw_token,
    "issue_type": "Parking Issue",
    "message": "Your car is parked wrong and lights on, please move it",
    "reporter_contact": "neighbor@example.com",
})
print(r.status_code, r.json())
assert r.status_code == 201
low_alert = r.json()
assert low_alert["risk_label"] in ("low", "medium")

section("5c. Report CRITICAL-risk alert (smashed window, theft)")
r = client.post("/alerts/report", data={
    "qr_token": known_raw_token,
    "issue_type": "Suspicious Activity / Theft",
    "message": "Break in! Window smashed, looks like theft in progress, someone trapped nearby",
    "reporter_contact": "passerby@example.com",
})
print(r.status_code, r.json())
assert r.status_code == 201
high_alert = r.json()
assert high_alert["risk_label"] in ("high", "critical")
assert high_alert["risk_score"] > low_alert["risk_score"]
assert high_alert["notified"] == "sent"
assert high_alert["fused_risk_score"] is not None
assert high_alert["corroborating_reports"] == 1  # first report of this incident

section("5c-dup. A SECOND person reports the same break-in (duplicate/incident detection)")
r = client.post("/alerts/report", data={
    "qr_token": known_raw_token,
    "issue_type": "Suspicious Activity / Theft",
    "message": "Window is smashed, looks like a break in happened, possible theft",
    "reporter_contact": "another_witness@example.com",
})
print(r.status_code, r.json())
assert r.status_code == 201
corroborating_alert = r.json()
# Should be recognized as the SAME incident as high_alert, not a new one.
assert corroborating_alert["incident_id"] == high_alert["incident_id"]
assert corroborating_alert["corroborating_reports"] == 2
# Two independent matching reports should push the fused score UP relative
# to a lone, unconfirmed report of the same severity.
assert corroborating_alert["fused_risk_score"] >= high_alert["fused_risk_score"]
assert "independent reports" in corroborating_alert["fusion_reasons"]

section("5d. Report with a photo attached (image upload)")
import io
from PIL import Image as PILImage
img_buf = io.BytesIO()
PILImage.new("RGB", (40, 40), color=(200, 30, 30)).save(img_buf, format="PNG")
img_buf.seek(0)
r = client.post(
    "/alerts/report",
    data={
        "qr_token": known_raw_token,
        "issue_type": "Vehicle Damage",
        "message": "Rear bumper is cracked, photo attached showing the damage clearly",
    },
    files={"image": ("damage.png", img_buf, "image/png")},
)
print(r.status_code, r.json())
assert r.status_code == 201
image_alert = r.json()
assert image_alert["image_path"] is not None and image_alert["image_path"].startswith("/static/uploads/")
assert image_alert["fraud_assessment"] == "likely_genuine"

# Confirm the uploaded file was actually saved to disk and is servable.
r_img = client.get(image_alert["image_path"])
assert r_img.status_code == 200

section("6. Owner views alerts, sorted by fused risk (highest first)")
r = client.get(f"/alerts/vehicle/{vehicle['id']}", headers=headers)
alerts_list = r.json()
print(r.status_code, [(a["fused_risk_label"], a["fused_risk_score"], a["corroborating_reports"]) for a in alerts_list])
assert r.status_code == 200
assert alerts_list[0]["fused_risk_score"] >= alerts_list[1]["fused_risk_score"]  # sorted desc

section("7. Mock notification log (proves 'SMS' was dispatched)")
print(get_sent_log())
assert len(get_sent_log()) >= 1

section("ALL CHECKS PASSED")
print("Full flow verified: register -> login -> add vehicle + QR -> report alert -> "
      "risk score + authenticity check -> incident/duplicate detection -> evidence fusion "
      "-> notify owner -> owner views sorted alerts")
