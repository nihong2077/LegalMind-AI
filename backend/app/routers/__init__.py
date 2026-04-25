from app.routers.auth import router as auth_router
from app.routers.cases import router as cases_router
from app.routers.agents import router as agents_router
from app.routers.gateway import router as gateway_router
from app.routers.voice import router as voice_router
from app.routers.evaluation import router as evaluation_router

__all__ = ["auth_router", "cases_router", "agents_router", "gateway_router", "voice_router", "evaluation_router"]