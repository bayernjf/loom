#!/bin/sh
set -e

# Q157：多副本并发启动由 alembic env.py 的 PG 咨询锁串行化（一个升级、其余 no-op）。
alembic upgrade head

# --log-config 把 root 日志级别提到 INFO，使 app 自身的 worker/锁/配置广播日志
# （app.core.* 的 logger.info）在容器 stdout 可见；默认 uvicorn 配置只输出
# uvicorn.* 日志，应用 INFO 行会被 root 的 WARNING 级别过滤掉。
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-config /app/uvicorn-log.json
