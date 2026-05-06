# API routes for user authentication and Google OAuth token exchange.
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def auth_health() -> dict:
    """Liveness for the auth router; the mobile app uses Supabase for sign-in today."""
    return {"status": "ok"}
