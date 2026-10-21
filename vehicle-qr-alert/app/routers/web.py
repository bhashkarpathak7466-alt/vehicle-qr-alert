"""
Page routes (serves HTML, not JSON).

Plain-language summary:
This router is what makes it a "web app" rather than just an API.
Every route here renders a template and returns HTML. The pages
then use JavaScript (see static/js/api.js) to call the JSON API
defined in app/routers/auth.py, vehicles.py, and alerts.py.

Keeping this cleanly separate from the API routers is the same
modular-monolith idea applied to the frontend: the API doesn't know
or care that a browser UI exists, and the UI is just another client
of the same API a mobile app or third party could also use.
"""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/dashboard")
def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/vehicles/add")
def add_vehicle_page(request: Request):
    return templates.TemplateResponse("add_vehicle.html", {"request": request})


@router.get("/report/{token}")
def report_page(request: Request, token: str):
    """
    Public page reached by scanning a vehicle's QR sticker. No login
    is required -- the QR token itself is what identifies the
    vehicle, in the same way a physical key identifies a lock.
    """
    return templates.TemplateResponse("report.html", {"request": request, "token": token})
