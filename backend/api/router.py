from fastapi import APIRouter

from backend.api import routes_review, routes_stories, routes_system, routes_workflow

api_router = APIRouter(prefix="/api/v1")
for _r in (routes_system.router, routes_stories.router, routes_review.router, routes_workflow.router):
    api_router.include_router(_r)
