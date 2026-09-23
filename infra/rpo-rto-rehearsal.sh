#!/usr/bin/env bash
# Q175 RPO / RTO 量化达标演练（docs/17 §5 + §7.4，02 C1.119）。
#
# docs/17 §5 已定目标值：RPO ≤ 24h（86400s）/ RTO ≤ 4h（14400s）。Q146 落了每日
# 全量 pg_dump（custom/compress=9 + 7 天保留），Q158 演练了「异机恢复内容零差异」，
# 但「故障注入后到底丢多少、多久能恢复」从未量化。本脚本用一次性 PG16 容器实测：
#
#   源库 A ：alembic upgrade head（真实 head/61 表）+ 造 tenants 2 行；
#   备份   ：Q146 同款 pg_dump（custom/compress=9），记 T_DUMP；
#   备份后 ：再写 1 行（模拟备份后、故障前的新增）——该行在故障中丢失，用来量 RPO；
#   故障注入：docker rm -f 源库（实例/数据卷彻底消失），记 T_FAIL；
#   新机 B ：起替代空库 → drop/create → pg_restore → 应用 ORM 栈只读冒烟，
#            恢复动作全程计时（T_RTO_START..T_RTO_END）；
#   量化   ：RPO_OBSERVED = T_FAIL - T_DUMP（备份间隔即最坏丢失窗口）；
#            RTO_OBSERVED = T_RTO_END - T_RTO_START（工程恢复动作耗时）；
#            恢复后 tenants=2（备份点），第 3 行确认丢失（RPO 演示）。
#
# 达标口径（诚实边界）：
# - RPO：生产每日 1 次全量备份 → 最坏丢失窗口 = 备份间隔 = 24h，故 RPO ≤ 24h 由备份
#   频率保证；本次演练 T_DUMP→T_FAIL 仅数秒，RPO_OBSERVED ≪ 24h，证明机制成立。
# - RTO：本演练认证「工程恢复动作」（起库 + restore + 应用只读确认）耗时 ≤ 4h；
#   不含人员发现/决策时间（生产由 Q146 watchdog 探活 + webhook 缩短发现段）。
#
# 不构建应用镜像、不注 LLM key（synthetic、不花真钱）、不碰本机 atlas-pg
# （宿主端口 55446/55447）；结束默认拆除容器（KEEP=1 保留）。
#
# 用法（在 infra/ 目录，需本机 Docker；宿主需有 backend/.venv，含 alembic/asyncpg）：
#   ./rpo-rto-rehearsal.sh          # 全流程并输出 RPO_RTO_CERT 认证行
#   ./rpo-rto-rehearsal.sh down     # 仅清理残留演练容器
#   KEEP=1 ./rpo-rto-rehearsal.sh   # 跑完保留容器便于人工排查
set -uo pipefail

cd "$(dirname "$0")"
IMG=pgvector/pgvector:pg16
SRC=loom-rpo-src
DST=loom-rpo-dst
SPORT=${RPO_SRC_PORT:-55446}
DPORT=${RPO_DST_PORT:-55447}
BACKEND_DIR=../backend
PY="$BACKEND_DIR/.venv/bin/python"
ALEMBIC="$BACKEND_DIR/.venv/bin/alembic"
DSN_SQL_B="postgresql://loom:loom@localhost:${DPORT}/loom"
DSN_ALEMBIC_A="postgresql+asyncpg://loom:loom@localhost:${SPORT}/loom"
DSN_ALEMBIC_B="postgresql+asyncpg://loom:loom@localhost:${DPORT}/loom"
# docs/17 §5 目标值。
RPO_TARGET=86400   # 24h
RTO_TARGET=14400   # 4h
TMP=$(mktemp -d)

c_green=$'\033[32m'; c_red=$'\033[31m'; c_bold=$'\033[1m'; c_off=$'\033[0m'
pass=0; fail=0
check() { # check <desc> <0|1>
  if [ "$2" = "1" ]; then echo "${c_green}  PASS${c_off} $1"; pass=$((pass+1));
  else echo "${c_red}  FAIL${c_off} $1"; fail=$((fail+1)); fi
}
now() { "$PY" -c 'import time;print(f"{time.time():.3f}")'; }

