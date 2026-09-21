#!/usr/bin/env bash
# Q158 异机备份恢复端到端演练（docs/17 §7.2，02 C1.102）。
#
# Q146 落了每日 pg_dump（infra/backup/backup.sh，custom 格式 + compress=9）与
# 7 天保留，但「备份能否在一台全新的异机上完整恢复」这条腿从未演练过。本脚本
# 用两个相互独立的一次性 PG16 容器（不同容器/不同宿主端口/不同数据卷）验证：
#
#   源库 A：全链 alembic upgrade head 到当前 head（含全部迁移种子）+ 造一批覆盖
#           JSONB / timestamptz / 任务表 / 时序表的业务行；
#   备份  ：用 Q146 backup.sh 完全相同的 pg_dump（--format=custom --compress=9）；
#   异机 B：全新空库 drop/create 后 pg_restore --no-owner（模拟新机恢复）；
#   校验  ：迁移版本一致、业务表集合=60、全表逐表行数一致、索引/PK/FK/UQ 结构
#           指纹一致、pgvector 扩展与 vector 列一致、关键表整行内容逐字段一致、
#           配置种子一致、应用 ORM 栈连恢复库只读成功、对恢复库再 upgrade head
#           幂等 no-op。
#
# 不依赖构建应用镜像、不注入 LLM key（synthetic、不花真钱）、不触碰本机
# atlas-pg（宿主端口用 55440/55441）；脚本结束默认拆除两容器（KEEP=1 保留排查）。
#
# 用法（在 infra/ 目录，需本机 Docker；宿主需有 backend/.venv，含 alembic/asyncpg）：
#   ./restore-rehearsal.sh          # 全流程：起库→迁移→造数→备份→异机恢复→校验→拆除
#   ./restore-rehearsal.sh down     # 仅清理残留演练容器
#   KEEP=1 ./restore-rehearsal.sh   # 跑完保留两容器便于人工排查
set -uo pipefail

cd "$(dirname "$0")"
IMG=pgvector/pgvector:pg16
SRC=loom-restore-src
DST=loom-restore-dst
SPORT=${RESTORE_SRC_PORT:-55440}
DPORT=${RESTORE_DST_PORT:-55441}
BACKEND_DIR=../backend
PY="$BACKEND_DIR/.venv/bin/python"
ALEMBIC="$BACKEND_DIR/.venv/bin/alembic"
DSN_SQL_A="postgresql://loom:loom@localhost:${SPORT}/loom"
DSN_SQL_B="postgresql://loom:loom@localhost:${DPORT}/loom"
DSN_ALEMBIC_A="postgresql+asyncpg://loom:loom@localhost:${SPORT}/loom"
DSN_ALEMBIC_B="postgresql+asyncpg://loom:loom@localhost:${DPORT}/loom"
EXPECT_BIZ_TABLES=60   # docs/10 §4：head 0038 业务物理表 60（另加 alembic_version 共 61 张 public 表）
MIGRATION_COUNT=38     # 0001..0038 全链升级条数
TMP=$(mktemp -d)

c_green=$'\033[32m'; c_red=$'\033[31m'; c_bold=$'\033[1m'; c_off=$'\033[0m'
pass=0; fail=0
check() { # check <desc> <0|1>
  if [ "$2" = "1" ]; then echo "${c_green}  PASS${c_off} $1"; pass=$((pass+1));
  else echo "${c_red}  FAIL${c_off} $1"; fail=$((fail+1)); fi
}

