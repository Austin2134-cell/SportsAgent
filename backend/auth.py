"""
auth.py — Supabase JWT validation. get_current_user verifies the bearer
token; get_admin_user additionally checks the profiles.is_admin flag.
"""

import os
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

security = HTTPBearer()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    token = credentials.credentials
    try:
        client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        response = client.auth.get_user(token)
        if not response or not response.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return {"id": response.user.id, "email": response.user.email}
    except Exception:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


async def get_admin_user(user: dict = Depends(get_current_user)) -> dict:
    from database import db
    result = db.table("profiles").select("is_admin").eq("id", user["id"]).single().execute()
    if not result.data or not result.data.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
