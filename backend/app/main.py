# FastAPI application entry point — registers all API routers and CORS middleware.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.routes import events, course_import

app = FastAPI(title="Syntra API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router,        prefix="/api/v1/events",        tags=["events"])
app.include_router(course_import.router, prefix="/api/v1/course-import", tags=["course-import"])
