#!/usr/bin/env bash
# Q185 指标消费侧端到端演练（docs/17 §7.6，02 C1.129）；Q188 业务级打点后扩至 10 条
# 规则、两张看板（02 C1.132）。
#
# 起真栈（真 PG/Redis/backend/frontend）+ monitoring overlay（Prometheus 规则求值
# + Grafana 看板 + watchdog 告警转发），全程 synthetic 不花钱，验证四段链路：
#   1. 配置静态校验：promtool check config/rules 通过、解析出 10 条规则；
#   2. 采集面真实可用：backend target health=up、Q181 两族 HTTP 指标真的进了 TSDB；
#   3. 消费面就位：10 条规则不仅装载、且 health=ok（表达式在真 TSDB 上真能求值，
#      比 promtool 的纯语法检查强一档；Q188 业务族无流量时无序列，空向量求值仍
#      应为 ok，这条正是「无数据 ≠ 求值失败」的实证）、Grafana 两张看板与数据源
#      文件式置备可查、数据源代理能查回真值、overlay 已替 watchdog 打开转发档；
#   4. 端到端触发：停 backend → up 转 0 → LoomBackendUnreachable 转 firing →
#      watchdog 把该告警转发进 LOOM_ALERT_WEBHOOK，且**整段只转发一次**（去重）。
#
# 顺带证明 Q185 修掉的两个真实缺陷：全新卷下 postgres 能起（归档卷属主改由
# wal-archive-init 预备）、staging overlay 下 compose project 不再因
# wal-archiver→minio 被判 invalid。
#
# 用法（在 infra/ 目录）：
#   ./alerting-rehearsal.sh up      # 构建/起栈并跑全部演练（默认）
#   ./alerting-rehearsal.sh run     # 栈已在跑，只重跑断言 1-3（跳过触发段）
#   ./alerting-rehearsal.sh down    # 拆除演练栈
set -uo pipefail

cd "$(dirname "$0")"
PROJECT=loom-alerting
# Q193：多叠一层演练专用 override，只为打开导出 worker 门控（业务告警实触发用）。
FILES=(-f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.monitoring.yml \
       -f docker-compose.alerting-rehearsal.yml)
# 告警通道指向 frontend：POST 结果可忽略、阶段 4 仍存活。真正的 webhook 投递语义
# 由 tests/unit/test_backup_monitoring_contract.py 覆盖，本演练只验「转发被触发」。
export LOOM_ALERT_WEBHOOK="${LOOM_ALERT_WEBHOOK:-http://frontend:3000/}"
export LOOM_GRAFANA_ADMIN_PASSWORD="${LOOM_GRAFANA_ADMIN_PASSWORD:-loom-alerting-rehearsal}"
GRAFANA_AUTH="admin:${LOOM_GRAFANA_ADMIN_PASSWORD}"
COMPOSE="docker compose ${FILES[*]} -p ${PROJECT} --profile monitoring"
# 网格内 HTTP 探针走 watchdog 容器（python:3.12-slim，全程存活）：阶段 4 会停 backend，
# 从 backend 发探针会随之失效。Grafana 自 Q192 起**只绑宿主回环 127.0.0.1:3001**，
# 故「看板真能打开」必须由**宿主侧**断言（见 GRAFANA_HOST_URL），网格内那条只证明服务活着。
NET="${PROJECT}-watchdog-1"
GRAFANA_HOST_URL="http://127.0.0.1:3001/api/health"

c_green=$'\033[32m'; c_red=$'\033[31m'; c_bold=$'\033[1m'; c_off=$'\033[0m'
pass=0; fail=0

