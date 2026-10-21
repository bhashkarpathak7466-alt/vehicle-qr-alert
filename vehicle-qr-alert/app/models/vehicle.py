"""
Vehicle model.

Plain language: a Vehicle belongs to a User. Each vehicle gets a
QR code sticker. We never store the raw QR token in the database --
only its hash (see app/services/qr_service.py for why). This means
even if the database leaks, nobody can forge a working QR sticker
from the stolen data.
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.db.session import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    make = Column(String, nullable=False)
    model = Column(String, nullable=False)
    plate_number = Column(String, unique=True, index=True, nullable=False)
    color = Column(String, nullable=True)

    # We store only the SHA-256 hash of the QR token, never the raw token.
    qr_token_hash = Column(String, unique=True, index=True, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="vehicles")
    alerts = relationship("Alert", back_populates="vehicle", cascade="all, delete-orphan")
