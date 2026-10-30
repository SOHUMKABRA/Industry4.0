from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-insecure-secret-change-me-before-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twin_env: str = "development"
    database_url: str = "sqlite:///./data/twin.db"
    secret_key: str = DEV_SECRET
    credential_key: str = ""
    access_token_minutes: int = 480
    cors_origins: str = "http://localhost:5173"
    seed_demo: bool = True

    @property
    def is_production(self) -> bool:
        return self.twin_env.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def check_production_safety(self) -> None:
        """Refuse to start a production instance with development secrets."""
        if not self.is_production:
            return
        problems = []
        if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to a random value of 32+ chars")
        if not self.credential_key:
            problems.append("CREDENTIAL_KEY must be set (Fernet key)")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
