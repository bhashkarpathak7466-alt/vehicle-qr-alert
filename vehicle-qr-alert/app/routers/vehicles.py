from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleOut, VehicleWithQR
from app.services.qr_service import generate_raw_token, hash_token, build_qr_code_base64

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.post("/", response_model=VehicleWithQR, status_code=status.HTTP_201_CREATED)
def add_vehicle(
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    raw_token = generate_raw_token()
    token_hash = hash_token(raw_token)

    vehicle = Vehicle(
        owner_id=current_user.id,
        make=payload.make,
        model=payload.model,
        plate_number=payload.plate_number,
        color=payload.color,
        qr_token_hash=token_hash,
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    qr_png_b64 = build_qr_code_base64(raw_token)

    return VehicleWithQR(
        id=vehicle.id,
        make=vehicle.make,
        model=vehicle.model,
        plate_number=vehicle.plate_number,
        color=vehicle.color,
        qr_code_base64_png=qr_png_b64,
    )


@router.get("/", response_model=list[VehicleOut])
def list_my_vehicles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Vehicle).filter(Vehicle.owner_id == current_user.id).all()
