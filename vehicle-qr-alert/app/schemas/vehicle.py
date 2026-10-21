from pydantic import BaseModel


class VehicleCreate(BaseModel):
    make: str
    model: str
    plate_number: str
    color: str | None = None


class VehicleOut(BaseModel):
    id: int
    make: str
    model: str
    plate_number: str
    color: str | None = None

    class Config:
        from_attributes = True


class VehicleWithQR(VehicleOut):
    qr_code_base64_png: str  # shown once, at registration time only