# 断言助手：直接以「命令自身的退出码」判定，绝不经 $? 串联（初版在此踩空：
# `rc=$(cmd); check "..." "$?"` 与 echo 型 helper 混用会静默误判 FAIL）。
#   c <desc> <cmd...>            退出码 0 即 PASS
#   ci <desc> <cmd> <期望输出>    命令输出含期望串即 PASS（cmd 由 sh -c 执行）
c() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "${c_green}  PASS${c_off} $desc"; pass=$((pass+1))
  else
    echo "${c_red}  FAIL${c_off} $desc"; fail=$((fail+1))
  fi
}
ci() {
  local desc="$1" cmd="$2" needle="$3" out
  out=$(eval "$cmd" 2>/dev/null)
  if printf '%s' "$out" | grep -qF -- "$needle"; then
    echo "${c_green}  PASS${c_off} $desc"; pass=$((pass+1))
  else
    echo "${c_red}  FAIL${c_off} $desc${c_off}   （未命中：$needle）"; fail=$((fail+1))
  fi
}

# 在 watchdog 容器里用 python 打网格内任意 host:port。输出 "STATUS <code>" + body。
net_api() { # net_api <method> <url> [body] [user:pass]
  docker exec -i "$NET" python - "$1" "$2" "${3:-}" "${4:-}" <<'PY'
import sys, base64, urllib.request, urllib.error
method, url, body, auth = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
req = urllib.request.Request(url, data=(body.encode() if body else None), method=method)
req.add_header("Content-Type", "application/json")
if auth:
    req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        print("STATUS", r.status)
        print(r.read().decode(errors="replace"))
except urllib.error.HTTPError as e:
    print("STATUS", e.code)
    print(e.read().decode(errors="replace"))
except Exception as e:  # noqa: BLE001
    print("STATUS", 0)
    print(type(e).__name__, e)
PY
}

status_of() { head -1 | awk '{print $2}'; }
# 取 Prometheus instant query 首条向量的值（纯 grep/sed，不依赖宿主 python）。
query_value() {
  grep -o '"value":\[[0-9.eE+]*,"[^"]*"\]' | head -1 | sed -E 's/.*,"([^"]*)".*/\1/'
}
RULES_URL='http://prometheus:9090/api/v1/rules?type=alert'   # 合法值只有 alert|record|all
UP_QUERY='http://prometheus:9090/api/v1/query?query=up%7Bjob%3D%22loom-backend%22%7D'

up_stack() {
  echo "${c_bold}== 起栈（monitoring overlay）==${c_off}"
  # 先确认演练项目下已无残留容器：早先一次 `down -v` 静默失败，导致本轮把上一轮的
  # 转发日志与 15 分钟窗口里的旧 firing 当成自己的证据（假失败＋假通过同时出现）。
  local leftover
  leftover=$(docker ps -a --format '{{.Names}}' | grep -c "^${PROJECT}-" || true)
  if [ "$leftover" != "0" ]; then
    echo "${c_red}  ABORT${c_off} 演练项目残留 $leftover 个容器，先执行 $0 down"; exit 2
  fi
  # --wait 若因旁路服务不齐而超时，回退普通 up -d，后续断言自身收敛。
  $COMPOSE up -d --build --wait --wait-timeout 240 >/dev/null 2>&1 \
    || $COMPOSE up -d --build >/dev/null 2>&1
  echo "     等待首轮抓取 + 规则求值（40s）…"
  sleep 40
}

stage_static() {
  echo "${c_bold}== 阶段 1：配置静态校验 ==${c_off}"
  c "promtool check config 通过（含 rule_files）" \
    $COMPOSE exec -T prometheus /bin/promtool check config /etc/prometheus/prometheus.yml
  ci "promtool check rules SUCCESS" \
    "$COMPOSE exec -T prometheus /bin/promtool check rules /etc/prometheus/alert_rules.yml" \
    "SUCCESS: 10 rules found"
  ci "Prometheus /-/ready 200" "net_api GET http://prometheus:9090/-/ready" "STATUS 200"
  ci "Grafana 容器在跑" "docker inspect -f '{{.State.Running}}' ${PROJECT}-grafana-1" "true"
}

