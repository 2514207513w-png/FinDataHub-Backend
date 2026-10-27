from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://findata:localpass@localhost:5432/findata"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = ""
    bootstrap_admin_email: str = "admin@example.test"
    bootstrap_admin_password: str = ""
    upload_dir: str = "./uploads"
    max_upload_mb: int = 10
    cache_ttl_seconds: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
