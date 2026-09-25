#!/usr/bin/env bash
# Q157 真多副本/多 worker 持续负载端到端演练（docs/17 §7，02 C1.101）。
#
# 起 2 个 backend 副本 + 真 PG/Redis（不注入 LLM key，全程 synthetic 不花真钱），
# 自动验证四件事并打印结论：
#   1. 多副本并发启动迁移：PG 咨询锁串行化，两副本合计恰好全量升级一次、无 DDL 竞争；
#   2. 导出 worker 同消费组两 consumer 分片：N 个 job 不重不漏、两副本都参与；
#   3. SLA/restock leader 锁互斥：并发手工 /run，有 200 也有 409、绝无 5xx；
#   4. 配置缓存失效广播跨副本：PUT 后对端副本日志出现 reload key。
#
# 用法（在 infra/ 目录）：
#   ./ha-rehearsal.sh up       # 构建/起栈并跑全部演练（默认）
#   ./ha-rehearsal.sh run      # 栈已在跑，只重跑演练步骤
#   ./ha-rehearsal.sh logs     # 打印两副本关键日志
#   ./ha-rehearsal.sh down     # 拆除演练栈（加 -v 才清数据卷）
set -uo pipefail

# Q200 #33：backend entrypoint 对空 LOOM_MASTER_KEY 启动即 fail-fast，
# 彩排不注入真 Key，统一用演练专用测试值（非生产密钥）。
export LOOM_MASTER_KEY="${LOOM_MASTER_KEY:-loom-rehearsal-only-master-key}"

# Q203 #33 残留 1：compose 里两个 datastore 口令已无弱默认（不给就起不来），
# 彩排同样注入演练专用值；刻意不用 ${VAR:?}——解析期求值会打断没设变量的 overlay。
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-loom-rehearsal-only-pg}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-loom-rehearsal-only-minio}"

cd "$(dirname "$0")"
PROJECT=loom-ha
FILES=(-f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.ha.yml)
COMPOSE="docker compose ${FILES[*]} -p ${PROJECT}"
JOBS=${HA_JOBS:-24}
ADMIN='{"id":"ha-rehearsal","roles":["platform_admin"]}'
TENANT=ha-rehearsal
C1="${PROJECT}-backend-1"
C2="${PROJECT}-backend-2"
MIGRATION_COUNT=38   # 0001..0038 全量升级条数（串行成功时两副本合计恰为此值）

c_green=$'\033[32m'; c_red=$'\033[31m'; c_bold=$'\033[1m'; c_off=$'\033[0m'
pass=0; fail=0
check() { # check <desc> <0|1>
  if [ "$2" = "1" ]; then echo "${c_green}  PASS${c_off} $1"; pass=$((pass+1));
  else echo "${c_red}  FAIL${c_off} $1"; fail=$((fail+1)); fi
}