stage_scrape() {
  echo "${c_bold}== 阶段 2：采集面真实可用 ==${c_off}"
  ci "backend target health=up（Q181 /metrics 抓取成功）" \
    "net_api GET http://prometheus:9090/api/v1/targets" '"health":"up"'
  local fam
  for fam in http_requests_total http_request_duration_seconds_bucket; do
    ci "TSDB 中存在指标族 $fam" \
      "net_api GET 'http://prometheus:9090/api/v1/series?match[]=$fam'" \
      "\"__name__\":\"$fam\""
  done
}

stage_consume() {
  echo "${c_bold}== 阶段 3：消费面就位（规则 / 看板 / 转发开关）==${c_off}"
  local rules n name ok
  rules=$(net_api GET "$RULES_URL")
  # 只数 `"name":"Loom` 前缀出现次数：告警名含数字（LoomHigh5xxRatio / LoomHighP99…），
  # 用 [A-Za-z]* 收尾的正则会在数字处截断而误判条数。
  n=$(printf '%s' "$rules" | grep -o '"name":"Loom' | wc -l | tr -d ' ')
  # Q185 三条 HTTP RED + Q188 七条业务信号。
  c "Prometheus 装载 10 条告警规则（got $n）" test "$n" -eq 10
  for name in \
    LoomHigh5xxRatio LoomHighP99Latency LoomBackendUnreachable \
    LoomJobFailed LoomStreamDeadLettered LoomQueueBacklog LoomStreamNearTrimLimit \
    LoomLockLost LoomLlmUpstreamSlow LoomLlmBudgetBlocked; do
    c "规则 $name 已注册" sh -c "printf '%s' '$rules' | grep -qF '\"$name\"'"
  done
  # health=ok 才说明表达式在真 TSDB 上求值不报错（promtool 只验语法，语法过 ≠ 能跑）。
  # 业务族在无流量时**无序列**，空向量求值仍是 ok——这条正是确认「无数据 ≠ 求值失败」。
  ok=$(printf '%s' "$rules" | grep -o '"health":"ok"' | wc -l | tr -d ' ')
  c "10 条规则 health 全为 ok（表达式可求值，got $ok）" test "$ok" -ge 10
  c "无规则求值报错" sh -c "! printf '%s' '$rules' | grep -qF '\"health\":\"err\"'"

  ci "Grafana /api/health 200" \
    "net_api GET http://grafana:3000/api/health '' '$GRAFANA_AUTH'" "STATUS 200"
  ci "Grafana 看板 loom-http 文件式置备可查" \
    "net_api GET http://grafana:3000/api/dashboards/uid/loom-http '' '$GRAFANA_AUTH'" \
    "STATUS 200"
  # Q188 第二张看板：同一 provider 目录自动装载，不需要改 compose。
  ci "Grafana 看板 loom-operations 文件式置备可查" \
    "net_api GET http://grafana:3000/api/dashboards/uid/loom-operations '' '$GRAFANA_AUTH'" \
    "STATUS 200"

  # Q192：负责人拍板开 Grafana 回环端口。断言必须打在**宿主**上，否则证明的是网格内
  # 可达（那在没有发布端口时也一样成立），等于没验这次改动。
  c "宿主直连 Grafana 回环端口 $GRAFANA_HOST_URL" \
    curl -fsS --max-time 10 "$GRAFANA_HOST_URL"
  ci "该端口只绑 127.0.0.1（未裸露网卡）" \
    "docker port ${PROJECT}-grafana-1 3000/tcp" "127.0.0.1:3001"
  ci "Grafana 数据源 loom-prom 置备可查" \
    "net_api GET http://grafana:3000/api/datasources/uid/loom-prom '' '$GRAFANA_AUTH'" \
    "STATUS 200"
  # 数据源代理真查询：证明「看板 → Prometheus」这条链路真通，而非只落了配置文件。
  # Prometheus 的 /api/v1/query 要 query-string 参数（POST JSON body 会被判缺参）。
  ci "Grafana 数据源代理查询 up 返回真值" \
    "net_api GET \
      'http://grafana:3000/api/datasources/proxy/uid/loom-prom/api/v1/query?query=up%7Bjob%3D%22loom-backend%22%7D' \
      '' '$GRAFANA_AUTH'" \
    '"__name__":"up"'

  ci "watchdog 已开 PROMETHEUS_ALERTS_URL 转发档" \
    "$COMPOSE exec -T watchdog env" \
    "PROMETHEUS_ALERTS_URL=http://prometheus:9090/api/v1/alerts"
}

