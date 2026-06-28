import json
import os
import math
import time
import random
import re
import requests
import shutil
import threading
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo
from typing import Optional
import subprocess

from fastapi import FastAPI, Request, Depends, HTTPException, Form, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from skyfield.api import load, wgs84

# ── Database & Models ─────────────────────────────────────────────────────────
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import func
from database import engine, get_db, SessionLocal
import models
from pulse_check import generate_talking_points
from audit_logging import log_security_event
from security_validation import SecurityValidationError, validate_allow_list, validate_int_field
from sentinel_queue import enqueue_sentinel_decision

# ── Authentication Middleware & Security ──────────────────────────────────────
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth, OAuthError

# ── App Core Initialization ───────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(SCRIPT_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()
@app.get("/health")
async def _health_check():
    return JSONResponse(status_code=200, content={"status": "ok"})
models.Base.metadata.create_all(bind=engine)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET_KEY", "demo_session_secret_key"))
app.mount("/static", StaticFiles(directory=os.path.join(SCRIPT_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(SCRIPT_DIR, "templates"))

# Auto-seed core tracker categories if missing
db_init = SessionLocal()
try:
    if db_init.query(models.Category).count() == 0:
        db_init.add_all([
            models.Category(name="Spiritual Formations"),
            models.Category(name="Household Labor"),
            models.Category(name="Self-Care"),
            models.Category(name="Neighborly Service")
        ])
        db_init.commit()
finally:
    db_init.close()

# ── Guild Tracker Configuration & Environment Constants ───────────────────────
LAT, LON  = 37.6393, -120.9969
LOCAL_TZ  = ZoneInfo("America/Los_Angeles")
CACHE_LIFESPAN = 900  # 15 minutes

# ── Astronomical Data Tracking ────────────────────────────────────────────────
try:
    planets = load(os.path.join(SCRIPT_DIR, 'de421.bsp'))
except Exception:
    planets = load('de421.bsp')

earth   = planets['earth']
sun     = planets['sun']
moon    = planets['moon']
mercury = planets['mercury']
venus   = planets['venus']
mars    = planets['mars']
jupiter = planets['jupiter barycenter']
saturn  = planets['saturn barycenter']
uranus  = planets['uranus barycenter']
neptune = planets['neptune barycenter']
pluto   = planets['pluto barycenter']

modesto = earth + wgs84.latlon(LAT, LON)
ts      = load.timescale()

# ── State Cache & Dictionaries ────────────────────────────────────────────────
STATE = {
    "last_fetch": 0,
    "weather":    {"temp_f": "--", "rh": "--", "wind_spd": "--", "gusts": "--", "uv": "--", "clouds": "--", "solar": "--"},
    "et":         {"rate": "--", "risk": "--", "precip_prob": "--", "soil": "--"},
    "astro":      {"sunrise": "--", "sunset": "--"}
}

WORDS = {
    "surrender": {
        "tone":    "Surrender — willing, open hands",
        "verse":   "Trust in the Lord with all your heart and lean not on your own understanding. — Proverbs 3:5",
        "line":    "You don't have to have it figured out today. You just have to show up.",
        "color":   "#9d7fc7",
    },
    "loyalty": {
        "tone":    "Loyalty — showing up again",
        "verse":   "Let us not grow weary of doing good, for in due season we will reap, if we do not give up. — Galatians 6:9",
        "line":    "Nobody sees the days you showed up anyway. God does. That's enough.",
        "color":   "#4a9ebb",
    },
    "joy": {
        "tone":    "Pure Joy — the reward is real",
        "verse":   "This is the day the Lord has made. Let us rejoice and be glad in it. — Psalm 118:24",
        "line":    "You made it to a full moon. That's not nothing. Take the win.",
        "color":   "#c8913a",
    },
    "determination": {
        "tone":    "Determination — press on",
        "verse":   "Not that I have already obtained this or am already perfect, but I press on to make it my own. — Philippians 3:12",
        "line":    "There is always a way forward as long as you get out of bed. That's the whole plan.",
        "color":   "#5aad7a",
    },
    "independence": {
        "tone":    "Servant Leader — you went through it for a reason",
        "verse":   "Whoever wants to be great among you must be your servant. — Matthew 20:26",
        "line":    "The things that nearly killed you are exactly what make you useful to someone else right now.",
        "color":   "#c47a7a",
    },
    "sunday": {
        "tone":    "Sunday — set apart",
        "verse":   "Come to me, all you who are weary and burdened, and I will give you rest. — Matthew 11:28",
        "line":    "One day a week you don't have to earn anything. Just receive it.",
        "color":   "#e8d5a3",
    },
}

REWARD_SCRIPTURES = [
    "Whatever you do, work heartily, as for the Lord and not for men. — Colossians 3:23",
    "Whether you eat or drink, or whatever you do, do all to the glory of God. — 1 Corinthians 10:31",
    "As each has received a gift, use it to serve one another, as good stewards of God's varied grace. — 1 Peter 4:10",
    "Let your light shine before others, so that they may see your good works and give glory to your Father who is in heaven. — Matthew 5:16",
    "Always abounding in the work of the Lord, knowing that in the Lord your labor is not in vain. — 1 Corinthians 15:58",
    "For we are his workmanship, created in Christ Jesus for good works, which God prepared beforehand. — Ephesians 2:10",
    "For everything there is a season, and a time for every matter under heaven. — Ecclesiastes 3:1"
]

# ── Background Engine Helper Functions ────────────────────────────────────────
def sync_weather():
    now = time.time()
    if now - STATE["last_fetch"] < CACHE_LIFESPAN:
        return
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_gusts_10m,uv_index,cloud_cover,shortwave_radiation"
            f"&hourly=et0_fao_evapotranspiration,precipitation_probability,soil_moisture_0_to_7cm"
            f"&daily=sunrise,sunset"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&forecast_days=1&timeformat=unixtime&timezone=America%2FLos_Angeles"
        )
        resp = requests.get(url, timeout=5).json()
        curr = resp.get("current", {})

        STATE["weather"].update({
            "temp_f":   curr.get("temperature_2m", "--"),
            "rh":       curr.get("relative_humidity_2m", "--"),
            "wind_spd": curr.get("wind_speed_10m", "--"),
            "gusts":    curr.get("wind_gusts_10m", "--"),
            "uv":       curr.get("uv_index", "--"),
            "clouds":   curr.get("cloud_cover", "--"),
            "solar":    curr.get("shortwave_radiation", "--")
        })

        hrly = resp.get("hourly", {})
        times = hrly.get("time", [])
        if times:
            idx = min(range(len(times)), key=lambda i: abs(times[i] - now))
            
            et_vals = hrly.get("et0_fao_evapotranspiration", [])
            et_val = et_vals[idx] if idx < len(et_vals) else None
            if et_val is not None:
                STATE["et"]["rate"] = f"{et_val:.3f} mm/hr"
                STATE["et"]["risk"] = "High — drink water" if et_val > 0.4 else "Moderate" if et_val > 0.2 else "Low"
            
            prob_vals = hrly.get("precipitation_probability", [])
            soil_vals = hrly.get("soil_moisture_0_to_7cm", [])
            STATE["et"]["precip_prob"] = f"{prob_vals[idx]}%" if idx < len(prob_vals) else "--"
            STATE["et"]["soil"] = f"{soil_vals[idx]} m³/m³" if idx < len(soil_vals) else "--"

        daily = resp.get("daily", {})
        sunrises = daily.get("sunrise", [])
        sunsets = daily.get("sunset", [])
        if sunrises and sunsets:
            sr_dt = datetime.fromtimestamp(sunrises[0], LOCAL_TZ)
            ss_dt = datetime.fromtimestamp(sunsets[0], LOCAL_TZ)
            STATE["astro"]["sunrise"] = sr_dt.strftime("%I:%M %p").lstrip("0")
            STATE["astro"]["sunset"] = ss_dt.strftime("%I:%M %p").lstrip("0")

    except Exception as e:
        print(f"Weather sync error: {e}")
    STATE["last_fetch"] = now


def get_trend_summary(db):
    now = datetime.now(LOCAL_TZ)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    prev_week_ago = now - timedelta(days=14)

    total_hours_week = db.query(func.sum(models.ShiftLog.hours)).filter(models.ShiftLog.created_at >= week_ago).scalar() or 0
    prev_week_hours = db.query(func.sum(models.ShiftLog.hours)).filter(
        models.ShiftLog.created_at >= prev_week_ago,
        models.ShiftLog.created_at < week_ago
    ).scalar() or 0
    shifts_week = db.query(func.count(models.ShiftLog.id)).filter(models.ShiftLog.created_at >= week_ago).scalar() or 0

    shift_days = {
        log.created_at.astimezone(LOCAL_TZ).date()
        for log in db.query(models.ShiftLog).filter(models.ShiftLog.created_at >= week_ago).all()
    }
    active_days = len(shift_days)
    avg_hours_per_shift = round(total_hours_week / shifts_week, 1) if shifts_week else 0
    week_change = total_hours_week - prev_week_hours

    top_tasks = [
        {"task": task, "count": count}
        for task, count in db.query(
            models.ShiftLog.task,
            func.count(models.ShiftLog.id).label("count")
        )
        .filter(models.ShiftLog.created_at >= month_ago)
        .group_by(models.ShiftLog.task)
        .order_by(desc("count"))
        .limit(3)
        .all()
    ]

    recent_strategies = db.query(models.StrategyLog).order_by(models.StrategyLog.created_at.desc()).limit(3).all()

    return {
        "total_hours_week": total_hours_week,
        "shifts_week": shifts_week,
        "active_days": active_days,
        "avg_hours_per_shift": avg_hours_per_shift,
        "week_change": week_change,
        "top_tasks": top_tasks,
        "recent_strategies": recent_strategies,
    }


def is_director(user):
    director_emails = os.getenv("DIRECTOR_EMAILS", "").split(",")
    normalized = {email.strip().lower() for email in director_emails if email.strip()}
    return user is not None and user.email.lower() in normalized


def get_user_role(user) -> str:
    if user is None:
        return "anonymous"
    explicit_role = getattr(user, "role", None)
    if explicit_role:
        return str(explicit_role).lower()
    if is_director(user):
        return "director"
    return "member"


def require_roles(*allowed_roles):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            db = kwargs.get("db")
            if db is None:
                for arg in args:
                    if isinstance(arg, Session):
                        db = arg
                        break

            user_id = request.session.get("user_id") if request is not None else None
            user = None
            if db is not None and user_id is not None:
                user = db.query(models.User).filter(models.User.id == user_id).first()

            effective_role = get_user_role(user)
            if user is None:
                log_security_event(
                    action_type="authorization_failure",
                    user_id=user_id,
                    request=request,
                    result="rbac_denied",
                    status_code=401,
                    severity="high",
                    detail={
                        "reason": "authentication_required",
                        "required_roles": list(allowed_roles),
                        "user_role": effective_role,
                        "resource": request.url.path if request else None,
                    },
                )
                raise HTTPException(status_code=401, detail="Unauthorized")

            if effective_role not in allowed_roles:
                log_security_event(
                    action_type="authorization_failure",
                    user_id=user.id,
                    request=request,
                    result="rbac_denied",
                    status_code=403,
                    severity="high",
                    detail={
                        "reason": "role_not_authorized",
                        "required_roles": list(allowed_roles),
                        "user_role": effective_role,
                        "resource": request.url.path if request else None,
                    },
                )
                raise HTTPException(status_code=403, detail="Forbidden")

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def get_current_user(request: Request, db: Session):
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_daily_word(illumination_pct, weekday):
    if weekday == 6:
        return WORDS["sunday"]
    if illumination_pct < 15:
        tone = "surrender"
    elif illumination_pct < 45:
        tone = "loyalty"
    elif illumination_pct < 70:
        tone = "determination"
    elif illumination_pct >= 70:
        tone = "joy"
    else:
        tone = "determination"
    if weekday in (4, 5) and tone not in ("surrender",):
        tone = "independence"
    return WORDS[tone]


def generate_director_insight(slot: str, db: Session):
    try:
        content = generate_talking_points(
            db_url=os.getenv("DATABASE_URL"),
            model=os.getenv("OLLAMA_MODEL", "CalderaAI:latest"),
        )
        if not content:
            raise RuntimeError("No content returned from the pulse-check flow")
        insight = models.DirectorInsight(slot=slot, content=content, summary=content[:180])
        db.add(insight)
        db.commit()
        return content
    except Exception as exc:
        print(f"Director insight generation failed for {slot}: {exc}")
        return None


def execute_sentinel_decree(ai_full_response: str, db_session):
    """
    Parses the mixed text and JSON payload from the custom Llama3 model.
    Queues a reviewable defensive action instead of applying firewall rules automatically.
    """
    json_match = re.search(r"\{.*\}", ai_full_response, re.DOTALL)
    if not json_match:
        print("❌ Sentinel Alert: No defensive JSON metadata found in AI response.")
        return

    try:
        decision = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        print("❌ Sentinel Alert: Found JSON block, but it was corrupted.")
        return

    talking_points = ai_full_response.split("```json")[0].strip()
    if not talking_points:
        talking_points = decision.get("sentinel_summary", "Threat intercepted by local AI.")

    if not decision.get("threat_detected"):
        return

    summary = decision.get("sentinel_summary", "Threat queued for review")
    enqueue_sentinel_decision(db_session, decision, summary, ai_full_response)

    security_alert = models.DirectorInsight(
        slot="security_alert",
        content=talking_points,
        summary=summary,
    )
    db_session.add(security_alert)
    db_session.commit()
    print("🛡️ Sentinel decision queued for Director review; no firewall changes were applied automatically.")


def schedule_director_insights():
    from sqlalchemy.orm import Session as SessionType
    db = SessionLocal()
    try:
        now = datetime.now(LOCAL_TZ)
        hour = now.hour
        if hour in (4, 7):
            slot = "morning" if hour == 4 else "evening"
            existing = db.query(models.DirectorInsight).filter(models.DirectorInsight.slot == slot).order_by(models.DirectorInsight.generated_at.desc()).first()
            should_generate = existing is None or (now - existing.generated_at.astimezone(LOCAL_TZ)).total_seconds() > 60 * 60 * 12
            if should_generate:
                generate_director_insight(slot, db)
        else:
            # Ensure the director page is never blank if insights haven't been generated yet.
            morning_existing = db.query(models.DirectorInsight).filter(models.DirectorInsight.slot == "morning").order_by(models.DirectorInsight.generated_at.desc()).first()
            evening_existing = db.query(models.DirectorInsight).filter(models.DirectorInsight.slot == "evening").order_by(models.DirectorInsight.generated_at.desc()).first()
            if morning_existing is None:
                generate_director_insight("morning", db)
            if evening_existing is None:
                generate_director_insight("evening", db)

        audit_log_path = os.path.join(SCRIPT_DIR, "audit.log")
        if os.path.exists(audit_log_path):
            with open(audit_log_path, "r", encoding="utf-8") as audit_handle:
                recent_lines = [line.strip() for line in audit_handle.readlines()[-30:] if line.strip()]
            if recent_lines:
                audit_context = "\n".join(recent_lines)
                ai_output = generate_talking_points(
                    db_url=os.getenv("DATABASE_URL"),
                    model=os.getenv("OLLAMA_MODEL", "CalderaAI:latest"),
                    audit_context=audit_context,
                )
                if ai_output:
                    execute_sentinel_decree(ai_output, db)
    finally:
        db.close()


def run_director_insight_scheduler():
    while True:
        try:
            schedule_director_insights()
        except Exception as exc:
            print(f"Director insight scheduler error: {exc}")
        time.sleep(60)


@app.on_event("startup")
async def start_director_insight_scheduler():
    if getattr(app.state, "director_scheduler_started", False):
        return
    app.state.director_scheduler_started = True
    thread = threading.Thread(target=run_director_insight_scheduler, daemon=True, name="director-insight-scheduler")
    thread.start()

# ── Google OAuth Registration ─────────────────────────────────────────────────
oauth = OAuth()
google_client_id = os.getenv("GOOGLE_CLIENT_ID", "demo-google-client-id")
google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "demo-google-client-secret")
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_id=google_client_id,
    client_secret=google_client_secret,
    client_kwargs={'scope': 'openid email profile'}
)


