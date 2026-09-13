from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings.

    Only secrets and connection strings come from environment variables
    (docs/15 §4). All business tunables live in the config center (Q9).
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="LOOM_")

    database_dsn: str = "postgresql+asyncpg://loom:loom@localhost:5432/loom"
    redis_dsn: str = "redis://localhost:6379/0"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "loom"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
