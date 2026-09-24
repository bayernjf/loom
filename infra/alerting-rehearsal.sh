#!/usr/bin/env bash
# Q185 指标消费侧端到端演练（docs/17 §7.6，02 C1.129）。
#
# 起真栈（真 PG/Redis/backend/frontend）+ monitoring overlay（Prometheus 规则求值
# + Grafana 看板 + watchdog 告警转发），全程 synthetic 不花钱，验证四段链路：
#   1. 配置静态校验：promtool check config/rules 通过、解析出 3 条规则；
#   2. 采集面真实可用：backend target health=up、Q181 两族 HTTP 指标真的进了 TSDB；
#   3. 消费面就位：3 条规则不仅装载、且 health=ok（表达式在真 TSDB 上真能求值，
#      比 promtool 的纯语法检查强一档）、Grafana 看板/数据源文件式置备可查、
#      数据源代理能查回真值、overlay 已替 watchdog 打开转发档；
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
FILES=(-f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.monitoring.yml)
# 告警通道指向 frontend：POST 结果可忽略、阶段 4 仍存活。真正的 webhook 投递语义
# 由 tests/unit/test_backup_monitoring_contract.py 覆盖，本演练只验「转发被触发」。
export LOOM_ALERT_WEBHOOK="${LOOM_ALERT_WEBHOOK:-http://frontend:3000/}"
export LOOM_GRAFANA_ADMIN_PASSWORD="${LOOM_GRAFANA_ADMIN_PASSWORD:-loom-alerting-rehearsal}"
GRAFANA_AUTH="admin:${LOOM_GRAFANA_ADMIN_PASSWORD}"
COMPOSE="docker compose ${FILES[*]} -p ${PROJECT} --profile monitoring"
# HTTP 探针走 watchdog 容器（python:3.12-slim，全程存活）：阶段 4 会停 backend，
# 从 backend 发探针会随之失效；Grafana 未发布宿主端口，只能从网格内打。
NET="${PROJECT}-watchdog-1"

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
    "SUCCESS: 3 rules found"
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
  c "Prometheus 装载 3 条告警规则（got $n）" test "$n" -eq 3
  for name in LoomHigh5xxRatio LoomHighP99Latency LoomBackendUnreachable; do
    c "规则 $name 已注册" sh -c "printf '%s' '$rules' | grep -qF '\"$name\"'"
  done
  # health=ok 才说明表达式在真 TSDB 上求值不报错（promtool 只验语法，语法过 ≠ 能跑）。
  ok=$(printf '%s' "$rules" | grep -o '"health":"ok"' | wc -l | tr -d ' ')
  c "3 条规则 health 全为 ok（表达式可求值，got $ok）" test "$ok" -ge 3
  c "无规则求值报错" sh -c "! printf '%s' '$rules' | grep -qF '\"health\":\"err\"'"

  ci "Grafana /api/health 200" \
    "net_api GET http://grafana:3000/api/health '' '$GRAFANA_AUTH'" "STATUS 200"
  ci "Grafana 看板 loom-http 文件式置备可查" \
    "net_api GET http://grafana:3000/api/dashboards/uid/loom-http '' '$GRAFANA_AUTH'" \
    "STATUS 200"
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
  local before after hits
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

  hits=$(docker logs "$NET" 2>&1 | grep -c "ALERT target=prometheus:LoomBackendUnreachable")
  echo "     watchdog 转发命中 $hits 次（180s 内轮询 ~6 轮）"
  c "watchdog 至少转发一次（规则不是死文本）" test "$hits" -ge 1
  # 去重是硬要求：同一 activeAt 的同一告警多轮轮询只该通知一次。
  c "同一事件只转发一次（去重生效）" test "$hits" -eq 1

  echo "     恢复 backend …"
  $COMPOSE up -d backend >/dev/null 2>&1
  sleep 45
  ci "恢复后 backend 重新可抓取" "net_api GET $RULES_URL" '"name":"LoomBackendUnreachable"'
}

case "${1:-up}" in
  up)    up_stack; stage_static; stage_scrape; stage_consume; stage_fire ;;
  run)   stage_static; stage_scrape; stage_consume ;;
  down)  $COMPOSE down ;;
  *) echo "usage: $0 up|run|down"; exit 2 ;;
esac

echo "${c_bold}== 演练结果：${c_green}PASS=$pass${c_off}  ${c_red}FAIL=$fail${c_off} ==${c_off}"
[ "$fail" = 0 ]