def is_demo_oauth_mode() -> bool:
    return google_client_id.startswith("demo-") or google_client_secret.startswith("demo-")

@app.exception_handler(SecurityValidationError)
async def security_validation_exception_handler(request: Request, exc: SecurityValidationError):
    log_security_event(
        action_type="validation_failure",
        request=request,
        result="rejected_input",
        status_code=400,
        severity="high",
        detail={"field": exc.field, "code": exc.code, "message": exc.message},
    )
    return JSONResponse(status_code=400, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    log_security_event(
        action_type="validation_failure",
        request=request,
        result="request_validation_failed",
        status_code=400,
        severity="high",
        detail={"errors": exc.errors()},
    )
    return JSONResponse(status_code=400, content={"detail": "Invalid request payload"})


# ── SECTION 1: Authentication Gateways ────────────────────────────────────────
@app.get("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    if is_demo_oauth_mode():
        demo_email = os.getenv("DEMO_USER_EMAIL", "director@example.com")
        demo_user = db.query(models.User).filter(models.User.email == demo_email).first()
        if not demo_user:
            demo_user = models.User(
                email=demo_email,
                google_id="demo-google-id",
                total_points=120,
                total_hours=48,
                target_trade="Demo Steward",
            )
            db.add(demo_user)
            db.commit()
            db.refresh(demo_user)

        request.session["user_id"] = demo_user.id
        log_security_event(
            action_type="authentication_attempt",
            request=request,
            result="demo_login",
            detail={"provider": "demo", "email": demo_email},
        )
        return RedirectResponse(url="/")

    redirect_uri = os.getenv("REDIRECT_URI")
    log_security_event(
        action_type="authentication_attempt",
        request=request,
        result="initiated",
        detail={"provider": "google", "redirect_uri": bool(redirect_uri)},
    )
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth")
async def auth(request: Request, db: Session = Depends(get_db)):
    if is_demo_oauth_mode():
        return RedirectResponse(url="/")

    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as error:
        log_security_event(
            action_type="authentication_failure",
            request=request,
            result="oauth_error",
            status_code=401,
            detail={"error": error.error},
        )
        return {"error": error.error}

    user_info = token.get('userinfo')
    if not user_info:
        log_security_event(
            action_type="authentication_failure",
            request=request,
            result="missing_user_info",
            status_code=401,
        )
        return {"error": "Failed to fetch user info"}

    email = user_info.get("email")
    google_id = user_info.get("sub")
    user = db.query(models.User).filter(models.User.email == email).first()
    
    if not user:
        user = models.User(email=email, google_id=google_id)
        db.add(user)
        db.commit()
        db.refresh(user)
        log_security_event(
            action_type="account_created",
            user_id=user.id,
            request=request,
            result="created",
            detail={"provider": "google"},
        )

        sf = db.query(models.Category).filter_by(name="Spiritual Formations").first()
        hl = db.query(models.Category).filter_by(name="Household Labor").first()
        sc = db.query(models.Category).filter_by(name="Self-Care").first()

        default_chores = [
            models.Chore(user_id=user.id, category_id=hl.id if hl else 2, title="Make the Bed", description="Reduces cognitive load and anxiety.", points=10),
            models.Chore(user_id=user.id, category_id=hl.id if hl else 2, title="Start the Coffee", description="Establishes positive morning micro-habits.", points=10),
            models.Chore(user_id=user.id, category_id=hl.id if hl else 2, title="Wash Dishes", description="A divine appointment for service.", points=25),
            models.Chore(user_id=user.id, category_id=sc.id if sc else 3, title="Sabbath Rest", description="A dedicated 24-hour period free from commerce.", points=50),
            models.Chore(user_id=user.id, category_id=sc.id if sc else 3, title="Physical Stewardship", description="Maintaining health to ensure longevity.", points=25),
            models.Chore(user_id=user.id, category_id=sf.id if sf else 1, title="Solitude and Silence", description="Withdrawing from digital noise.", points=25),
        ]
        db.add_all(default_chores)
        db.commit()

    request.session['user_id'] = user.id
    log_security_event(
        action_type="authentication_success",
        user_id=user.id,
        request=request,
        result="authenticated",
        status_code=302,
        detail={"provider": "google"},
    )
    return RedirectResponse(url="/")

@app.get("/logout")
async def logout(request: Request):
    user_id = request.session.get('user_id')
    request.session.pop('user_id', None)
    log_security_event(
        action_type="logout",
        user_id=user_id,
        request=request,
        result="signed_out",
        status_code=302,
    )
    return RedirectResponse(url="/")


# ── SECTION 2: Core Page Rendering Routes (GET) ───────────────────────────────
@app.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthenticated_access",
            status_code=302,
            resource="/",
        )
        return RedirectResponse(url="/login")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        request.session.pop('user_id', None)
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="stale_session",
            status_code=302,
            resource="/",
        )
        return RedirectResponse(url="/login")

    history = (
        db.query(models.ShiftLog)
        .filter(models.ShiftLog.user_id == user_id)
        .order_by(models.ShiftLog.created_at.desc())
        .all()
    )

    sync_weather()
    trend_summary = get_trend_summary(db)
    user_is_director = is_director(user)

    t = ts.now()
    alt_sun,  az_sun,  _ = modesto.at(t).observe(sun).apparent().altaz()
    alt_moon, az_moon, _ = modesto.at(t).observe(moon).apparent().altaz()
    
    phase_angle  = modesto.at(t).observe(moon).phase_angle(sun)
    illumination = 100.0 * (1.0 - math.cos(phase_angle.radians)) / 2.0

    def deg(val):
        return f"{val.degrees:.2f}°" if hasattr(val, 'degrees') else "--"

    def check_vis(body):
        alt, _, _ = modesto.at(t).observe(body).apparent().altaz()
        return "Visible in Sky" if alt.degrees > 0 else "Below Horizon"

    planetary_status = {
        "Mercury": check_vis(mercury),
        "Venus":   check_vis(venus),
        "Mars":    check_vis(mars),
        "Jupiter": check_vis(jupiter),
        "Saturn":  check_vis(saturn),
        "Uranus":  check_vis(uranus),
        "Neptune": check_vis(neptune),
        "Pluto":   check_vis(pluto),
    }

    now_local = datetime.now(LOCAL_TZ)
    weekday   = now_local.weekday()
    word      = get_daily_word(illumination, weekday)

    return templates.TemplateResponse("index.html", {
        "request":    request,
        "user_email": user.email,
        "user_is_director": user_is_director,
        "weather":    STATE["weather"],
        "et":         STATE["et"],
        "astro":      STATE["astro"],
        "sun_alt":    deg(alt_sun),
        "sun_az":     deg(az_sun),
        "moon_alt":   deg(alt_moon),
        "moon_phase": f"{illumination:.1f}% illuminated",
        "planets":    planetary_status,
        "word":       word,
        "today":      now_local.strftime("%A, %B %d"),
        "history":    history,
        "trend_summary": trend_summary,
    })

