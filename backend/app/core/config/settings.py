# App configuration — loads environment variables for the database, Redis, and third-party APIs.
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://user:password@localhost:5432/syntra"
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "change-me-in-production"
    supabase_url: str = ""
    supabase_key: str = ""
    canvas_api_token: str = ""
    # REST root including /api/v1 — UW default; override for other schools.
    canvas_api_base_url: str = "https://canvas.uw.edu/api/v1"
    google_client_id: str = ""
    google_client_secret: str = ""

settings = Settings()
