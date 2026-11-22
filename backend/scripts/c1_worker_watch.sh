#!/bin/bash
# L-03a: launchd 常驻 C1 worker 包装（宿主 sidecar）。
# - WorkingDirectory 必须是 backend/，Settings 才会读到 backend/.env（DSN/MASTER_KEY）。
# - .env.shell 提供直接读 os.environ 的变量（model-hub 地址与 token）。
# - 宿主侧把知识增强地址也切到 localhost（容器 DNS 在宿主不可解析；失败即停用，不阻断）。
# - 单实例约束：本 launchd 是唯一常驻 worker；容器 worker 由 LOOM_C1_WORKER_ENABLED
#   控制，重建镜像前必须先把它置 false（见 infra/.env），两者不得同时开。
set -euo pipefail
cd "$(dirname "$0")/.."   # → backend/

set -a
# shellcheck disable=SC1091
[ -f .env.shell ] && source .env.shell
set +a

export MODEL_HUB_URL="${MODEL_HUB_URL:-http://localhost:8791}"
export LOOM_KNOWLEDGE_URL="${LOOM_KNOWLEDGE_URL:-http://localhost:8791}"
# 用 http（本地回环明文），与容器内一致；LOOM_KNOWLEDGE_URL 若为容器 DNS 则覆盖。
case "${LOOM_KNOWLEDGE_URL:-}" in
  http://model-hub:*) export LOOM_KNOWLEDGE_URL="http://localhost:8791" ;;
esac

exec .venv/bin/python scripts/c1_worker.py --watch \
  --interval "${LOOM_C1_WORKER_INTERVAL_SECONDS:-60}" \
  --limit "${LOOM_C1_WORKER_BATCH_SIZE:-10}"