@app.get("/director-trends")
@require_roles("director")
async def director_trends(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url="/login")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not is_director(user):
        return RedirectResponse(url="/")

    trend_summary = get_trend_summary(db)
    morning_insight = db.query(models.DirectorInsight).filter(models.DirectorInsight.slot == "morning").order_by(models.DirectorInsight.generated_at.desc()).first()
    evening_insight = db.query(models.DirectorInsight).filter(models.DirectorInsight.slot == "evening").order_by(models.DirectorInsight.generated_at.desc()).first()
    pending_actions = db.query(models.SentinelActionQueue).filter(models.SentinelActionQueue.status == "pending").order_by(models.SentinelActionQueue.created_at.asc()).all()

    return templates.TemplateResponse("director_trends.html", {
        "request": request,
        "user_email": user.email,
        "trend_summary": trend_summary,
        "morning_insight": morning_insight,
        "evening_insight": evening_insight,
        "pending_actions": pending_actions,
    })

@app.post("/api/sentinel/apply/{action_id}")
@require_roles("director")
async def apply_sentinel_action(action_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    user = db.query(models.User).filter(models.User.id == user_id).first() if user_id else None
    if not is_director(user):
        log_security_event(
            action_type="authorization_failure",
            user_id=user_id,
            request=request,
            result="rbac_denied",
            status_code=403,
            severity="high",
        )
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    
    action = db.query(models.SentinelActionQueue).filter(models.SentinelActionQueue.id == action_id).first()
    if not action:
        return JSONResponse(status_code=404, content={"detail": "Action not found"})
    if action.action_type != "block" or not action.ip_address:
        return JSONResponse(status_code=400, content={"detail": "Only block actions can be applied"})
    
    try:
        subprocess.run(["sudo", "iptables", "-A", "INPUT", "-s", action.ip_address, "-j", "DROP"], check=True, timeout=5)
        action.status = "applied"
        action.reviewed_at = datetime.now(LOCAL_TZ)
        db.commit()
        log_security_event(
            action_type="firewall_block_applied",
            user_id=user_id,
            request=request,
            result="success",
            detail={"ip_address": action.ip_address, "action_id": action_id},
        )
        return JSONResponse(status_code=200, content={"status": "applied", "ip_address": action.ip_address})
    except subprocess.CalledProcessError as exc:
        log_security_event(
            action_type="firewall_block_failed",
            user_id=user_id,
            request=request,
            result="error",
            severity="high",
            detail={"error": str(exc), "ip_address": action.ip_address},
        )
        return JSONResponse(status_code=500, content={"detail": "Failed to apply firewall rule"})

@app.post("/api/sentinel/dismiss/{action_id}")
@require_roles("director")
async def dismiss_sentinel_action(action_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    user = db.query(models.User).filter(models.User.id == user_id).first() if user_id else None
    if not is_director(user):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    
    action = db.query(models.SentinelActionQueue).filter(models.SentinelActionQueue.id == action_id).first()
    if not action:
        return JSONResponse(status_code=404, content={"detail": "Action not found"})
    
    action.status = "dismissed"
    action.reviewed_at = datetime.now(LOCAL_TZ)
    db.commit()
    log_security_event(
        action_type="sentinel_action_dismissed",
        user_id=user_id,
        request=request,
        result="success",
        detail={"action_id": action_id},
    )
    return JSONResponse(status_code=200, content={"status": "dismissed"})

@app.get("/chores")
@require_roles("member", "director")
async def chores_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthenticated_access",
            status_code=302,
            resource="/chores",
        )
        return RedirectResponse(url="/login")

    today = datetime.now(LOCAL_TZ).date()
    active_chores = (
        db.query(models.Chore)
        .options(joinedload(models.Chore.category))
        .filter(models.Chore.user_id == user.id, models.Chore.is_active == True)
        .all()
    )

    grouped_chores = {}
    for chore in active_chores:
        cat_name = chore.category.name if chore.category else "Uncategorized"
        is_completed = any(
            log.completed_at.astimezone(LOCAL_TZ).date() == today 
            for log in chore.logs
        )
        chore_data = {
            "id": chore.id,
            "title": chore.title,
            "description": chore.description,
            "points": chore.points,
            "is_completed_today": is_completed
        }
        if cat_name not in grouped_chores:
            grouped_chores[cat_name] = []
        grouped_chores[cat_name].append(chore_data)

    log_security_event(
        action_type="data_access",
        user_id=user.id,
        request=request,
        result="loaded_chores",
        status_code=200,
        resource="/chores",
    )

    return templates.TemplateResponse("chores.html", {
        "request": request,
        "user_email": user.email,
        "user_is_director": is_director(user),
        "total_points": user.total_points,
        "grouped_chores": grouped_chores
    })

@app.get("/skills")
@require_roles("member", "director")
async def skills_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthenticated_access",
            status_code=302,
            resource="/skills",
        )
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("skills.html", {
        "request": request,
        "user_email": user.email,
        "user_is_director": is_director(user),
        "total_points": user.total_points
    })