stage_fire() {
  echo "${c_bold}== 阶段 4：端到端触发（停 backend → firing → watchdog 单次转发）==${c_off}"
  local before after hits t0
  # docker logs 会跨轮次累积（若容器未被重建），所以转发次数只统计本阶段开始之后的行。
  t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  before=$(net_api GET "$UP_QUERY" | query_value)
  echo "     触发前 up{job=loom-backend}=$before"
  c "触发前 up 为 1" sh -c "case '$before' in 1|1.0) exit 0;; *) exit 1;; esac"

  $COMPOSE stop backend >/dev/null 2>&1
  echo "     backend 已停，等待 for:1m 判定 + watchdog 轮询（180s）…"
  sleep 180

  after=$(net_api GET "$UP_QUERY" | query_value)
  echo "     停后 up{job=loom-backend}=$after"
  c "停后 up 转 0" sh -c "case '$after' in 0|0.0|'') exit 0;; *) exit 1;; esac"
  ci "Prometheus 判 LoomBackendUnreachable 为 firing" \
    "net_api GET $RULES_URL" '"name":"LoomBackendUnreachable"'

  hits=$(docker logs --since "$t0" "$NET" 2>&1 | grep -c "ALERT target=prometheus:LoomBackendUnreachable")
  echo "     watchdog 转发命中 $hits 次（180s 内轮询 ~6 轮）"
  c "watchdog 至少转发一次（规则不是死文本）" test "$hits" -ge 1
  # 去重是硬要求：同一 activeAt 的同一告警多轮轮询只该通知一次。
  c "同一事件只转发一次（去重生效）" test "$hits" -eq 1

  echo "     恢复 backend …"
  $COMPOSE up -d backend >/dev/null 2>&1
  # 固定 sleep 45 不够：backend entrypoint 先跑 alembic upgrade head 才起服务（Q145），
  # 冷启动时长随迁移数量增长。改为轮询到 up 回 1，最多 180s——超时即真失败。
  local back=0
  while [ "$back" -lt 180 ]; do
    sleep 15; back=$((back + 15))
    if [ "$(net_api GET "$UP_QUERY" | query_value)" = "1" ]; then break; fi
  done
  echo "     等待 ${back}s 后检查 up"
  # 原断言写的是「规则列表里出现 LoomBackendUnreachable」——该名字无论 firing 还是
  # resolved 都在 /api/v1/rules 里，**永远绿、证不了任何事**（Q193 复核时抓出）。
  # 改判真信号：up 必须回到 1。
  recovered=$(net_api GET "$UP_QUERY" | query_value)
  echo "     恢复后 up{job=loom-backend}=$recovered"
  c "恢复后 backend 重新可抓取（up 回 1）" sh -c "case '$recovered' in 1|1.0) exit 0;; *) exit 1;; esac"
}

# Q193：业务告警实触发——七条业务规则此前只被证明「表达式可求值」，从未证明
# 「真出事前会发生」。本阶段用一条**真实生产故障路径**（入流 fail-closed）把它打红：
# 停 redis → POST /api/exports/jobs（门控已开）→ enqueue 抛 StreamBackendError
# → service.fail_export_job 落 DB 并 inc loom_job_failed_total → 抓取 → 规则 firing
# → watchdog 转发进 LOOM_ALERT_WEBHOOK。全程不 monkeypatch 容器内代码。

