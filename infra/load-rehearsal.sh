#!/usr/bin/env bash
# Q173 持续高压负载端到端演练（docs/17 §7.3，02 C1.117）。
#
# Q157 ha-rehearsal 只做短时突发（24 jobs + 瞬时锁竞争）；本演练在同一 HA 形态
# （2 backend 副本 + 真 PG/Redis，synthetic 不花真钱）下施加**持续数分钟**的混合
# 负载，验证：
#   1. 两副本全程 healthy、无重启 / OOMKill；
#   2. export worker 消费组在持续入流下来一单处理一单：提交数 == completed 数，
#      无 failed、无丢单、队列不无限堆积（最终 drain 干净）；
#   3. 持续 SLA/restock leader 锁抢占期间只有 200/409，绝无 5xx；
#   4. 全程日志无未处理 Traceback。
#
# 用法（在 infra/ 目录）：
#   ./load-rehearsal.sh up     # 起栈并跑持续负载（默认）
#   ./load-rehearsal.sh run    # 栈已在跑，只重跑负载
#   ./load-rehearsal.sh down   # 拆除（加 -v 清卷）
#
# 可调环境变量（运维值，非 Q9 旋钮）：
#   LOOM_LOAD_MINUTES=5        持续时长
#   LOOM_LOAD_RATE=1.0         每副本每秒提交 export job 数（两副本合计 2x）
#   LOOM_CHURN_EVERY=2         leader /run 抢占间隔（秒）
set -uo pipefail

# Q200 #33：backend entrypoint 对空 LOOM_MASTER_KEY 启动即 fail-fast，
# 彩排不注入真 Key，统一用演练专用测试值（非生产密钥）。
export LOOM_MASTER_KEY="${LOOM_MASTER_KEY:-loom-rehearsal-only-master-key}"

cd "$(dirname "$0")"
PROJECT=loom-load
FILES=(-f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.ha.yml)
COMPOSE="docker compose ${FILES[*]} -p ${PROJECT}"
MINUTES=${LOOM_LOAD_MINUTES:-5}
RATE=${LOOM_LOAD_RATE:-1.0}
CHURN_EVERY=${LOOM_CHURN_EVERY:-2}
BURST=${LOOM_CHURN_BURST:-8}
ADMIN='{"id":"load-rehearsal","roles":["platform_admin"]}'
TENANT="load-rehearsal-$(date +%s)"
C1="${PROJECT}-backend-1"
C2="${PROJECT}-backend-2"
BACKEND_IMAGE="${PROJECT}-backend"
NET="${PROJECT}_default"
# driver/sampler 全部跑在一次性隔离容器（--rm）里，绝不 docker exec 进 app 容器：
# ① 隔离内存与崩溃——driver 自身的 OOM 不会在 app 容器上钉 OOMKilled 标记；
# ② 不制造僵尸（app 容器 PID1 不 reaper）；③ backend:8000 在副本间 DNS 负载均衡。
BASE="http://backend:8000"
DRIVER_MEMORY=${LOOM_DRIVER_MEMORY:-1g}
TMP=$(mktemp -d)
DUR_SECS=$(awk -v m="$MINUTES" 'BEGIN{printf "%d", m*60}')

c_green=$'\033[32m'; c_red=$'\033[31m'; c_bold=$'\033[1m'; c_off=$'\033[0m'
pass=0; fail=0
check() { # check <desc> <0|1>
  if [ "$2" = "1" ]; then echo "${c_green}  PASS${c_off} $1"; pass=$((pass+1));
  else echo "${c_red}  FAIL${c_off} $1"; fail=$((fail+1)); fi
}

trap 'rm -rf "$TMP"' EXIT

up_stack() {
  echo "${c_bold}== 起栈（2 backend 副本 + 真 PG/Redis，synthetic）==${c_off}"
  $COMPOSE up -d --build postgres redis backend
  echo "等待两副本 healthy ..."
  for _ in $(seq 1 60); do
    ready=$(docker ps --filter "name=${PROJECT}-backend-" --filter health=healthy -q | wc -l | tr -d ' ')
    [ "$ready" = "2" ] && break
    sleep 3
  done
  docker ps --filter "name=${PROJECT}-" --format '{{.Names}}\t{{.Status}}'
  ready=$(docker ps --filter "name=${PROJECT}-backend-" --filter health=healthy -q | wc -l | tr -d ' ')
  check "两副本均 healthy" "$([ "$ready" = "2" ] && echo 1 || echo 0)"
}