@app.get("/tasks")
@require_roles("member", "director")
async def task_hub_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthenticated_access",
            status_code=302,
            resource="/tasks",
        )
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("tasks.html", {
        "request": request,
        "user_email": user.email,
        "user_is_director": is_director(user),
        "total_points": user.total_points,
        "target_trade": user.target_trade
    })

@app.get("/community")
@require_roles("member", "director")
async def community_board(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthenticated_access",
            status_code=302,
            resource="/community",
        )
    user_is_director = is_director(user)

    # 1. FETCH LEADERBOARD: Sort users by points (highest first)
    leaderboard_users = db.query(models.User).order_by(models.User.total_points.desc()).all()
    
    # 2. FETCH FORUM THREADS: Join ShiftLog and User explicitly to avoid relationship gaps
    results = (
        db.query(models.ShiftLog, models.User)
        .join(models.User, models.ShiftLog.user_id == models.User.id)
        .order_by(models.ShiftLog.id.desc())
        .all()
    )
    
    # Dynamically structure the payload so template properties evaluate natively
    recent_shifts = []
    for log, usr in results:
        log.user = usr
        recent_shifts.append(log)
    
    return templates.TemplateResponse("community.html", {
        "request": request,
        "user_is_director": user_is_director,
        "leaderboard": leaderboard_users,
        "shifts": recent_shifts
    })