# 真判据：从 /api/v1/alerts 找"该 alertname 当前 state=firing"。
# 绝不用 /api/v1/rules 的规则名当判据——规则名无论 firing/pending/inactive 都在里面。
alert_firing() { # <alertname> [label=value]
  docker exec -i "$NET" python - "$1" "${2:-}" <<'PYEOF'
import json, sys, urllib.request
name, want = sys.argv[1], sys.argv[2]
key, _, val = want.partition("=")
d = json.load(urllib.request.urlopen("http://prometheus:9090/api/v1/alerts", timeout=20))
for a in d["data"]["alerts"]:
    if a["state"] != "firing" or a["labels"].get("alertname") != name:
        continue
    if want and a["labels"].get(key) != val:
        continue
    sys.exit(0)
sys.exit(1)
PYEOF
}

stage_business_alert() {
  echo "${c_bold}== 阶段 5：业务告警实触发（入流 fail-closed → LoomJobFailed → 转发）==${c_off}"
  local code hits waited saw_firing t0
  t0=$(date -u +%Y-%m-%dT%H:%M:%SZ); T0="$t0"
  $COMPOSE stop redis >/dev/null 2>&1
  echo "     redis 已停（导出 worker 门控本阶段已开）…"
  code=$(net_api POST "http://backend:8000/api/exports/jobs" \
    '{"tenant_id":"t-rehearsal-biz","format":"csv","actor":{"id":"ops-1","roles":["operations"]}}')
  echo "     POST /api/exports/jobs → $code"
  # 注意 ci 的签名是 <desc> <cmd> <needle>，把 $code 直接摊进去会让判据变成 JSON 块。
  c "入流失败按 Q137 口径回 503（不是 201、不是静默成功）" \
    sh -c 'printf "%s" "$1" | grep -qF "STATUS 503"' _ "$code"

  # 两个观测都必须在轮询里采样：告警先 pending（activeAt 起算）后 firing，事后一次性
  # 快照 state=="firing" 会撞进这个窗口——上一版正是因此假失败（20s 就转发到了，那一刻
  # 规则尚在 pending）。要求"曾见 firing"且"已转发"同时成立才退出。
  echo "     等待抓取 + for:1m 判定 + watchdog 轮询（最多 300s）…"
  waited=0; hits=0; saw_firing=0
  while [ "$waited" -lt 300 ]; do
    sleep 15; waited=$((waited + 15))
    if [ "$saw_firing" = 0 ] && alert_firing LoomJobFailed kind=export; then
      saw_firing=1; echo "     (${waited}s) 已观测到 firing（kind=export）"
    fi
    hits=$(docker logs --since "$t0" "$NET" 2>&1 | grep -c "ALERT target=prometheus:LoomJobFailed")
    if [ "$saw_firing" = 1 ] && [ "$hits" -ge 1 ]; then break; fi
  done
  c "阶段内曾观测到 LoomJobFailed firing（含 kind=export 标签）" test "$saw_firing" -eq 1
  echo "     watchdog 转发 LoomJobFailed 命中 $hits 次（等了 ${waited}s）"
  c "业务告警真走完投递链（watchdog 转发过 LoomJobFailed）" test "$hits" -ge 1
  ci "watchdog 日志行格式与 Q185 转发链一致（target=prometheus:规则名）" \
    "docker logs --since $T0 $NET 2>&1" "ALERT target=prometheus:LoomJobFailed"

  echo "     恢复 redis …"
  $COMPOSE start redis >/dev/null 2>&1
  sleep 20
  c "redis 恢复且健康" docker inspect -f "{{.State.Health.Status}}" "${PROJECT}-redis-1"
}

case "${1:-up}" in
  up)    up_stack; stage_static; stage_scrape; stage_consume; stage_fire; stage_business_alert ;;
  run)   stage_static; stage_scrape; stage_consume ;;
  biz)   stage_business_alert ;;
  down)  $COMPOSE down ;;
  *) echo "usage: $0 up|run|biz|down"; exit 2 ;;
esac

echo "${c_bold}== 演练结果：${c_green}PASS=$pass${c_off}  ${c_red}FAIL=$fail${c_off} ==${c_off}"
[ "$fail" = 0 ]
