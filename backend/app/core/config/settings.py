# App configuration — loads environment variables for the database, Redis, and third-party APIs.
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql://user:password@localhost:5432/syntra"
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "change-me-in-production"
    canvas_api_token: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