cleanup() {
  docker rm -f "$SRC" "$DST" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap 'if [ "${KEEP:-0}" != "1" ]; then cleanup; fi' EXIT

pg_wait() {
  for _ in $(seq 1 60); do
    if docker exec -e PGPASSWORD=loom "$1" pg_isready -h localhost -U loom >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

start_src() {
  echo "${c_bold}== 起源库 A（${SPORT}）==${c_off}"
  docker rm -f "$SRC" >/dev/null 2>&1 || true
  docker run -d --rm --name "$SRC" \
    -e POSTGRES_USER=loom -e POSTGRES_PASSWORD=loom -e POSTGRES_DB=loom \
    -p "${SPORT}:5432" "$IMG" >/dev/null
  if pg_wait "$SRC"; then echo "     源库 A ready"; check "源库 A 就绪" 1;
  else echo "     源库 A 未就绪"; check "源库 A 就绪" 0; fi
}

migrate_src() {
  echo "${c_bold}== 源库 A：alembic upgrade head（真实 head/61 表）==${c_off}"
  ( cd "$BACKEND_DIR" && LOOM_DATABASE_DSN="$DSN_ALEMBIC_A" "$ALEMBIC" upgrade head ) \
    > "$TMP/migrate.log" 2>&1
  rc=$?
  tail -1 "$TMP/migrate.log" | sed 's/^/     /'
  check "源库 A 迁移到 head（rc=0）" "$([ $rc = 0 ] && echo 1 || echo 0)"
}

seed_and_backup() {
  echo "${c_bold}== 造 tenants 2 行 → pg_dump → 备份后再写 1 行（量 RPO）==${c_off}"
  docker exec -e PGPASSWORD=loom "$SRC" psql -h localhost -U loom -d loom -v ON_ERROR_STOP=1 \
    -c "INSERT INTO tenants(tenant_id,name,plan,status,monthly_token_quota,detail,created_by)
        VALUES ('rpo-demo-alpha','RPO Alpha','pro','active',NULL,'{\"rpo\":true}'::jsonb,'rpo-rehearsal'),
               ('rpo-demo-beta','RPO Beta','trial','trial',500000,'{\"rpo\":true}'::jsonb,'rpo-rehearsal');" \
    > "$TMP/seed1.log" 2>&1
  check "备份点造数 tenants=2" "$([ $? = 0 ] && echo 1 || echo 0)"

  # Q146 同款备份。
  docker exec -e PGPASSWORD=loom "$SRC" \
    pg_dump -h localhost -U loom -d loom --no-password --format=custom --compress=9 \
    --file=/tmp/loom-rpo.dump >/dev/null 2>&1
  docker cp "$SRC":/tmp/loom-rpo.dump "$TMP/loom.dump"
  T_DUMP=$(now)
  sz=$(stat -f%z "$TMP/loom.dump" 2>/dev/null || stat -c%s "$TMP/loom.dump")
  echo "     dump=$sz bytes, T_DUMP=$T_DUMP"
  check "pg_dump 非空（$sz bytes）" "$([ "$sz" -gt 1000 ] && echo 1 || echo 0)"

  # 备份后新增：该行将在故障中丢失（RPO 窗口演示）。
  docker exec -e PGPASSWORD=loom "$SRC" psql -h localhost -U loom -d loom -v ON_ERROR_STOP=1 \
    -c "INSERT INTO tenants(tenant_id,name,plan,status,monthly_token_quota,detail,created_by)
        VALUES ('rpo-demo-lost','RPO Lost Row','trial','trial',NULL,'{\"would_be_lost\":true}'::jsonb,'rpo-rehearsal');" \
    > "$TMP/seed2.log" 2>&1
  n3=$(docker exec -e PGPASSWORD=loom "$SRC" psql -h localhost -U loom -d loom -tAc 'SELECT count(*) FROM tenants;')
  echo "     备份后源库 tenants=${n3}（=3，第 3 行未备份）"
  check "备份后源库 tenants=3" "$([ "$n3" = 3 ] && echo 1 || echo 0)"
  echo "$T_DUMP" > "$TMP/t_dump"
}

inject_failure() {
  echo "${c_bold}== 故障注入：docker rm -f 源库 A（实例/卷彻底消失）==${c_off}"
  T_FAIL=$(now)
  docker rm -f "$SRC" >/dev/null 2>&1
  sleep 1
  alive=$(docker ps --filter "name=$SRC" --format '{{.Names}}')
  echo "     T_FAIL=$T_FAIL, 源库存活=['${alive}']"
  check "源库 A 已被故障销毁" "$([ -z "$alive" ] && echo 1 || echo 0)"
  echo "$T_FAIL" > "$TMP/t_fail"
}

# RTO 计时段：起新机 → 恢复 → 应用只读冒烟。
recover_timed() {
  echo "${c_bold}== 新机 B 恢复（RTO 计时开始，${DPORT}）==${c_off}"
  T_RTO_START=$(now)
  docker rm -f "$DST" >/dev/null 2>&1 || true
  docker run -d --rm --name "$DST" \
    -e POSTGRES_USER=loom -e POSTGRES_PASSWORD=loom -e POSTGRES_DB=loom \
    -p "${DPORT}:5432" "$IMG" >/dev/null
  pg_wait "$DST" || true

  docker exec -e PGPASSWORD=loom "$DST" psql -h localhost -U loom -d postgres -v ON_ERROR_STOP=1 \
    -c "REVOKE CONNECT ON DATABASE loom FROM public;
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
          WHERE datname='loom' AND pid<>pg_backend_pid();
        DROP DATABASE IF EXISTS loom;
        CREATE DATABASE loom OWNER loom;" > "$TMP/recreate.log" 2>&1
  docker cp "$TMP/loom.dump" "$DST":/tmp/loom.dump
  docker exec -e PGPASSWORD=loom "$DST" \
    pg_restore -h localhost -U loom -d loom --no-owner --no-password /tmp/loom.dump \
    > "$TMP/restore.log" 2>&1
  rc=$?
  errs=$(grep -cE "^pg_restore:.*error" "$TMP/restore.log" || true)
  check "pg_restore rc=0、无 error 行" "$([ $rc = 0 ] && [ "$errs" = 0 ] && echo 1 || echo 0)"

  # 应用 ORM 栈连恢复库只读冒烟（同 Q158 先例）。
  ( cd "$BACKEND_DIR" && LOOM_DATABASE_DSN="$DSN_ALEMBIC_B" "$PY" - <<'PY'
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import app.main  # noqa: F401
async def main():
    eng = create_async_engine(os.environ["LOOM_DATABASE_DSN"])
    try:
        async with eng.connect() as conn:
            n = (await conn.execute(text("SELECT count(*) FROM tenants"))).scalar()
            print(f"APP_READ tenants={n}")
    finally:
        await eng.dispose()
asyncio.run(main())
PY
  ) > "$TMP/appread.log" 2>&1
  arc=$?
  sed 's/^/     /' "$TMP/appread.log"
  T_RTO_END=$(now)
  check "应用栈连恢复库只读成功" "$([ $arc = 0 ] && echo 1 || echo 0)"

  n_rec=$(docker exec -e PGPASSWORD=loom "$DST" psql -h localhost -U loom -d loom -tAc 'SELECT count(*) FROM tenants;')
  lost=$(docker exec -e PGPASSWORD=loom "$DST" psql -h localhost -U loom -d loom -tAc "SELECT count(*) FROM tenants WHERE tenant_id='rpo-demo-lost';")
  echo "     恢复后 tenants=${n_rec}（备份点=2），未备份行存活=${lost}（应=0，已随故障丢失）"
  check "恢复到备份点 tenants=2" "$([ "$n_rec" = 2 ] && echo 1 || echo 0)"
  check "备份后新增行确认丢失（RPO 窗口）" "$([ "$lost" = 0 ] && echo 1 || echo 0)"

  echo "$T_RTO_START" > "$TMP/t_rto_s"
  echo "$T_RTO_END" > "$TMP/t_rto_e"
}

certify() {
  echo "${c_bold}== 量化与达标认证 ==${c_off}"
  T_DUMP=$(cat "$TMP/t_dump"); T_FAIL=$(cat "$TMP/t_fail")
  T_RTO_S=$(cat "$TMP/t_rto_s"); T_RTO_E=$(cat "$TMP/t_rto_e")
  RPO_OBS=$("$PY" -c "print(f'{float('$T_FAIL')-float('$T_DUMP'):.3f}')")
  RTO_OBS=$("$PY" -c "print(f'{float('$T_RTO_E')-float('$T_RTO_S'):.3f}')")
  RPO_PASS=$("$PY" -c "print('true' if float('$RPO_OBS') <= $RPO_TARGET else 'false')")
  RTO_PASS=$("$PY" -c "print('true' if float('$RTO_OBS') <= $RTO_TARGET else 'false')")
  echo "     RPO 观测窗口=${RPO_OBS}s（目标 ≤${RPO_TARGET}s＝24h；生产由每日备份频率保证）"
  echo "     RTO 观测耗时=${RTO_OBS}s（目标 ≤${RTO_TARGET}s＝4h；工程恢复动作）"
  check "RPO ≤ 24h（观测 ${RPO_OBS}s ≤ ${RPO_TARGET}s）" "$([ "$RPO_PASS" = true ] && echo 1 || echo 0)"
  check "RTO ≤ 4h（观测 ${RTO_OBS}s ≤ ${RTO_TARGET}s）" "$([ "$RTO_PASS" = true ] && echo 1 || echo 0)"
  # 认证行（机器可读，docs/17 §7.4 登记同口径）。
  echo "RPO_RTO_CERT {\"rpo_target_seconds\":${RPO_TARGET},\"rpo_observed_seconds\":${RPO_OBS},\"rpo_pass\":${RPO_PASS},\"rto_target_seconds\":${RTO_TARGET},\"rto_observed_seconds\":${RTO_OBS},\"rto_pass\":${RTO_PASS}}"
}

run_all() {
  start_src
  migrate_src
  seed_and_backup
  inject_failure
  recover_timed
  certify
}

case "${1:-up}" in
  up)   run_all ;;
  down) cleanup; echo "已清理 $SRC / $DST"; exit 0 ;;
  *) echo "usage: $0 [up|down]（KEEP=1 跑完保留容器）"; exit 2 ;;
esac

echo "${c_bold}== 演练结果：${c_green}PASS=$pass${c_off}  ${c_red}FAIL=$fail${c_off} ==${c_off}"
[ "$fail" = 0 ]