cleanup() {
  docker rm -f "$SRC" "$DST" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap 'if [ "${KEEP:-0}" != "1" ]; then cleanup; fi' EXIT

pg_wait() { # pg_wait <container>
  for _ in $(seq 1 60); do
    if docker exec -e PGPASSWORD=loom "$1" pg_isready -h localhost -U loom >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

start_databases() {
  echo "${c_bold}== 起两个相互独立的一次性 PG16 容器（源 ${SPORT} / 异机 ${DPORT}）==${c_off}"
  docker rm -f "$SRC" "$DST" >/dev/null 2>&1 || true
  docker run -d --rm --name "$SRC" \
    -e POSTGRES_USER=loom -e POSTGRES_PASSWORD=loom -e POSTGRES_DB=loom \
    -p "${SPORT}:5432" "$IMG" >/dev/null
  docker run -d --rm --name "$DST" \
    -e POSTGRES_USER=loom -e POSTGRES_PASSWORD=loom -e POSTGRES_DB=loom \
    -p "${DPORT}:5432" "$IMG" >/dev/null
  ready=1
  if pg_wait "$SRC"; then echo "     源库 A ready"; else echo "     源库 A 未就绪"; ready=0; fi
  if pg_wait "$DST"; then echo "     异机库 B ready"; else echo "     异机库 B 未就绪"; ready=0; fi
  docker ps --filter "name=loom-restore-" --format '{{.Names}}\t{{.Status}}' | sed 's/^/     /'
  check "源库 A / 异机库 B 均就绪" "$ready"
}

migrate_source() {
  echo "${c_bold}== 源库 A：全链 alembic upgrade head（含全部迁移种子）==${c_off}"
  ( cd "$BACKEND_DIR" && LOOM_DATABASE_DSN="$DSN_ALEMBIC_A" "$ALEMBIC" upgrade head ) \
    > "$TMP/migrate.log" 2>&1
  rc=$?
  tail -2 "$TMP/migrate.log" | sed 's/^/     /'
  n_up=$(grep -c "Running upgrade" "$TMP/migrate.log" || true)
  echo "     Running upgrade 条数=${n_up}（期望 ${MIGRATION_COUNT}），rc=${rc}"
  check "源库 A 全链迁移成功（rc=0）" "$([ $rc = 0 ] && echo 1 || echo 0)"
  check "源库 A 升级条数=${MIGRATION_COUNT}" "$([ "$n_up" = "$MIGRATION_COUNT" ] && echo 1 || echo 0)"
}

seed_source() {
  echo "${c_bold}== 源库 A：造覆盖 JSONB/timestamptz/任务/时序的业务行 ==${c_off}"
  ( cd "$BACKEND_DIR" && "$PY" - "$DSN_SQL_A" <<'PY'
import asyncio, sys
import asyncpg
from datetime import datetime, timezone, timedelta

async def main(dsn):
    c = await asyncpg.connect(dsn)
    try:
        await c.execute(
            "INSERT INTO tenants(tenant_id,name,plan,status,monthly_token_quota,detail,created_by) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)",
            "restore-demo-alpha", "Restore Alpha", "pro", "active", None,
            '{"restore_rehearsal": true, "n": 1}', "restore-rehearsal")
        await c.execute(
            "INSERT INTO tenants(tenant_id,name,plan,status,monthly_token_quota,detail,created_by) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)",
            "restore-demo-beta", "Restore Beta", "trial", "trial", 500000,
            '{"restore_rehearsal": true, "n": 2}', "restore-rehearsal")
        jobs = [
            ("rj-csv-1", "restore-demo-alpha", "csv", "completed", 12,
             "fcw-restore-alpha.csv", "restore-rehearsal", datetime.now(timezone.utc)),
            ("rj-json-2", "restore-demo-alpha", "json", "completed", 7,
             "fcw-restore-alpha.json", "restore-rehearsal", datetime.now(timezone.utc)),
            ("rj-csv-3", "restore-demo-beta", "csv", "failed", 0,
             "fcw-restore-beta.csv", "restore-rehearsal", None),
        ]
        await c.executemany(
            "INSERT INTO export_jobs(job_id,tenant_id,format,status,row_count,file_name,"
            "requested_by,error,completed_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            [
                (j[0], j[1], j[2], j[3], j[4], j[5], j[6],
                 None if j[3] == "completed" else "boom (restore rehearsal)", j[7])
                for j in jobs
            ],
        )
        base = datetime(2026, 9, 21, tzinfo=timezone.utc)
        effects = [
            ("re-ext-1", "https://example.invalid/post/1", base + timedelta(hours=1),
             '{"plays":100,"likes":3,"read_rate":0.21}', "orphan"),
            ("re-ext-2", "https://example.invalid/post/2", base + timedelta(hours=2),
             None, "orphan"),
            ("re-ext-3", "https://example.invalid/post/3", base + timedelta(hours=3),
             '{"conversions":2,"read_rate":0.05}', "orphan"),
        ]
        await c.executemany(
            "INSERT INTO effect_records(record_id,source,external_content_id,platform_post_id,"
            "captured_at,metrics,status,received_by) VALUES "
            "($1,'restore-rehearsal-agent',$2,$3,$4,$5::jsonb,$6,'restore-rehearsal')",
            [(f"rec-{i}", e[0], e[1], e[2], e[3], e[4]) for i, e in enumerate(effects, 1)],
        )
        nt = await c.fetchval("SELECT count(*) FROM tenants")
        nj = await c.fetchval("SELECT count(*) FROM export_jobs")
        ne = await c.fetchval("SELECT count(*) FROM effect_records")
        print(f"SEED tenants={nt} export_jobs={nj} effect_records={ne}")
    finally:
        await c.close()

asyncio.run(main(sys.argv[1]))
PY
  ) > "$TMP/seed.log" 2>&1
  ssrc=$?
  sed 's/^/     /' "$TMP/seed.log"
  check "源库 A 造数成功（tenants=2/export_jobs=3/effect_records=3）" \
    "$([ $ssrc = 0 ] && grep -q '^SEED tenants=2 export_jobs=3 effect_records=3' "$TMP/seed.log" && echo 1 || echo 0)"
}

backup_source() {
  echo "${c_bold}== 备份：Q146 同款 pg_dump（custom / compress=9）==${c_off}"
  docker exec -e PGPASSWORD=loom "$SRC" \
    pg_dump -h localhost -U loom -d loom --no-password --format=custom --compress=9 \
    --file=/tmp/loom-restore.dump
  docker cp "$SRC":/tmp/loom-restore.dump "$TMP/loom.dump"
  sz=$(stat -f%z "$TMP/loom.dump" 2>/dev/null || stat -c%s "$TMP/loom.dump")
  echo "     dump 字节数=$sz"
  check "dump 非空（$sz bytes）" "$([ "$sz" -gt 1000 ] && echo 1 || echo 0)"
  # custom 格式可用 pg_restore --list 列出 TOC（plain SQL 则不行），佐证格式正确。
  docker cp "$TMP/loom.dump" "$DST":/tmp/loom.dump
  if docker exec -e PGPASSWORD=loom "$DST" pg_restore -h localhost -U loom --list /tmp/loom.dump \
      > "$TMP/toc.log" 2>&1; then
    toc=$(grep -c "TABLE DATA" "$TMP/toc.log" || true)
    echo "     TOC TABLE DATA 条目=$toc"
    check "dump 为 custom 格式且可列 TOC（TABLE DATA 条目>0）" "$([ "$toc" -gt 0 ] && echo 1 || echo 0)"
  else
    check "dump 为 custom 格式且可列 TOC" 0
  fi
}

restore_to_destination() {
  echo "${c_bold}== 异机库 B：drop/create 空库后 pg_restore（模拟新机恢复）==${c_off}"
  docker exec -e PGPASSWORD=loom "$DST" psql -h localhost -U loom -d postgres -v ON_ERROR_STOP=1 \
    -c "REVOKE CONNECT ON DATABASE loom FROM public;
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='loom' AND pid<>pg_backend_pid();
        DROP DATABASE IF EXISTS loom;
        CREATE DATABASE loom OWNER loom;" > "$TMP/recreate.log" 2>&1
  docker exec -e PGPASSWORD=loom "$DST" \
    pg_restore -h localhost -U loom -d loom --no-owner --no-password \
    /tmp/loom.dump > "$TMP/restore.log" 2>&1
  rc=$?
  errs=$(grep -cE "^pg_restore:.*error" "$TMP/restore.log" || true)
  echo "     pg_restore rc=${rc}，error 行=${errs}"
  grep -E "error|fatal" -i "$TMP/restore.log" | head -5 | sed 's/^/     /'
  check "pg_restore rc=0" "$([ $rc = 0 ] && echo 1 || echo 0)"
  check "pg_restore 无 error 行" "$([ "$errs" = 0 ] && echo 1 || echo 0)"
}

verify() {
  echo "${c_bold}== 校验：源库 A 与异机恢复库 B 逐项比对 ==${c_off}"
  ( cd "$BACKEND_DIR" && "$PY" - "$DSN_SQL_A" "$DSN_SQL_B" "$EXPECT_BIZ_TABLES" <<'PY'
import asyncio, json, sys
import asyncpg

A_DSN, B_DSN, EXPECT_BIZ = sys.argv[1], sys.argv[2], int(sys.argv[3])
results = []   # (desc, ok, detail)
def ck(desc, ok, detail=""):
    results.append((desc, bool(ok), detail))

def norm(v):
    return json.dumps(v, sort_keys=True, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))

async def main():
    a = await asyncpg.connect(A_DSN)
    b = await asyncpg.connect(B_DSN)
    try:
        # 1) alembic 版本：各单行、非空、A==B。
        va = await a.fetch("SELECT version_num FROM alembic_version")
        vb = await b.fetch("SELECT version_num FROM alembic_version")
        va = [r["version_num"] for r in va]; vb = [r["version_num"] for r in vb]
        ck("alembic_version 单行非空且 A==B", len(va)==1==len(vb) and va==vb and va[0],
           f"A={va} B={vb}")

        # 2) public 基表集合：业务表=60、含版本表共 61、A==B。
        async def tables(c):
            rows = await c.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
            return [r["table_name"] for r in rows]
        ta, tb = await tables(a), await tables(b)
        biz_a = [t for t in ta if t != "alembic_version"]
        ck("业务表集合 A==B", set(ta)==set(tb), f"A={len(ta)} B={len(tb)}")
        ck(f"业务物理表={EXPECT_BIZ}（含版本表共 {EXPECT_BIZ+1}）",
           len(biz_a)==EXPECT_BIZ and len(ta)==EXPECT_BIZ+1, f"业务表={len(biz_a)} 总表={len(ta)}")

        # 3) 全表逐表行数 A==B。
        async def counts(c, ts):
            out = {}
            for t in ts:
                out[t] = await c.fetchval(f'SELECT count(*) FROM "{t}"')
            return out
        ca, cb = await counts(a, ta), await counts(b, tb)
        diff = {t: (ca[t], cb.get(t)) for t in ta if ca[t] != cb.get(t)}
        nonempty = sum(1 for n in ca.values() if n > 0)
        ck("全表逐表行数 A==B", not diff, f"非空表={nonempty}，差异={diff if diff else '无'}")
        ck("演练造数行数（tenants=2/export_jobs=3/effect_records=3）",
           ca.get("tenants")==2 and ca.get("export_jobs")==3 and ca.get("effect_records")==3,
           f"tenants={ca.get('tenants')} jobs={ca.get('export_jobs')} effects={ca.get('effect_records')}")
        ck("迁移种子非空（config_items>=54）", ca.get("config_items",0)>=54,
           f"config_items={ca.get('config_items')}")

        # 4) 结构指纹：索引 / PK / FK / UQ 计数 A==B。
        async def fingerprint(c):
            idx = await c.fetchval("SELECT count(*) FROM pg_indexes WHERE schemaname='public'")
            async def ctype(kind):
                return await c.fetchval(
                    "SELECT count(*) FROM information_schema.table_constraints "
                    "WHERE table_schema='public' AND constraint_type=$1", kind)
            pk = await ctype("PRIMARY KEY"); fk = await ctype("FOREIGN KEY"); uq = await ctype("UNIQUE")
            vec_cols = await c.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema='public' AND udt_name='vector'")
            ext = [r["extname"] for r in await c.fetch("SELECT extname FROM pg_extension")]
            return dict(indexes=idx, pk=pk, fk=fk, uq=uq, vector_cols=vec_cols,
                        has_vector_ext="vector" in ext)
        fa, fb = await fingerprint(a), await fingerprint(b)
        ck("结构指纹（索引/PK/FK/UQ/vector 列）A==B", fa==fb, f"A={fa} B={fb}")
        ck("pgvector 扩展在恢复库就位且 vector 列>0",
           fb.get("has_vector_ext") and fb.get("vector_cols",0)>0, f"B={fb}")

        # 5) 关键表整行内容逐字段一致（JSONB / timestamptz / 可空 metrics）。
        async def rows(c, table, key, ids):
            rs = await c.fetch(f'SELECT * FROM "{table}" WHERE {key} = ANY($1) ORDER BY {key}', ids)
            return {r[key]: norm(dict(r)) for r in rs}
        cases = [
            ("tenants", "tenant_id", ["restore-demo-alpha", "restore-demo-beta"]),
            ("export_jobs", "job_id", ["rj-csv-1", "rj-json-2", "rj-csv-3"]),
            ("effect_records", "record_id", ["rec-1", "rec-2", "rec-3"]),
        ]
        for table, key, ids in cases:
            ra, rb = await rows(a, table, key, ids), await rows(b, table, key, ids)
            ck(f"{table} 演练行整行内容 A==B（{len(ids)} 行）", ra==rb and len(ra)==len(ids),
               f"匹配={len(set(ra)&set(rb))}/{len(ids)}")

        # 6) 配置种子：键集合与关键阈值 A==B。
        async def cfg(c):
            qc = await c.fetchval("SELECT count(*) FROM config_items")
            qv = await c.fetchval(
                "SELECT value FROM config_items WHERE key='content.ai_quality_threshold'")
            return qc, qv
        cca, qva = await cfg(a); ccb, qvb = await cfg(b)
        ck("config_items 行数与 QC 阈值 A==B", cca==ccb and norm(qva)==norm(qvb),
           f"行数 {cca}/{ccb}，QC {qva!r}/{qvb!r}")
    finally:
        await a.close(); await b.close()

    for desc, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"{mark} | {desc}" + (f" | {detail}" if detail else ""))
    bad = [d for d, ok, _ in results if not ok]
    print(f"VERIFY_TOTAL {len(results)} VERIFY_FAIL {len(bad)}")
    sys.exit(1 if bad else 0)

asyncio.run(main())
PY
  ) | tee "$TMP/verify.log" | sed 's/^/     /'
  vfail=$(grep "^VERIFY_TOTAL" "$TMP/verify.log" | sed 's/.*VERIFY_FAIL //')
  vtotal=$(grep "^VERIFY_TOTAL" "$TMP/verify.log" | awk '{print $2}')
  check "比对校验全部通过（${vtotal:-?} 项，FAIL=${vfail:-?}）" "$([ "${vfail:-1}" = 0 ] && echo 1 || echo 0)"
}

