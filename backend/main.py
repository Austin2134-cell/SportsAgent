"""
main.py — FastAPI app entrypoint. Defines all API routes (cards, bets,
preferences, admin), CORS, and the APScheduler jobs (daily card generation,
weekly digest).
"""

import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

from database import db
from auth import get_current_user, get_admin_user
from services.grader import grade_all_pending
from services.agent_runner import run_card_for_user

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
TIMEZONE = os.getenv("TIMEZONE", "America/Denver")

scheduler = AsyncIOScheduler(timezone=TIMEZONE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(run_daily_cards, "cron", hour=9, minute=30, id="daily_cards")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="EdgeBet API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    invite_code: str


class PreferencesUpdate(BaseModel):
    sports: list[str] = ["MLB", "NBA", "NHL"]
    bet_types: list[str] = ["player_props", "straight"]
    risk_level: str = "MEDIUM"
    max_plays: int = 5
    unit_size: float = 50
    include_parlays: bool = False
    notification_email: Optional[str] = None


class GradeRequest(BaseModel):
    bet_id: str
    result: str
    units_result: float


@app.post("/auth/register")
async def register(body: RegisterRequest):
    code_result = db.table("invite_codes").select("*").eq("code", body.invite_code.upper()).single().execute()
    if not code_result.data:
        raise HTTPException(status_code=400, detail="Invalid invite code")
    code = code_result.data
    if not code["is_active"] or code["current_uses"] >= code["max_uses"]:
        raise HTTPException(status_code=400, detail="Invite code has expired")
    from supabase import create_client
    client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
    try:
        auth_response = client.auth.admin.create_user({
            "email": body.email,
            "password": body.password,
            "email_confirm": True,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    user_id = auth_response.user.id
    db.table("profiles").update({"full_name": body.full_name}).eq("id", user_id).execute()
    db.table("preferences").insert({"user_id": user_id}).execute()
    db.table("invite_codes").update({"current_uses": code["current_uses"] + 1}).eq("id", code["id"]).execute()
    return {"message": "Account created. Please sign in.", "user_id": user_id}


@app.get("/api/card/today")
async def get_today_card(user: dict = Depends(get_current_user)):
    today = date.today().isoformat()
    result = db.table("cards").select("*").eq("user_id", user["id"]).eq("date", today).execute()
    if not result.data:
        return {"card": None, "message": "No card generated yet today. Check back at 9:30 AM MT."}
    return {"card": result.data[0]}


@app.get("/api/card/{card_date}")
async def get_card_by_date(card_date: str, user: dict = Depends(get_current_user)):
    result = db.table("cards").select("*").eq("user_id", user["id"]).eq("date", card_date).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"card": result.data[0]}


@app.get("/api/bets")
async def get_bets(limit: int = 50, offset: int = 0, user: dict = Depends(get_current_user)):
    result = (
        db.table("bets").select("*").eq("user_id", user["id"])
        .order("date", desc=True).range(offset, offset + limit - 1).execute()
    )
    return {"bets": result.data or []}


@app.get("/api/record")
async def get_record(user: dict = Depends(get_current_user)):
    result = db.table("bets").select("*").eq("user_id", user["id"]).neq("result", "pending").execute()
    return _calculate_record(result.data or [])


@app.get("/api/record/daily")
async def get_daily_record(user: dict = Depends(get_current_user)):
    today = date.today().isoformat()
    result = db.table("bets").select("*").eq("user_id", user["id"]).eq("date", today).neq("result", "pending").execute()
    return _calculate_record(result.data or [])


@app.get("/api/preferences")
async def get_preferences(user: dict = Depends(get_current_user)):
    result = db.table("preferences").select("*").eq("user_id", user["id"]).execute()
    if not result.data:
        db.table("preferences").insert({"user_id": user["id"]}).execute()
        result = db.table("preferences").select("*").eq("user_id", user["id"]).execute()
    return {"preferences": result.data[0] if result.data else {}}


@app.put("/api/preferences")
async def update_preferences(body: PreferencesUpdate, user: dict = Depends(get_current_user)):
    data = body.model_dump()
    data["updated_at"] = datetime.now().isoformat()
    db.table("preferences").upsert({"user_id": user["id"], **data}, on_conflict="user_id").execute()
    return {"message": "Preferences updated"}


@app.get("/api/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    result = db.table("profiles").select("*").eq("id", user["id"]).single().execute()
    return {"profile": result.data}


@app.post("/api/admin/run-card")
async def admin_run_card(target_date: Optional[str] = None, user_id: Optional[str] = None, admin: dict = Depends(get_admin_user)):
    await run_daily_cards(target_date=target_date, specific_user_id=user_id)
    return {"message": "Card generation triggered"}


@app.post("/api/admin/grade")
async def admin_grade(body: GradeRequest, admin: dict = Depends(get_admin_user)):
    db.table("bets").update({"result": body.result.upper(), "units_result": body.units_result}).eq("id", body.bet_id).execute()
    return {"message": "Bet graded"}


@app.post("/api/admin/grade-all")
async def admin_grade_all(admin: dict = Depends(get_admin_user)):
    from services.grader import grade_all_pending
    return grade_all_pending(db)


@app.get("/api/admin/users")
async def admin_list_users(admin: dict = Depends(get_admin_user)):
    result = db.table("profiles").select("id, email, full_name, is_active, created_at").execute()
    return {"users": result.data or []}


@app.post("/api/admin/invite")
async def admin_create_invite(code: str, max_uses: int = 1, admin: dict = Depends(get_admin_user)):
    db.table("invite_codes").insert({"code": code.upper(), "max_uses": max_uses, "created_by": admin["id"]}).execute()
    return {"message": f"Invite code {code.upper()} created"}


@app.get("/api/admin/pending-bets")
async def admin_pending_bets(admin: dict = Depends(get_admin_user)):
    today = date.today().isoformat()
    result = db.table("bets").select("*, profiles(email)").eq("result", "pending").lt("date", today).order("date", desc=True).execute()
    return {"bets": result.data or []}


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


async def run_daily_cards(target_date: str = None, specific_user_id: str = None):
    today = target_date or date.today().isoformat()
    grade_result = grade_all_pending(db)
    print(f"[EdgeBet] Graded: {grade_result}")
    if specific_user_id:
        users_result = db.table("profiles").select("id").eq("id", specific_user_id).eq("is_active", True).execute()
    else:
        users_result = db.table("profiles").select("id").eq("is_active", True).execute()
    users = users_result.data or []
    for user_row in users:
        uid = user_row["id"]
        try:
            prefs_result = db.table("preferences").select("*").eq("user_id", uid).execute()
            prefs = prefs_result.data[0] if prefs_result.data else {}
            run_card_for_user(uid, prefs, target_date=today)
            print(f"[EdgeBet] Card generated for {uid}")
        except Exception as e:
            print(f"[EdgeBet] Error for {uid}: {e}")


def _calculate_record(bets: list) -> dict:
    wins = losses = pushes = 0
    net_units = 0.0
    wagered = 0.0
    for bet in bets:
        units = float(bet.get("units", 2))
        units_result = float(bet.get("units_result", 0))
        wagered += units
        if bet["result"] == "W":
            wins += 1
            net_units += units_result
        elif bet["result"] == "L":
            losses += 1
            net_units += units_result
        elif bet["result"] == "P":
            pushes += 1
    roi = (net_units / wagered * 100) if wagered > 0 else 0.0
    sign = "+" if net_units >= 0 else ""
    return {
        "wins": wins, "losses": losses, "pushes": pushes,
        "total": wins + losses + pushes,
        "net_units": round(net_units, 2),
        "wagered": round(wagered, 2),
        "roi_pct": round(roi, 1),
        "record_str": f"{wins}-{losses}-{pushes}",
        "units_str": f"{sign}{net_units:.1f}u",
    }
