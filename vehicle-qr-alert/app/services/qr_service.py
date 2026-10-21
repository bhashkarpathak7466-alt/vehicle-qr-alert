"""
QR token service.

Plain-language summary of the design decision:

  When a vehicle is registered, we generate a random, unguessable
  token (like a long random password) and encode it into a QR code
  image that gets printed as a sticker for the car.

  We NEVER store that raw token in the database. Instead we store
  only its SHA-256 hash. This is the same pattern used for password
  storage, and for the same reason: if the database is ever leaked,
  an attacker cannot reconstruct the original QR tokens and print
  working duplicate stickers. When someone scans a sticker, we hash
  whatever they scanned and compare it against the stored hash --
  matching without ever needing the raw value to be recoverable.

  The raw token is shown to the vehicle owner exactly once (at
  registration time) as a QR image, and never again.
"""

import hashlib
import secrets
import base64
from io import BytesIO

import qrcode

from app.core.config import settings


def generate_raw_token() -> str:
    """Cryptographically random token, URL-safe, ~43 chars for 32 bytes."""
    return secrets.token_urlsafe(settings.QR_TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """One-way hash. Same input always produces same output,
    but the output cannot be reversed back into the input."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def build_qr_code_base64(raw_token: str) -> str:
    """
    Encodes a scannable link (not just the bare token) into a QR code
    image and returns it as a base64 PNG string, so it can be embedded
    directly in an API response or an <img> tag without needing
    separate file storage.

    Encoding a full URL (http://.../report/<token>) means a phone
    camera app can open the report page directly on scan, instead of
    just displaying raw text the user would have to copy manually.
    """
    scan_url = f"{settings.BASE_URL}/report/{raw_token}"
    img = qrcode.make(scan_url)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def verify_scanned_token(raw_token: str, stored_hash: str) -> bool:
    """Used when someone scans a sticker: hash what they scanned and
    compare against the stored hash. Constant-time compare avoids
    leaking timing information about partial matches."""
    return secrets.compare_digest(hash_token(raw_token), stored_hash)