app_read_check() {
  echo "${c_bold}== 应用 ORM 栈连恢复库 B 只读冒烟 ==${c_off}"
  ( cd "$BACKEND_DIR" && LOOM_DATABASE_DSN="$DSN_ALEMBIC_B" "$PY" - <<'PY'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import app.main  # noqa: F401  经 main 导入链注册全量 ORM

async def main():
    eng = create_async_engine(__import__("os").environ["LOOM_DATABASE_DSN"])
    try:
        async with eng.connect() as conn:
            for label, sql in [
                ("tenants", "SELECT count(*) FROM tenants"),
                ("export_jobs", "SELECT count(*) FROM export_jobs"),
                ("effect_records", "SELECT count(*) FROM effect_records"),
                ("config_qc", "SELECT value FROM config_items WHERE key='content.ai_quality_threshold'"),
            ]:
                v = (await conn.execute(text(sql))).scalar()
                print(f"READ {label}={v}")
    finally:
        await eng.dispose()

asyncio.run(main())
PY
  ) > "$TMP/appread.log" 2>&1
  arc=$?
  sed 's/^/     /' "$TMP/appread.log"
  check "应用栈 import app.main + ORM 连恢复库只读成功" "$([ $arc = 0 ] && echo 1 || echo 0)"
}

idempotent_reupgrade() {
  echo "${c_bold}== 恢复库 B 再跑一次 alembic upgrade head（应幂等 no-op）==${c_off}"
  ( cd "$BACKEND_DIR" && LOOM_DATABASE_DSN="$DSN_ALEMBIC_B" "$ALEMBIC" upgrade head ) \
    > "$TMP/reupgrade.log" 2>&1
  rc=$?
  n_up=$(grep -c "Running upgrade" "$TMP/reupgrade.log" || true)
  tail -1 "$TMP/reupgrade.log" | sed 's/^/     /'
  check "恢复库 upgrade head rc=0" "$([ $rc = 0 ] && echo 1 || echo 0)"
  check "恢复库已在 head、无新增升级（Running upgrade=0）" "$([ "$n_up" = 0 ] && echo 1 || echo 0)"
}

run_all() {
  start_databases
  migrate_source
  seed_source
  backup_source
  restore_to_destination
  verify
  app_read_check
  idempotent_reupgrade
}

case "${1:-up}" in
  up)   run_all ;;
  down) cleanup; echo "已清理 $SRC / $DST"; exit 0 ;;
  *) echo "usage: $0 [up|down]（KEEP=1 跑完保留容器）"; exit 2 ;;
esac

echo "${c_bold}== 演练结果：${c_green}PASS=$pass${c_off}  ${c_red}FAIL=$fail${c_off} ==${c_off}"
[ "$fail" = 0 ]
