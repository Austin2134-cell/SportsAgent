"""
main.py — FastAPI app entrypoint. AgentEdge API: per-user agents, cards,
bets, preferences, admin, and scheduled market polling + agent scans.
"""

import asyncio
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
from agent.provision import provision_agent, get_agent_status
from agent.kernel import run_agent_scan
from agent.sports import get_all_supported_sports
from workers.market_poller import (
    poll_markets,
    poll_morning_toa_snapshot,
    ensure_wc_odds_before_card,
    run_all_agent_scans,
)
from esm.api_budget import POLL_INTERVAL_MINUTES, AGENT_SCAN_INTERVAL_MINUTES, budget_summary
from esm.odds_client import OddsClient

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
TIMEZONE = os.getenv("TIMEZONE", "America/Denver")

scheduler = AsyncIOScheduler(timezone=TIMEZONE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(_scheduled_morning_grade, "cron", hour=9, minute=15, id="morning_grade")
    scheduler.add_job(_scheduled_morning_toa, "cron", hour=8, minute=40, id="morning_toa_snapshot")
    scheduler.add_job(_scheduled_world_cup_card, "cron", hour=8, minute=50, id="world_cup_card")
    scheduler.add_job(_scheduled_morning_agents, "cron", hour=9, minute=30, id="morning_agent_run")
    scheduler.add_job(run_daily_cards, "cron", hour=9, minute=35, id="daily_cards")
    scheduler.add_job(_scheduled_sheets_sync, "cron", hour=10, minute=0, id="sheets_sync")
    scheduler.add_job(run_weekly_digest, "cron", day_of_week="mon", hour=8, minute=0, id="weekly_digest")
    scheduler.add_job(_scheduled_market_poll, "interval", minutes=POLL_INTERVAL_MINUTES, id="market_poll")
    scheduler.add_job(_scheduled_agent_scans, "interval", minutes=AGENT_SCAN_INTERVAL_MINUTES, id="agent_scans")
    scheduler.start()
    yield
    scheduler.shutdown()


async def _scheduled_world_cup_card():
    """Daily WC card — email + Supabase + Google Sheet (8:50 AM Mountain Time)."""
    if os.getenv("WC_CARD_ENABLED", "true").lower() in ("0", "false", "no"):
        print("[AgentEdge] World Cup card disabled (WC_CARD_ENABLED=false)")
        return
    try:
        from services.world_cup_card import run_world_cup_card

        odds_result = await asyncio.to_thread(ensure_wc_odds_before_card, db)
        print(f"[AgentEdge] Pre-WC odds check: {odds_result}")

        card = await asyncio.to_thread(
            run_world_cup_card,
            print_output=True,
            db=db,
        )
        print(
            f"[AgentEdge] World Cup card complete: "
            f"{card.get('date')} grade {card.get('slate_grade')} "
            f"({len(card.get('official_plays') or [])} plays)"
        )
    except Exception as e:
        print(f"[AgentEdge] World Cup card error: {e}")


async def _scheduled_morning_grade():
    """Grade yesterday's bets, refresh agent memory, sync sheet (9:15 AM Mountain Time)."""
    try:
        from agent.unit_tracker import today_mt, sync_units_at_risk

        grade_result = grade_all_pending(db)
        print(f"[AgentEdge] Morning grade ({grade_result.get('as_of')}): {grade_result}")
        today = today_mt()
        agents = db.table("agent_instances").select("user_id").eq("status", "active").execute()
        for row in agents.data or []:
            sync_units_at_risk(db, row["user_id"], today)
    except Exception as e:
        print(f"[AgentEdge] Morning grade error: {e}")


async def _scheduled_morning_toa():
    try:
        result = poll_morning_toa_snapshot(db)
        print(f"[AgentEdge] Morning TOA snapshot: {result}")
    except Exception as e:
        print(f"[AgentEdge] Morning TOA snapshot error: {e}")


async def _scheduled_morning_agents():
    """Run agent morning scans against fresh odds cache (grading runs at 9:15 AM)."""
    try:
        from agent.unit_tracker import today_mt, sync_units_at_risk

        today = today_mt()
        agents = db.table("agent_instances").select("user_id").eq("status", "active").execute()
        for row in agents.data or []:
            sync_units_at_risk(db, row["user_id"], today)
        run_all_agent_scans(db)
    except Exception as e:
        print(f"[AgentEdge] Morning agent run error: {e}")


async def _scheduled_market_poll():
    try:
        poll_markets(db)
    except Exception as e:
        print(f"[AgentEdge] Market poll error: {e}")


async def _scheduled_agent_scans():
    try:
        grade_all_pending(db)
        run_all_agent_scans(db)
    except Exception as e:
        print(f"[AgentEdge] Agent scan error: {e}")


async def _scheduled_sheets_sync():
    try:
        from services.sheets_sync import maybe_sync_sheets
        maybe_sync_sheets(db, reason="scheduled")
    except Exception as e:
        print(f"[AgentEdge] Sheets sync error: {e}")


app = FastAPI(title="AgentEdge API", version="2.0.0", lifespan=lifespan)

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
    sports: list[str] = ["MLB", "NBA", "NHL", "NFL", "WC"]
    bet_types: list[str] = ["player_props", "straight"]
    risk_level: str = "MEDIUM"
    max_plays: int = 5
    unit_size: Optional[float] = None
    include_parlays: bool = False
    notification_email: Optional[str] = None
    bankroll_starting: Optional[float] = None
    unit_pct: Optional[float] = None
    max_daily_pct: Optional[float] = None


class AgentSetupRequest(BaseModel):
    bankroll_starting: float = 1000
    unit_pct: float = 0.03
    max_daily_pct: float = 0.06
    sports: list[str] = ["MLB", "WC"]
    bet_types: list[str] = ["player_props", "straight"]
    risk_level: str = "MEDIUM"
    max_plays: int = 5
    include_parlays: bool = False
    notification_email: Optional[str] = None


class GradeRequest(BaseModel):
    bet_id: str
    result: str
    units_result: Optional[float] = None


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


@app.get("/api/sports")
async def list_sports():
    return {"sports": get_all_supported_sports()}


@app.get("/api/agent")
async def get_agent(user: dict = Depends(get_current_user)):
    prefs_result = db.table("preferences").select("*").eq("user_id", user["id"]).execute()
    prefs = prefs_result.data[0] if prefs_result.data else {}
    return get_agent_status(db, user["id"], prefs)


@app.post("/api/agent/setup")
async def setup_agent(body: AgentSetupRequest, user: dict = Depends(get_current_user)):
    if body.bankroll_starting < 100:
        raise HTTPException(status_code=400, detail="Minimum bankroll is $100")
    if body.unit_pct < 0.005 or body.unit_pct > 0.05:
        raise HTTPException(status_code=400, detail="Unit size must be 0.5%–5% of bankroll")
    result = provision_agent(db, user["id"], body.model_dump())
    return result


@app.get("/api/agent/feed")
async def get_agent_feed(limit: int = 50, user: dict = Depends(get_current_user)):
    from agent.memory_store import get_feed, get_hypotheses, get_beliefs
    return {
        "feed": get_feed(db, user["id"], limit),
        "hypotheses": get_hypotheses(db, user["id"]),
        "beliefs": get_beliefs(db, user["id"]),
    }


@app.get("/api/agent/memory")
async def get_agent_memory(user: dict = Depends(get_current_user)):
    from agent.calibration import get_memory_panel
    return get_memory_panel(db, user["id"])


@app.post("/api/agent/scan")
async def trigger_agent_scan(user: dict = Depends(get_current_user)):
    agent = db.table("agent_instances").select("status").eq("user_id", user["id"]).execute()
    if not agent.data or agent.data[0].get("status") != "active":
        raise HTTPException(status_code=400, detail="Agent not provisioned or not active")
    result = run_agent_scan(db, user["id"], trigger_type="manual_scan")
    return {"message": "Scan complete", "result": result}


@app.put("/api/agent/pause")
async def pause_agent(user: dict = Depends(get_current_user)):
    db.table("agent_instances").update({"status": "paused"}).eq("user_id", user["id"]).execute()
    return {"message": "Agent paused"}


@app.put("/api/agent/resume")
async def resume_agent(user: dict = Depends(get_current_user)):
    db.table("agent_instances").update({"status": "active"}).eq("user_id", user["id"]).execute()
    return {"message": "Agent resumed"}


@app.post("/api/admin/run-card")
async def admin_run_card(target_date: Optional[str] = None, user_id: Optional[str] = None, admin: dict = Depends(get_admin_user)):
    await run_daily_cards(target_date=target_date, specific_user_id=user_id)
    return {"message": "Card generation triggered"}


@app.post("/api/admin/run-wc-card")
async def admin_run_wc_card(
    target_date: Optional[str] = None,
    no_email: bool = False,
    admin: dict = Depends(get_admin_user),
):
    """Manually trigger the World Cup daily card (same job as 8:50 AM Railway schedule)."""
    from services.world_cup_card import run_world_cup_card

    odds_result = await asyncio.to_thread(ensure_wc_odds_before_card, db)
    card = await asyncio.to_thread(
        run_world_cup_card,
        target_date=target_date,
        send_email=not no_email,
        print_output=True,
        db=db,
    )
    return {
        "message": "World Cup card generated",
        "date": card.get("date"),
        "slate_grade": card.get("slate_grade"),
        "plays": len(card.get("official_plays") or []),
    }


@app.post("/api/admin/grade")
async def admin_grade(body: GradeRequest, admin: dict = Depends(get_admin_user)):
    from services.units import calculate_units_result
    from learning.memory import refresh_memory, refresh_platform_memory
    from agent.post_grade import apply_post_grade_effects, finalize_grade_batch

    bet_result = db.table("bets").select("*").eq("id", body.bet_id).single().execute()
    if not bet_result.data:
        raise HTTPException(status_code=404, detail="Bet not found")
    bet = bet_result.data
    units_result = body.units_result
    if units_result is None:
        units_result = calculate_units_result(
            body.result,
            float(bet.get("units") or 0),
            int(bet.get("odds") or -110),
        )
    result = body.result.upper()
    db.table("bets").update({
        "result": result,
        "units_result": units_result,
    }).eq("id", body.bet_id).execute()
    graded_bet = {**bet, "result": result, "units_result": units_result}
    apply_post_grade_effects(db, graded_bet, result, units_result)
    refresh_memory(db, bet["user_id"])
    refresh_platform_memory(db)
    finalize_grade_batch(db, {bet["user_id"]})
    return {"message": "Bet graded", "units_result": units_result}


@app.post("/api/admin/weekly-digest")
async def admin_weekly_digest(admin: dict = Depends(get_admin_user)):
    summaries = await run_weekly_digest()
    return {"message": "Weekly digest complete", "users_processed": len(summaries), "summaries": summaries}


@app.post("/api/admin/grade-all")
async def admin_grade_all(admin: dict = Depends(get_admin_user)):
    from services.grader import grade_all_pending
    return grade_all_pending(db)


@app.post("/api/admin/backfill-bankroll")
async def admin_backfill_bankroll(
    user_id: Optional[str] = None,
    admin: dict = Depends(get_admin_user),
):
    """Replay graded bets to rebuild agent_instances.bankroll_current."""
    from agent.bankroll_backfill import backfill_all_agent_bankrolls, replay_bankroll_for_user

    if user_id:
        return replay_bankroll_for_user(db, user_id)
    return backfill_all_agent_bankrolls(db)


@app.post("/api/admin/refresh-memory")
async def admin_refresh_memory(
    user_id: Optional[str] = None,
    admin: dict = Depends(get_admin_user),
):
    """Recompute agent_memory stats (optionally for one user)."""
    from learning.memory import refresh_memory, refresh_memory_all_users, refresh_platform_memory

    if user_id:
        refresh_memory(db, user_id)
        refresh_platform_memory(db)
        return {"message": "Memory refreshed", "user_id": user_id, "platform_refreshed": True}
    return refresh_memory_all_users(db)


@app.post("/api/admin/recalculate-units")
async def admin_recalculate_units(admin: dict = Depends(get_admin_user)):
    """Recompute units_result for all graded bets and refresh the Google Sheet."""
    from services.grader import recalculate_graded_units
    from services.sheets_sync import maybe_sync_sheets

    result = recalculate_graded_units(db)
    maybe_sync_sheets(db, reason="recalculate-units")
    return result


@app.post("/api/admin/sync-sheets")
async def admin_sync_sheets(admin: dict = Depends(get_admin_user)):
    from services.sheets_sync import is_configured, sync_bets_to_sheet
    if not is_configured():
        raise HTTPException(status_code=400, detail="Google Sheets not configured (GOOGLE_SHEET_ID + credentials)")
    return sync_bets_to_sheet(db)


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


@app.post("/api/admin/morning-toa-poll")
async def admin_morning_toa_poll(admin: dict = Depends(get_admin_user)):
    """Manually trigger the daily TOA morning snapshot."""
    return poll_morning_toa_snapshot(db)


@app.get("/api/admin/api-usage")
async def admin_api_usage(admin: dict = Depends(get_admin_user)):
    """Odds API quota status and projected burn rates."""
    return budget_summary(OddsClient.get_usage())


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


async def run_daily_cards(target_date: str = None, specific_user_id: str = None):
    """Daily major-league ESM card (MLB/NBA/NHL/NFL). World Cup uses the separate WC pipeline."""
    from agent.unit_tracker import sync_units_at_risk

    today = target_date or date.today().isoformat()
    grade_result = grade_all_pending(db)
    print(f"[AgentEdge] Graded: {grade_result}")
    if specific_user_id:
        users_result = db.table("profiles").select("id").eq("id", specific_user_id).eq("is_active", True).execute()
    else:
        users_result = db.table("profiles").select("id").eq("is_active", True).execute()
    users = users_result.data or []
    for user_row in users:
        uid = user_row["id"]
        try:
            sync_units_at_risk(db, uid, today)
            prefs_result = db.table("preferences").select("*").eq("user_id", uid).execute()
            prefs = prefs_result.data[0] if prefs_result.data else {}
            run_card_for_user(uid, prefs, target_date=today)
            print(f"[AgentEdge] Major-league ESM card generated for {uid}")
        except Exception as e:
            print(f"[AgentEdge] Error for {uid}: {e}")


async def run_weekly_digest():
    from datetime import timedelta
    today = date.today()
    week_start = (today - timedelta(days=7)).isoformat()
    users_result = db.table("profiles").select("id, email, full_name").eq("is_active", True).execute()
    users = users_result.data or []
    summaries = []
    for user_row in users:
        uid = user_row["id"]
        try:
            bets_result = (
                db.table("bets").select("*")
                .eq("user_id", uid)
                .neq("result", "pending")
                .gte("date", week_start)
                .lt("date", today.isoformat())
                .execute()
            )
            record = _calculate_record(bets_result.data or [])
            summaries.append({"user_id": uid, "email": user_row.get("email", ""), **record})
            print(f"[EdgeBet][WeeklyDigest] {user_row.get('email', uid)}: {record['record_str']} {record['units_str']} ({record['roi_pct']}% ROI)")
        except Exception as e:
            print(f"[EdgeBet][WeeklyDigest] Error for {uid}: {e}")
    print(f"[EdgeBet][WeeklyDigest] Completed for {len(summaries)} users (week of {week_start})")
    return summaries


def _calculate_record(bets: list) -> dict:
    from services.units import aggregate_record

    rec = aggregate_record(bets)
    return {
        "wins": rec["wins"],
        "losses": rec["losses"],
        "pushes": rec["pushes"],
        "total": rec["wins"] + rec["losses"] + rec["pushes"],
        "net_units": rec["net_units"],
        "wagered": rec["units_risked"],
        "units_won": rec["units_won"],
        "units_lost": rec["units_lost"],
        "roi_pct": rec["roi_pct"],
        "record_str": rec["record_str"],
        "units_str": rec["units_str"],
    }
