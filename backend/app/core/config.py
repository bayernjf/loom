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

    # M10b SLA sweep 调度（进程内 asyncio loop；LOOM_SCHEDULER_ENABLED=false 可关）。
    scheduler_enabled: bool = True
    sweep_interval_seconds: float = 300.0

    # Q87 M8 restock_auto worker：自动花真 token，默认关闭、部署显式 opt-in。
    restock_worker_enabled: bool = False
    restock_interval_seconds: float = 60.0
    restock_batch_size: int = 20

    # Q89 多副本单实例锁：Redis SET NX PX leader 锁，env 门控默认关
    # （单副本/本地零依赖）；开启后 Redis 不可用 fail-closed 跳过本轮。
    distributed_lock_enabled: bool = False

    # Q82：outbound 供应商 API Key 落库密文的主密钥（只从环境变量注入，不入库不入仓）。
    # 未设置时测试/本地用进程内临时密钥（重启后旧密文不可解，仅限开发态）。
    master_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
