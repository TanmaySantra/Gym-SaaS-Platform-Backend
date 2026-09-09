"""
FastAPI application entrypoint.

Routers are added phase-by-phase (auth in Phase 3, gyms/members etc. in later
phases). Kept intentionally thin per section 3 ("do NOT create a giant main.py").
"""
from fastapi import FastAPI

# Must be imported before any router that touches the ORM, so every model's
# relationship() string references can resolve regardless of import order.
import app.models_registry  # noqa: F401

from app.auth.router import router as auth_router
from app.admin.router import router as admin_router
from app.gyms.router import router as gyms_router
from app.members.router import router as members_router
from app.memberships.router import router as memberships_router
from app.payments.router import router as payments_router
from app.workouts.router import router as workouts_router
from app.progress.router import router as progress_router
from app.attendance.router import router as attendance_router
from app.ai.router import router as ai_router
from app.analytics.router import router as analytics_router
from app.notifications.router import router as notifications_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
)

register_exception_handlers(app)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"success": True, "data": {"status": "ok"}}


app.include_router(auth_router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["auth"])
app.include_router(admin_router, prefix=f"{settings.API_V1_PREFIX}/admin", tags=["admin"])
app.include_router(gyms_router, prefix=f"{settings.API_V1_PREFIX}/gyms", tags=["gyms"])
app.include_router(members_router, prefix=f"{settings.API_V1_PREFIX}/members", tags=["members"])
app.include_router(memberships_router, prefix=f"{settings.API_V1_PREFIX}/memberships", tags=["memberships"])
app.include_router(payments_router, prefix=f"{settings.API_V1_PREFIX}/payments", tags=["payments"])
app.include_router(workouts_router, prefix=f"{settings.API_V1_PREFIX}/workouts", tags=["workouts"])
app.include_router(progress_router, prefix=f"{settings.API_V1_PREFIX}/progress", tags=["progress"])
app.include_router(attendance_router, prefix=f"{settings.API_V1_PREFIX}/attendance", tags=["attendance"])
app.include_router(ai_router, prefix=f"{settings.API_V1_PREFIX}/ai", tags=["ai"])
app.include_router(analytics_router, prefix=f"{settings.API_V1_PREFIX}/analytics", tags=["analytics"])
app.include_router(notifications_router, prefix=f"{settings.API_V1_PREFIX}/notifications", tags=["notifications"])
