#!/bin/sh
set -e

# Q200 #33：出站供应商 Key 由 LOOM_MASTER_KEY 加密落库（Q148），空值 = 加密的 Key
# 重启即不可解（crypto._fernet 仅 warning + 进程内临时 key）。生产/彩排容器一律
# 启动即 fail-fast，避免"看起来跑起来了、重启后 Key 全废"。不放 compose 的
# ${VAR:?}——compose 解析期全局求值会打断彩排/监控 overlay（Q185 已记载该坑）。
if [ -z "${LOOM_MASTER_KEY:-}" ]; then
  echo "FATAL: LOOM_MASTER_KEY is required (outbound API keys are encrypted with it)." >&2
  exit 1
fi

# Q157：多副本并发启动由 alembic env.py 的 PG 咨询锁串行化（一个升级、其余 no-op）。
alembic upgrade head

# --log-config 把 root 日志级别提到 INFO，使 app 自身的 worker/锁/配置广播日志
# （app.core.* 的 logger.info）在容器 stdout 可见；默认 uvicorn 配置只输出
# uvicorn.* 日志，应用 INFO 行会被 root 的 WARNING 级别过滤掉。
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-config /app/uvicorn-log.json
