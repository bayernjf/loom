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

    # Q138 restock requested 信号 Redis Streams 生产接线：默认关。开启后跌破
    # critical 的补货请求在提交后 best-effort XADD 到 restock 流（DB 行仍是事实
    # 源、DB 轮询兜底）；消费组水平并行消费留 V2（花钱单实例裁决见 Q87/Q89）。
    restock_stream_enabled: bool = False

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

    # Q141 配置缓存 TTL 兜底（秒）：广播 best-effort 可能丢消息，订阅器在最近
    # 一次成功装载超过该时长后，即使没收到失效消息也回源全量 reload 一次，给
    # 陈旧时长设上限。仅在 config_cache_broadcast_enabled 开启时由订阅器使用；
    # 单副本 after_commit 即时 apply，不依赖 TTL。运维参数，非 Q9 业务旋钮。
    config_cache_ttl_seconds: float = 300.0

    # Q137 导出任务真后台 worker（Redis Streams 消费组）：默认关，关闭时 POST
    # /api/exports/jobs 维持 Q132 请求内同步 completed；开启后建 queued 入流，
    # 进程内 ExportWorker 消费置 running→completed/failed（只读幂等，可多副本并行）。
    export_worker_enabled: bool = False
    export_stream_block_seconds: float = 5.0
    # Q152 单进程内导出消费组 consumer 数（并发度）与每轮拉取批量：默认 1/20，
    # 保持 V1 单 worker 行为；消费组内多 consumer 原生分片（XREADGROUP 各取不
    # 重叠消息），调高并发度即水平扩展导出处理能力。运维参数，非 Q9 业务旋钮。
    export_worker_concurrency: int = 1
    export_stream_count: int = 20

    # Q161 客户效果批量回填异步导入 worker（Redis Streams 消费组）：默认关，关闭时
    # POST /api/effects/backfill/jobs 请求内同步跑到终态（保持 V1 单副本行为）；
    # 开启后建 queued 入流，进程内 ImportWorker 消费置 running→completed/failed。
    # 导入是写且需后台重放，payload（CSV 原文 / xlsx base64）落 import_jobs 表。
    import_worker_enabled: bool = False
    import_stream_block_seconds: float = 5.0
    import_worker_concurrency: int = 1
    import_stream_count: int = 20

    # Q165 段11 FCW 批量组装异步 worker（Redis Streams 消费组，镜像 Q137 导出 /
    # Q161 导入）：默认关，关闭时 POST /api/fcw/assembly-tasks 维持 Q55 请求内
    # 同步跑完（status=running→completed，七 Guard 原子性不变）；开启后建 queued
    # 入流，进程内 FcwWorker 消费置 running→completed（per-slot Guard 失败仍隔离
    # 记 results.failures，任务整体 completed）；基础设施异常留 PEL 由 XCLAIM
    # 接管、超 MAX_DELIVERIES 进死信并置 failed。运维参数，非 Q9 业务旋钮。
    fcw_worker_enabled: bool = False
    fcw_stream_block_seconds: float = 5.0
    fcw_worker_concurrency: int = 1
    fcw_stream_count: int = 20

    # Q142 中台导出行数硬上限（运维防护参数，非 Q9 业务旋钮）：fcw.csv/fcw.json
    # 与导出任务在未显式分页时最多导出的 final_id 行数，防大结果集 OOM/超大响应；
    # GET 直读端点的 limit 不得超过该值（422）。默认 10 万行。
    export_max_rows: int = 100000

    # Q156 客户效果批量 CSV 服务端上传的数据行硬上限（运维防护参数，非 Q9 业务
    # 旋钮）：解除 Q136 前端 500 行软上限后防单次超大请求；超限整批 422。
    backfill_upload_max_rows: int = 10000

    # Q91 自研 DAG 编排器：同层并行节点的进程内信号量上限（env 运维参数，
    # 非 Q9 业务旋钮）；日预算硬停仍由 gateway 全局闸门兜底，并发不绕预算。
    orch_max_concurrency: int = 4

    # Q82：outbound 供应商 API Key 落库密文的主密钥（只从环境变量注入，不入库不入仓）。
    # 未设置时测试/本地用进程内临时密钥（重启后旧密文不可解，仅限开发态）。
    master_key: str = ""

    # Q178 内部运营个人访问令牌（PAT）身份层第一切片：默认关。关闭时管理面读口
    # （query actor）与运营写口（body actor）维持 V1 自报口径，零行为变化；开启后
    # 凡要求内部角色（operations/platform_admin/internal_compliance/dictionary_admin/
    # product_reviewer）的端点一律以 Authorization: Bearer loom_staff_... 验真的人员/
    # 角色为准，忽略自报 roles（无令牌 401、角色不足 403、自报提权无效）。客户侧身份
    # 与 actor↔tenant 绑定后置，不受本门控影响；机器端点（Agent Key/A2A）独立鉴权。
    staff_auth_enabled: bool = False

    # Q187 段12 discarded 成品保留期物理清理（docs/20 §6.5 C4 收口，甲案）：默认关。
    # 关闭时第五个 sweep 作业空转返回 0，V1 现有行为一字不变；开启后过
    # content.discard_retention_days 保留窗口、且无任何下游引用（effect_records/
    # effect_claims 硬 FK、import_jobs 可重放历史）的 discarded 行被物理删除并逐行
    # 写 content.discard_purged 审计。破坏性动作，故与 Q87/Q137/Q161 同例门控默认关。
    discard_purge_enabled: bool = False
    # 单轮 sweep 最多清理的行数（运维防护参数，非 Q9 业务旋钮），防单事务过大。
    discard_purge_batch: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
