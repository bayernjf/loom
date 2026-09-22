#!/usr/bin/env bash
# fullchain-rehearsal.sh — 全链 golden path 真 PG 演练（B1/B4）
#
# 起一次性 pgvector/pgvector:pg16 容器（宿主端口默认 55442），alembic upgrade head，
# 然后跑 backend/tests/e2e/test_fullchain_golden_path.py 的真 PG 变体：
#   - 默认：synthetic LLM，不花钱（B1）
#   - 设 LOOM_E2E_REAL_LLM=1 + LOOM_E2E_AGNES_KEY：CAT-RECOG/ARTICLE-GEN 走 agnes
#     真模型（B4，真金白银，需负责人授权）
#
# 不触 atlas-pg；脚本结束默认拆容器（KEEP=1 保留）。演练本地手动，不进 CI。

set -u

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BACKEND_DIR="$ROOT_DIR/backend"
PY="$BACKEND_DIR/.venv/bin/python"
ALEMBIC="$BACKEND_DIR/.venv/bin/alembic"

IMG=pgvector/pgvector:pg16
PORT=${FULLCHAIN_PORT:-55442}
NAME="loom-fullchain-$PORT"
DSN="postgresql+asyncpg://loom:loom@localhost:${PORT}/loom"

c_bold=$'\033[1m'; c_green=$'\033[32m'; c_red=$'\033[31m'; c_off=$'\033[0m'
PASS=0; FAIL=0
check() { # check <desc> <0|1>
  if [ "$2" = "1" ]; then echo "  ${c_green}PASS${c_off} $1"; PASS=$((PASS+1));
  else echo "  ${c_red}FAIL${c_off} $1"; FAIL=$((FAIL+1)); fi
}

echo "${c_bold}== 起一次性 PG16 容器（端口 ${PORT}）==${c_off}"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --rm --name "$NAME" \
  -e POSTGRES_USER=loom -e POSTGRES_PASSWORD=loom -e POSTGRES_DB=loom \
  -p "${PORT}:5432" "$IMG" >/dev/null

ready=0
for _ in $(seq 1 60); do
  if docker exec -e PGPASSWORD=loom "$NAME" pg_isready -h localhost -U loom >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
check "PG16 容器就绪" "$ready"

echo "${c_bold}== alembic upgrade head ==${c_off}"
( cd "$BACKEND_DIR" && LOOM_DATABASE_DSN="$DSN" "$ALEMBIC" upgrade head ) > /tmp/fullchain-migrate.log 2>&1
rc=$?
tail -2 /tmp/fullchain-migrate.log | sed 's/^/  /'
check "迁移到 head 成功（rc=0）" "$([ $rc = 0 ] && echo 1 || echo 0)"

echo "${c_bold}== 跑 e2e 全链（真 PG）==${c_off}"
( cd "$BACKEND_DIR" && LOOM_E2E_PG_DSN="$DSN" \
  LOOM_E2E_REAL_LLM="${LOOM_E2E_REAL_LLM:-0}" \
  LOOM_E2E_AGNES_KEY="${LOOM_E2E_AGNES_KEY:-}" \
  "$PY" -m pytest tests/e2e -q ) > /tmp/fullchain-pytest.log 2>&1
rc=$?
tail -5 /tmp/fullchain-pytest.log | sed 's/^/  /'
if [ "${LOOM_E2E_REAL_LLM:-0}" = "1" ]; then
  check "真 LLM 全链 e2e 通过" "$([ $rc = 0 ] && echo 1 || echo 0)"
else
  check "synthetic 全链 e2e 通过" "$([ $rc = 0 ] && echo 1 || echo 0)"
fi

echo
echo "${c_bold}结果：${PASS} PASS / ${FAIL} FAIL${c_off}"

if [ "${KEEP:-0}" != "1" ]; then
  docker rm -f "$NAME" >/dev/null 2>&1 || true
fi
[ "$FAIL" = 0 ]
