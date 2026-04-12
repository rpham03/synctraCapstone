# FastAPI application entry point — registers all API routers and CORS middleware.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.routes import events, tasks, schedule, chat, auth

app = FastAPI(title="Syntra API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/api/v1/auth",     tags=["auth"])
app.include_router(events.router,   prefix="/api/v1/events",   tags=["events"])
app.include_router(tasks.router,    prefix="/api/v1/tasks",    tags=["tasks"])
app.include_router(schedule.router, prefix="/api/v1/schedule", tags=["schedule"])
app.include_router(chat.router,     prefix="/api/v1/chat",     tags=["chat"])