# 容器内混合负载驱动器。argv: duration pace churn churn_every tenant admin。
# 一个驱动 = 一个副本的全部入流量：按 pace 提交 export job（producer），穿插只读
# GET（reader）；churn=1 时每 churn_every 秒打一次 SLA/restock /run（锁抢占）。
# 结束打印一行 JSON 计数器。
run_driver() { # run_driver <churn 0|1> <outfile>
  docker run --rm -i --entrypoint python --network "$NET" --memory "$DRIVER_MEMORY" \
    "$BACKEND_IMAGE" - "$MINUTES" "$RATE" "$1" "$CHURN_EVERY" "$BURST" "$TENANT" "$ADMIN" "$BASE" > "$2" <<'PY'
import sys, json, time, random, urllib.request, urllib.error
minutes, rate, churn, churn_every, BURST, tenant, admin, base = (
    float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3]),
    float(sys.argv[4]), int(sys.argv[5]), sys.argv[6], json.loads(sys.argv[7]),
    sys.argv[8],
)
duration = minutes * 60
c = {"submitted": 0, "post_fail": 0, "reads": 0, "read_fail": 0,
     "run200": 0, "run409": 0, "run_other": 0, "http5xx": 0}

def call(method, path, body=None, timeout=30):
    req = urllib.request.Request(base+path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method, headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

interval = 1.0 / rate if rate > 0 else 0
deadline = time.monotonic() + duration
last_churn = 0.0
actor = {"id":"load-rehearsal","roles":[]}
while time.monotonic() < deadline:
    # producer：提交一个 export job（csv，空租户数据，下载按参数重渲染的幂等作业）
    s, _ = call("POST", "/api/exports/jobs",
                {"tenant_id":tenant,"format":"csv","actor":actor})
    if 200 <= s < 300: c["submitted"] += 1
    else:
        c["post_fail"] += 1
        if s >= 500: c["http5xx"] += 1
    # reader：job 列表 / token 成本驾驶舱（只读；列表显式大 limit 绕过默认分页 50）
    path = random.choice([
        f"/api/exports/jobs?tenant_id={tenant}&limit=200",
        "/api/admin/dashboards/token-cost?actor_id=load-rehearsal&roles=platform_admin",
    ])
    s, _ = call("GET", path)
    if 200 <= s < 300: c["reads"] += 1
    else:
        c["read_fail"] += 1
        if s >= 500: c["http5xx"] += 1
    # churner：leader 锁抢占——两副本同时在每个 tick 并发扇出 BURST 个
    # SLA/restock /run（同 ha-rehearsal 的并发竞争口径），并发抢锁必生 409。
    if churn and time.monotonic() - last_churn >= churn_every:
        last_churn = time.monotonic()
        from concurrent.futures import ThreadPoolExecutor
        def one(ep):
            return call("POST", f"/api/admin/{ep}/run", {"actor":admin})
        eps = ["sla", "restock"] * (BURST // 2)
        with ThreadPoolExecutor(max_workers=BURST) as ex:
            for s, _ in ex.map(one, eps):
                if s == 200: c["run200"] += 1
                elif s == 409: c["run409"] += 1
                else:
                    c["run_other"] += 1
                    if s >= 500: c["http5xx"] += 1
    if interval: time.sleep(interval)
print("JSON", json.dumps(c))
PY
}

sample_health() { # 每 30s 采样：健康副本数 + 队列深度 + completed/failed
  local elapsed=$1
  local healthy
  healthy=$(docker ps --filter "name=${PROJECT}-backend-" --filter health=healthy -q | wc -l | tr -d ' ')
  local q
  q=$(docker run --rm -i --entrypoint python --network "$NET" "$BACKEND_IMAGE" - "$TENANT" "$BASE" <<'PY'
import sys, json, urllib.request
tenant, base = sys.argv[1], sys.argv[2]
def all_jobs():
    out, off = [], 0
    while True:
        with urllib.request.urlopen(
            f"{base}/api/exports/jobs?tenant_id={tenant}&limit=200&offset={off}",
            timeout=30) as r:
            page = json.loads(r.read())["jobs"]
        out.extend(page)
        if len(page) < 200: break
        off += 200
    return out
try:
    jobs = all_jobs()
except Exception:
    print("queue=?"); raise SystemExit
stat = {}
for j in jobs: stat[j["status"]] = stat.get(j["status"],0)+1
print(f"queued={stat.get('queued',0)} running={stat.get('running',0)} "
      f"completed={stat.get('completed',0)} failed={stat.get('failed',0)}")
PY
)
  echo "     +${elapsed}s  healthy=${healthy}/2  ${q}"
}

run_load() {
  echo "${c_bold}== 持续混合负载 ${MINUTES} 分钟（两副本 producer+reader+churner）==${c_off}"
  echo "     预计提交量约 $(awk -v m="$MINUTES" -v r="$RATE" 'BEGIN{printf "%d", m*60*r*2}') jobs"
  run_driver 1 "$TMP/d1" &
  p1=$!
  run_driver 1 "$TMP/d2" &
  p2=$!
  # 健康采样（与驱动并行）
  elapsed=0
  ( while [ $elapsed -lt "$DUR_SECS" ]; do
      sleep 30; elapsed=$((elapsed+30)); sample_health $elapsed
    done ) &
  psampler=$!
  wait $p1 $p2
  wait $psampler 2>/dev/null || true
  echo "     -- 驱动器计数:"
  sed 's/^JSON/     C1/' "$TMP/d1"
  sed 's/^JSON/     C2/' "$TMP/d2"

  local agg
  agg=$(docker run --rm -i --entrypoint python "$BACKEND_IMAGE" - "$(cat "$TMP/d1")" "$(cat "$TMP/d2")" <<'PY'
import sys, json
tot = {}
for raw in sys.argv[1:]:
    line = raw.split("JSON ", 1)[1]
    for k, v in json.loads(line).items():
        tot[k] = tot.get(k, 0) + v
for k in sorted(tot):
    print(f"{k}={tot[k]}")
PY
)
  eval "$agg"
  echo "     合计: submitted=${submitted:-0} reads=${reads:-0} /run 200=${run200:-0} 409=${run409:-0} other=${run_other:-0} 5xx=${http5xx:-0}"
  echo "$agg" > "$TMP/totals"
}

drain_and_assert() {
  local submitted=$1
  echo "${c_bold}== 停流后 drain 队列（提交数 ${submitted}）==${c_off}"
  local final
  final=$(docker run --rm -i --entrypoint python --network "$NET" "$BACKEND_IMAGE" - "$submitted" "$TENANT" "$BASE" <<'PY'
import sys, json, time, urllib.request
submitted, tenant, base = int(sys.argv[1]), sys.argv[2], sys.argv[3]
def view():
    out, off = [], 0
    while True:
        with urllib.request.urlopen(
            f"{base}/api/exports/jobs?tenant_id={tenant}&limit=200&offset={off}",
            timeout=30) as r:
            page = json.loads(r.read())["jobs"]
        out.extend(page)
        if len(page) < 200: break
        off += 200
    return out
deadline = time.monotonic() + 180
stat = {}
while time.monotonic() < deadline:
    stat = {}
    for j in view(): stat[j["status"]] = stat.get(j["status"],0)+1
    if stat.get("queued",0)==0 and stat.get("running",0)==0: break
    time.sleep(2)
print("STAT", json.dumps(stat))
print(f"completed={stat.get('completed',0)}")
print(f"failed={stat.get('failed',0)}")
print(f"active={stat.get('queued',0)+stat.get('running',0)}")
PY
)
  echo "$final" | sed 's/^/     /'
  local completed failed active
  completed=$(echo "$final" | sed -n 's/^completed=//p')
  failed=$(echo "$final" | sed -n 's/^failed=//p')
  active=$(echo "$final" | sed -n 's/^active=//p')

  echo "${c_bold}== 断言 ==${c_off}"
  check "提交 ${submitted} == completed ${completed}（不丢单）" "$([ "$completed" = "$submitted" ] && echo 1 || echo 0)"
  check "队列 drain 干净（queued+running=${active}）" "$([ "$active" = "0" ] && echo 1 || echo 0)"
  check "无 failed job（failed=${failed:-0}）" "$([ "${failed:-0}" = "0" ] && echo 1 || echo 0)"

  local fivexx
  fivexx=$(grep '^http5xx=' "$TMP/totals" | cut -d= -f2)
  check "全程零 5xx（5xx=${fivexx:-0}）" "$([ "${fivexx:-0}" = "0" ] && echo 1 || echo 0)"
  local run200 run409
  run200=$(grep '^run200=' "$TMP/totals" | cut -d= -f2)
  run409=$(grep '^run409=' "$TMP/totals" | cut -d= -f2)
  check "持续锁抢占既有 200 也有 409（200=${run200:-0} 409=${run409:-0}）" \
    "$([ "${run200:-0}" -ge 1 ] && [ "${run409:-0}" -ge 1 ] && echo 1 || echo 0)"

  local healthy
  healthy=$(docker ps --filter "name=${PROJECT}-backend-" --filter health=healthy -q | wc -l | tr -d ' ')
  check "结束时两副本均 healthy" "$([ "$healthy" = "2" ] && echo 1 || echo 0)"

  local restarts oom
  restarts=0; oom=0
  for c in "$C1" "$C2"; do
    n=$(docker inspect -f '{{.RestartCount}}' "$c")
    restarts=$((restarts+n))
    docker inspect -f '{{.State.OOMKilled}}' "$c" | grep -q true && oom=1
  done
  check "两副本零重启（RestartCount 合计=${restarts}）" "$([ "$restarts" = "0" ] && echo 1 || echo 0)"
  check "无 OOMKill" "$([ "$oom" = "0" ] && echo 1 || echo 0)"

  local tb
  tb=0
  for c in "$C1" "$C2"; do
    docker logs "$c" 2>&1 | grep -q "Traceback" && tb=1
  done
  check "全程日志无未处理 Traceback" "$([ "$tb" = "0" ] && echo 1 || echo 0)"
}

case "${1:-up}" in
  up) up_stack; run_load; . "$TMP/totals"; drain_and_assert "${submitted:-0}" ;;
  run) run_load; . "$TMP/totals"; drain_and_assert "${submitted:-0}" ;;
  down) $COMPOSE down ;;
  *) echo "usage: $0 up|run|down"; exit 2 ;;
esac

echo "${c_bold}== 演练结果：${c_green}PASS=$pass${c_off}  ${c_red}FAIL=$fail${c_off} ==${c_off}"
[ "$fail" = "0" ]
