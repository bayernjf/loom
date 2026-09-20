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

    # Q90 restock 瞬态失败指数退避（env 运维参数，非 Q9 业务旋钮）：
    # base×2^(attempts-1)，封顶 max；上游传输错累计 max_attempts 次转终态，
    # 日预算硬停（UTC 次日恢复）永不转终态。
    restock_backoff_base_seconds: float = 60.0
    restock_backoff_max_seconds: float = 1800.0
    restock_backoff_max_attempts: int = 10

    # Q89 多副本单实例锁：Redis SET NX PX leader 锁，env 门控默认关
    # （单副本/本地零依赖）；开启后 Redis 不可用 fail-closed 跳过本轮。
    distributed_lock_enabled: bool = False

    # Q135 配置缓存多副本失效广播（Redis pub/sub）：默认关，V1 单进程仅在
    # after_commit 进程内热更新；多副本开启后，发布方广播失效、其余副本订阅后
    # reload。广播为 best-effort（失败只告警，不影响已提交事务）。
    config_cache_broadcast_enabled: bool = False

    # Q137 导出任务真后台 worker（Redis Streams 消费组）：默认关，关闭时 POST
    # /api/exports/jobs 维持 Q132 请求内同步 completed；开启后建 queued 入流，
    # 进程内 ExportWorker 消费置 running→completed/failed（只读幂等，可多副本并行）。
    export_worker_enabled: bool = False
    export_stream_block_seconds: float = 5.0

    # Q91 自研 DAG 编排器：同层并行节点的进程内信号量上限（env 运维参数，
    # 非 Q9 业务旋钮）；日预算硬停仍由 gateway 全局闸门兜底，并发不绕预算。
    orch_max_concurrency: int = 4

    # Q82：outbound 供应商 API Key 落库密文的主密钥（只从环境变量注入，不入库不入仓）。
    # 未设置时测试/本地用进程内临时密钥（重启后旧密文不可解，仅限开发态）。
    master_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
