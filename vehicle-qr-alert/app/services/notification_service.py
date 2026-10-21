"""
Notification service.

Plain-language summary:
  In production this would call a paid provider (e.g. Twilio) to
  send an SMS or automated call to the vehicle owner when a
  high-risk alert comes in. That costs real money per message and
  needs a verified phone number/account, so it can't run for real
  in this environment.

  Instead, this is a "local mock transport": it logs what WOULD be
  sent, in the exact shape a real provider call would need, and
  returns a status. Swapping in a real provider later is just
  replacing the body of `send_sms()` -- the interface (function
  signature, return type) doesn't change, so nothing else in the
  app needs to be touched.
"""

from dataclasses import dataclass


@dataclass
class NotificationResult:
    status: str  # "sent" (mock) / "skipped" / "failed"
    channel: str
    detail: str


_SENT_LOG: list[dict] = []  # in-memory log, purely for demo/inspection


def send_sms(to_phone: str | None, message: str) -> NotificationResult:
    if not to_phone:
        return NotificationResult(status="skipped", channel="sms", detail="No phone number on file")

    # --- Mocked provider call ---
    # Real version:
    #   twilio_client.messages.create(to=to_phone, from_=FROM_NUMBER, body=message)
    _SENT_LOG.append({"to": to_phone, "message": message})
    return NotificationResult(
        status="sent",
        channel="sms",
        detail=f"(mock) SMS queued to {to_phone}: '{message}'",
    )


def notify_owner_of_alert(phone: str | None, vehicle_label: str, risk_label: str, message: str) -> NotificationResult:
    body = f"Alert on your {vehicle_label}: [{risk_label.upper()}] {message}"
    return send_sms(phone, body)


def get_sent_log() -> list[dict]:
    """For demo purposes: lets us prove notifications were 'sent'."""
    return _SENT_LOG