# 容器内 HTTP 调用（引号 heredoc：脚本体不经 shell 展开，参数全走 argv）。
# 打印 "STATUS <code>" 行 + body。
ha_api() { # ha_api <container> <method> <path> [body]
  docker exec -i "$1" python - "$2" "$3" "${4:-}" <<'PY'
import sys, json, urllib.request, urllib.error
method, path, body = sys.argv[1], sys.argv[2], sys.argv[3]
req = urllib.request.Request(
    "http://localhost:8000" + path,
    data=(body.encode() if body else None),
    method=method,
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print("STATUS", r.status); print(r.read().decode())
except urllib.error.HTTPError as e:
    print("STATUS", e.code); print(e.read().decode())
PY
}

up_stack() {
  echo "${c_bold}== 起栈（2 backend 副本 + 真 PG/Redis，synthetic）==${c_off}"
  # Q157 聚焦后端多副本：frontend SSR 已在 Q147 验过，不随本演练构建。
  $COMPOSE up -d --build postgres redis backend
  echo "等待两副本 healthy ..."
  for _ in $(seq 1 60); do
    ready=$(docker ps --filter "name=${PROJECT}-backend-" --filter health=healthy -q | wc -l | tr -d ' ')
    [ "$ready" = "2" ] && break
    sleep 3
  done
  docker ps --filter "name=${PROJECT}-" --format '{{.Names}}\t{{.Status}}'
  ready=$(docker ps --filter "name=${PROJECT}-backend-" --filter health=healthy -q | wc -l | tr -d ' ')
  check "两副本均 healthy（迁移成功后才起 uvicorn）" "$([ "$ready" = "2" ] && echo 1 || echo 0)"
}

stage_migration() {
  echo "${c_bold}== 1) 迁移咨询锁串行化 ==${c_off}"
  u1=$(docker logs "$C1" 2>&1 | grep -c "Running upgrade")
  u2=$(docker logs "$C2" 2>&1 | grep -c "Running upgrade")
  echo "     副本1 升级条数=$u1  副本2 升级条数=$u2  合计=$((u1+u2))（期望 ${MIGRATION_COUNT}）"
  docker logs "$C2" 2>&1 | grep "Running upgrade" | tail -1 | sed 's/^/     尾条: /'
  check "两副本合计恰好全量升级一次（一个全量、另一个阻塞后 no-op）" \
    "$([ $((u1+u2)) = "$MIGRATION_COUNT" ] && echo 1 || echo 0)"
  ddl=0
  for c in "$C1" "$C2"; do
    docker logs "$c" 2>&1 | grep -qiE "relation .* already exists|duplicate key value|column .* already exists|multiple heads" && ddl=1
  done
  check "无并发 DDL 竞争报错（already exists / duplicate key / multiple heads）" \
    "$([ "$ddl" = "0" ] && echo 1 || echo 0)"
}

stage_export_sharding() {
  echo "${c_bold}== 2) 导出 worker 消费组分片（${JOBS} jobs）==${c_off}"
  # 在副本1内创建 N 个 job 并轮询到终态；JOBS/TENANT 经 argv 传入。
  out=$(docker exec -i "$C1" python - "$JOBS" "$TENANT" <<'PY'
import sys, json, time, urllib.request
jobs_n, tenant = int(sys.argv[1]), sys.argv[2]
def call(method, path, body=None):
    req = urllib.request.Request("http://localhost:8000"+path,
        data=json.dumps(body).encode() if body else None, method=method,
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
actor = {"id":"ha-rehearsal","roles":[]}
for _ in range(jobs_n):
    call("POST","/api/exports/jobs",{"tenant_id":tenant,"format":"csv","actor":actor})
stat, ids = {}, set()
for _ in range(60):
    view = call("GET", f"/api/exports/jobs?tenant_id={tenant}")
    stat = {}
    for j in view["jobs"]: stat[j["status"]] = stat.get(j["status"],0)+1
    ids = {j["job_id"] for j in view["jobs"]}
    if stat.get("queued",0)==0 and stat.get("running",0)==0: break
    time.sleep(1)
print("STAT", json.dumps(stat))
print("UNIQUE", len(ids))
PY
)
  echo "$out" | sed 's/^/     /'
  completed=$(echo "$out" | grep "^STAT" | sed 's/STAT //' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("completed",0))')
  unique=$(echo "$out" | grep "^UNIQUE" | awk '{print $2}')
  check "全部 ${JOBS} job completed（无 failed/卡住）" "$([ "$completed" = "$JOBS" ] && echo 1 || echo 0)"
  check "job_id 唯一不重复（不重不漏）" "$([ "$unique" = "$JOBS" ] && echo 1 || echo 0)"

  for c in "$C1" "$C2"; do
    echo "-- $c consumer 完成分布:"
    docker logs "$c" 2>&1 | grep -oE "consumer=export-[0-9a-f]+" | sort | uniq -c | sed 's/^/     /'
  done
  n1=$(docker logs "$C1" 2>&1 | grep -cE "consumer=export-[0-9a-f]+ completed job")
  n2=$(docker logs "$C2" 2>&1 | grep -cE "consumer=export-[0-9a-f]+ completed job")
  echo "     副本1 completed=$n1  副本2 completed=$n2  合计=$((n1+n2))"
  check "两副本 consumer 都处理了 job（真分片）" "$([ "$n1" -gt 0 ] && [ "$n2" -gt 0 ] && echo 1 || echo 0)"
  check "两副本 completed 合计=${JOBS}（每条恰处理一次）" "$([ $((n1+n2)) = "$JOBS" ] && echo 1 || echo 0)"
  # Q157 修复后空轮询不应再刷 tick failed traceback。
  tickfail=0
  for c in "$C1" "$C2"; do
    docker logs "$c" 2>&1 | grep -q "export worker tick failed" && tickfail=1
  done
  check "空轮询 BLOCK 超时不再报 tick failed（read_new 归一为空）" "$([ "$tickfail" = "0" ] && echo 1 || echo 0)"
}

stage_leader_lock() {
  echo "${c_bold}== 3) SLA/restock leader 锁互斥（每副本 4 并发）==${c_off}"
  for endpoint in sla restock; do
    tmp=$(mktemp -d)
    pids=()
    run_body="{\"actor\":${ADMIN}}"   # /run 的 _SweepBody/_RestockBody 要 {"actor": Actor}
    for rep in 1 2; do
      for k in 1 2 3 4; do
        c="${PROJECT}-backend-${rep}"
        ( ha_api "$c" POST "/api/admin/${endpoint}/run" "$run_body" ) > "$tmp/r${rep}_$k" &
        pids+=($!)
      done
    done
    for p in "${pids[@]}"; do wait "$p"; done
    codes=$(grep -h "^STATUS" "$tmp"/* | awk '{print $2}' | sort | uniq -c | tr '\n' ';')
    n200=$(grep -h "^STATUS" "$tmp"/* | awk '{print $2}' | grep -c 200 || true)
    n409=$(grep -h "^STATUS" "$tmp"/* | awk '{print $2}' | grep -c 409 || true)
    n5xx=$(grep -h "^STATUS" "$tmp"/* | awk '$2 ~ /^5/ {c++} END {print c+0}')
    echo "     /api/admin/${endpoint}/run 状态码分布: $codes"
    check "${endpoint}: 至少一个执行(200)" "$([ "$n200" -ge 1 ] && echo 1 || echo 0)"
    check "${endpoint}: 有抢锁失败(409)" "$([ "$n409" -ge 1 ] && echo 1 || echo 0)"
    check "${endpoint}: 无 5xx" "$([ "$n5xx" = 0 ] && echo 1 || echo 0)"
    rm -rf "$tmp"
  done
}

stage_config_broadcast() {
  echo "${c_bold}== 4) 配置缓存失效广播跨副本 ==${c_off}"
  key=content.ai_quality_threshold
  # 管理面读口（Q113/Q118）actor 走 query 参数；写口 actor 在 body。
  orig=$(ha_api "$C1" GET "/api/admin/config/$key?actor_id=ha-rehearsal&roles=platform_admin" \
    | tail -n +2 | python3 -c 'import sys,json;print(json.load(sys.stdin)["value"])' 2>/dev/null)
  echo "     原值=${orig:-<unknown>}；经副本1改为 0.82"
  s=$(ha_api "$C1" PUT "/api/admin/config/$key" \
    "{\"value\":0.82,\"change_note\":\"Q157 HA rehearsal\",\"actor\":$ADMIN}" | grep "^STATUS" | awk '{print $2}')
  check "副本1 PUT 配置 200" "$([ "$s" = "200" ] && echo 1 || echo 0)"
  sleep 3
  docker logs "$C2" 2>&1 | grep "reloaded key $key" | tail -2 | sed 's/^/     副本2 /'
  hit=$(docker logs "$C2" 2>&1 | grep -c "reloaded key $key")
  check "对端副本2 收到广播并 reload key" "$([ "$hit" -ge 1 ] && echo 1 || echo 0)"
  if [ -n "${orig:-}" ]; then
    ha_api "$C1" PUT "/api/admin/config/$key" \
      "{\"value\":$orig,\"change_note\":\"Q157 restore\",\"actor\":$ADMIN}" | grep "^STATUS" >/dev/null
    echo "     已还原为 ${orig}"
  fi
}

print_logs() {
  for c in "$C1" "$C2"; do
    echo "===== $c（worker/锁/广播关键行）====="
    docker logs "$c" 2>&1 | grep -iE "export worker starting|completed job|reloaded key|already running|tick failed" | tail -15
  done
}

case "${1:-up}" in
  up)    up_stack; stage_migration; stage_export_sharding; stage_leader_lock; stage_config_broadcast ;;
  run)   stage_migration; stage_export_sharding; stage_leader_lock; stage_config_broadcast ;;
  logs)  print_logs ;;
  down)  $COMPOSE down ;;
  *) echo "usage: $0 up|run|logs|down"; exit 2 ;;
esac

echo "${c_bold}== 演练结果：${c_green}PASS=$pass${c_off}  ${c_red}FAIL=$fail${c_off} ==${c_off}"
[ "$fail" = 0 ]