@app.get("/live")
@require_roles("member", "director")
async def live_broadcast_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthenticated_access",
            status_code=302,
            resource="/live",
        )
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("live.html", {
        "request": request,
        "user_email": user.email,
        "user_is_director": is_director(user),
        "total_points": user.total_points
    })

@app.post("/api/generate-podcast-talking-points")
@require_roles("member", "director")
async def generate_podcast_talking_points(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    try:
        body = await request.json()
        topic = body.get("topic", "").strip()
        if not topic or len(topic) > 500:
            return JSONResponse(status_code=400, content={"error": "Invalid topic"})
        
        # Fetch leaderboard data (top 10 users by points for macro trend analysis)
        leaderboard = db.query(models.User).order_by(models.User.total_points.desc()).limit(10).all()
        leaderboard_text = "\n".join([f"  - {u.email}: {u.total_points} points | {u.total_hours}h logged | Trade: {u.target_trade or 'TBD'}" for u in leaderboard])
        
        # Fetch recent life strategies (last 8 for spiritual health context)
        strategies = db.query(models.StrategyLog).order_by(models.StrategyLog.created_at.desc()).limit(8).all()
        strategies_text = "\n".join([f"  - {s.user.email}: \"{s.content}\"" for s in strategies])
        
        # Calculate macro trends
        total_crew = db.query(models.User).count()
        total_hours_logged = db.query(func.sum(models.User.total_hours)).scalar() or 0
        avg_hours_per_person = (total_hours_logged / total_crew) if total_crew > 0 else 0
        
        prompt = f"""Director, generate 5 GRITTY BROADCAST TALKING POINTS for your live podcast.

EPISODE THEME: {topic}

MACRO CREW HEALTH SNAPSHOT:
- Total crew: {total_crew} men post-recovery
- Total hours logged (collective work): {total_hours_logged}h
- Avg hours per person: {avg_hours_per_person:.1f}h
- This is spiritual momentum. Track it.

TOP PERFORMERS (Spiritual Health Leaders):
{leaderboard_text}

CREW WISDOM SHARED (Strategy Board):
{strategies_text}

YOUR TASK:
1. Analyze the MACRO TRENDS. Who's grinding (high hours)? Who's growing in wisdom? This is spiritual health data.
2. Reference SPECIFIC crew members by name and their sacrifice (hours, consistency, growth).
3. LINK THE WATER INITIATIVE: Remind the crew that their work hours and sacrifice aren't just about survival—they're building the biotic pump. They're restoring the earth. They're modeling restoration for others.
4. Create 5 talking points that blend GRITTY REALITY (actual data) with SPIRITUAL HOPE (the Water Initiative mission).

Format: Numbered list (1-5), 1-2 sentences each. Street-level language. NO corporate speak. NO "program language". This is a CREW on a MISSION.

Remember: These men have FINISHED recovery. They're already productive. Now they're stewards of restoration. Make the talking points inspire them toward MACRO PURPOSE, not micro survival."""

        db_url = os.getenv("DATABASE_URL", "")
        model = os.getenv("OLLAMA_MODEL", "llama2")
        
        response_text = generate_talking_points(db_url=db_url, model=model, audit_context=prompt)
        
        if not response_text:
            return JSONResponse(status_code=503, content={"error": "Ollama unavailable. Check if it's running."})
        
        log_security_event(
            action_type="podcast_talking_points_generated",
            user_id=user.id,
            request=request,
            result="success",
            detail={"topic": topic, "crew_count": total_crew, "total_hours": total_hours_logged},
        )
        
        return JSONResponse(status_code=200, content={"talking_points": response_text})
    except Exception as e:
        log_security_event(
            action_type="api_error",
            user_id=user.id if user else None,
            request=request,
            result="error",
            severity="medium",
            detail={"error": str(e)},
        )
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/privacy")
async def privacy_decree(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


# ── SECTION 3: Action & Processing API Endpoints (POST) ───────────────────────
@app.exception_handler(SecurityValidationError)
async def security_validation_exception_handler(request: Request, exc: SecurityValidationError):
    log_security_event(
        action_type="validation_failure",
        request=request,
        result="rejected_input",
        status_code=400,
        severity="high",
        detail={"field": exc.field, "code": exc.code, "message": exc.message},
    )
    return JSONResponse(status_code=400, content={"detail": exc.message})


@app.post("/chores/")
async def create_chore(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthorized_create_chore",
            status_code=401,
            resource="/chores/",
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except ValueError as exc:
        raise SecurityValidationError("Invalid JSON body", field="body", code="invalid_json") from exc

    if not isinstance(payload, dict):
        raise SecurityValidationError("Payload must be an object", field="body", code="invalid_type")

    title = validate_allow_list(payload.get("title"), field_name="title", pattern=r"[A-Za-z0-9 _\-.,'()]{1,80}", max_length=80)
    description = payload.get("description")
    if description is not None:
        description = validate_allow_list(description, field_name="description", pattern=r"[A-Za-z0-9 _\-.,'()]{0,160}", max_length=160)
    category_id = validate_int_field(payload.get("category_id"), field_name="category_id", min_value=1, max_value=4)
    points = validate_int_field(payload.get("points"), field_name="points", min_value=10, max_value=50)

    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        log_security_event(
            action_type="authorization_failure",
            user_id=user_id,
            request=request,
            result="invalid_category",
            status_code=400,
            resource="/chores/",
            detail={"category_id": category_id},
        )
        raise HTTPException(status_code=400, detail="Invalid Category ID")

    new_chore = models.Chore(
        user_id=user_id,
        category_id=category_id,
        title=title,
        description=description,
        points=points
    )
    db.add(new_chore)
    db.commit()
    db.refresh(new_chore)
    log_security_event(
        action_type="state_change",
        user_id=user_id,
        request=request,
        result="created_chore",
        status_code=200,
        resource="/chores/",
        detail={"chore_id": new_chore.id, "points": new_chore.points},
    )
    return {"status": "success", "chore_id": new_chore.id}

@app.post("/chores/{chore_id}/check-in")
async def log_chore_completion(chore_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthorized_chore_checkin",
            status_code=401,
            resource=f"/chores/{chore_id}/check-in",
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    chore = db.query(models.Chore).filter(models.Chore.id == chore_id, models.Chore.user_id == user_id).first()
    
    if not chore or not user:
        log_security_event(
            action_type="authorization_failure",
            user_id=user_id,
            request=request,
            result="missing_chore_or_user",
            status_code=404,
            resource=f"/chores/{chore_id}/check-in",
        )
        raise HTTPException(status_code=404, detail="Chore or User not found")

    today = datetime.now(LOCAL_TZ).date()
    already_logged = db.query(models.ChoreLog).filter(
        models.ChoreLog.chore_id == chore.id
    ).filter(
        func.date(models.ChoreLog.completed_at) == today
    ).first()

    if already_logged:
        log_security_event(
            action_type="authorization_failure",
            user_id=user_id,
            request=request,
            result="duplicate_chore_checkin",
            status_code=400,
            resource=f"/chores/{chore_id}/check-in",
            detail={"chore_id": chore_id},
        )
        raise HTTPException(status_code=400, detail="Chore already logged today")

    new_log = models.ChoreLog(chore_id=chore.id)
    db.add(new_log)

    old_points = user.total_points
    user.total_points += chore.points
    earned_reward = (user.total_points // 20) > (old_points // 20)
    reward = random.choice(REWARD_SCRIPTURES) if earned_reward else None

    db.commit()
    log_security_event(
        action_type="state_change",
        user_id=user_id,
        request=request,
        result="completed_chore",
        status_code=200,
        resource=f"/chores/{chore_id}/check-in",
        detail={"chore_id": chore_id, "points": chore.points, "reward_earned": bool(reward)},
    )
    return {
        "status": "success", 
        "new_total": user.total_points,
        "reward_scripture": reward
    }

@app.post("/skills/set-trade")
async def set_target_trade(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthorized_trade_update",
            status_code=401,
            resource="/skills/set-trade",
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        log_security_event(
            action_type="authorization_failure",
            user_id=user_id,
            request=request,
            result="missing_user_for_trade_update",
            status_code=404,
            resource="/skills/set-trade",
        )
        raise HTTPException(status_code=404, detail="User not found")

    try:
        payload = await request.json()
    except ValueError as exc:
        raise SecurityValidationError("Invalid JSON body", field="body", code="invalid_json") from exc

    if not isinstance(payload, dict):
        raise SecurityValidationError("Payload must be an object", field="body", code="invalid_type")

    trade = validate_allow_list(payload.get("trade"), field_name="trade", pattern=r"[A-Za-z0-9 _\-/]{1,40}", max_length=40)
    user.target_trade = trade
    db.commit()
    log_security_event(
        action_type="state_change",
        user_id=user_id,
        request=request,
        result="updated_target_trade",
        status_code=200,
        resource="/skills/set-trade",
        detail={"trade": trade},
    )
    return {"status": "success", "message": f"Trade locked in as {trade}"}

@app.post("/tasks/submit")
async def submit_shift_log(
    request: Request,
    hours: str = Form(...),
    task: str = Form(...),
    engine_check: str = Form(...),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user_id = request.session.get('user_id')
    if not user_id:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthorized_shift_submit",
            status_code=401,
            resource="/tasks/submit",
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        log_security_event(
            action_type="authorization_failure",
            user_id=user_id,
            request=request,
            result="missing_user_for_shift_submit",
            status_code=404,
            resource="/tasks/submit",
        )
        raise HTTPException(status_code=404, detail="User not found")

    hours_value = validate_allow_list(hours, field_name="hours", pattern=r"(?:[1-9]|1[0-2])", max_length=2)
    hours_count = validate_int_field(int(hours_value), field_name="hours", min_value=1, max_value=12)
    task = validate_allow_list(task, field_name="task", pattern=r"[A-Za-z0-9 _\-.,'()]{1,80}", max_length=80)
    engine_check = validate_allow_list(engine_check, field_name="engine_check", pattern=r"[A-Za-z0-9 _\-.,'()]{1,80}", max_length=80)

    photo_relative_path = None
    if photo and photo.filename:
        photo_filename = f"photo_{user_id}_{int(time.time())}_{photo.filename}"
        photo_path = os.path.join(UPLOAD_DIR, photo_filename)
        with open(photo_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        photo_relative_path = f"/static/uploads/{photo_filename}"

    new_log = models.ShiftLog(
        user_id=user_id,
        hours=hours_count,
        task=task,
        engine_check=engine_check,
        photo_path=photo_relative_path
    )
    db.add(new_log)

    user.total_points += (hours_count * 10)
    user.total_hours += hours_count
    db.commit()
    log_security_event(
        action_type="state_change",
        user_id=user_id,
        request=request,
        result="submitted_shift_log",
        status_code=200,
        resource="/tasks/submit",
        detail={"hours": hours_count, "task": task, "photo_attached": photo is not None},
    )
    return {"status": "success"}

@app.post("/community/strategy/{shift_id}")
async def submit_strategy(shift_id: int, request: Request, content: str = Form(...), db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if shift_id <= 0:
        raise SecurityValidationError("shift_id out of allowed range", field="shift_id", code="invalid_range")
    content = validate_allow_list(content, field_name="content", pattern=r"[A-Za-z0-9 _\-.,'()]{1,400}", max_length=400)
    if not user_id:
        log_security_event(
            action_type="authorization_failure",
            request=request,
            result="unauthorized_strategy_submission",
            status_code=303,
            resource=f"/community/strategy/{shift_id}",
        )
        return RedirectResponse(url="/login", status_code=303)

    new_strategy = models.StrategyLog(
        shift_id=shift_id,
        user_id=user_id,
        content=content
    )
    db.add(new_strategy)
    db.commit()
    log_security_event(
        action_type="state_change",
        user_id=user_id,
        request=request,
        result="submitted_strategy",
        status_code=303,
        resource=f"/community/strategy/{shift_id}",
        detail={"shift_id": shift_id},
    )
    return RedirectResponse(url="/community", status_code=303)


# ── SECTION 4: Diagnostic Utilities ───────────────────────────────────────────
@app.get("/db-check")
@require_roles("director")
def check_database(db: Session = Depends(get_db)):
    user_count = db.query(models.User).count()
    return {"status": "Database online", "registered_users": user_count}