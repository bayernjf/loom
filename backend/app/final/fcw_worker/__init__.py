"""Q165 FCW 批量组装异步 worker（Redis Streams 消费组，镜像 Q137 导出 / Q161 导入）。

组装是写（产 final_id + 审计），但七 Guard 在 assemble_one 内逐条强制，且重复任务
被 DuplicateIssuance 与七 Guard 幂等拦截，故与导入一样无需 leader 单实例锁，消费组
支持多副本各消费一部分任务：

- ``XREADGROUP >`` 读新任务即入 PEL，处理完成才 ``XACK``；
- 崩溃在 ACK 前的任务留 PEL，``XCLAIM`` 空闲阈值后由任一副本接管重试；
- per-slot Guard 失败（MaterialMissing/GuardsFailed/DuplicateIssuance）在
  process_task 内捕获记 results.failures，任务整体 completed，正常提交并 ACK
  （不重试、不进死信，Q55 单项失败隔离口径不变）；
- 任务不存在（消息指向已删除/幽灵 task_id）直接 ACK 丢弃（创建时已先提交再入流，
  正常路径任务必可见；幽灵消息无重试价值）；
- 基础设施异常（DB 故障等）向上抛：未超限留 PEL 接管，超 MAX_DELIVERIES 进死信流
  并置 task status=failed；
- 任务已终态（重复投递）直接 ACK 丢弃（幂等）。

门控 ``LOOM_FCW_WORKER_ENABLED`` 默认 false：关闭时 POST /api/fcw/assembly-tasks
维持 Q55 请求内同步跑完，不启动本循环、不接触 Redis。零迁移（status String(16)
已表达 queued/running/completed/failed）。
"""

from .worker import FcwWorker, build_fcw_workers

__all__ = ["FcwWorker", "build_fcw_workers"]
