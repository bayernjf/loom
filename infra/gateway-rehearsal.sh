#!/usr/bin/env bash
# Q282 网关放行面端到端演练（docs/17 §7.8，02 C1.225）。
#
# 起**真栈**（真 PG／Redis／backend／frontend）叠 gateway overlay，全程 synthetic、不花钱。
# 与 alerting-rehearsal 的分工：那边验「指标消费侧真链」，这边验「对外入站面的形状」——
# Q279 的 Caddyfile 之前只用 stand-in 上游验过路由，本脚本验的是真实服务：
#   阶段 1 发布面：app 服务一个都不发布宿主端口，只有 caddy 占 80/443（演练里 infra 端口
#          再额外收回网格内，好让本机已跑着的栈不互扰）；
#   阶段 2 放行面：/api 读口经网关回**空库真值** `[]`；`POST /mcp` 无凭证回 401（鉴权层的
#          答复，不是 Next 的 HTML）；A2A 两张卡片 200；
#   阶段 3 拦截面：/docs·/redoc·/openapi.json·/healthz·/metrics 由网关回 404「not found」，
#          且 body 必须是网关自己那句（证明拦在网关，而不是上游恰好没这个口）；
#   阶段 4 旋钮面：`LOOM_PUBLIC_BASE_URL` 空 ⇒ 卡片 `url` 相对路径；重建 backend 并注入该 env
#          ⇒ 卡片 `url` 变绝对。这一条就是 Q280 那个「compose 从不转发」缺陷的正向验证。
#
# 刻意不验真实 ACME 签发：那需要公网域名与 80/443 可达，属部署机动作（docs/17 §1.1 记此边界）。
# 站点地址取 localhost ⇒ Caddy 自动用内部 CA，不碰 Let's Encrypt 的签发速率限额。
#
# 用法（在 infra/ 目录）：
#   ./gateway-rehearsal.sh up      # 构建镜像、起栈、跑全部四段（默认）
#   ./gateway-rehearsal.sh run     # 栈已在跑，只重跑断言
#   ./gateway-rehearsal.sh down    # 拆除演练栈（含本项目自己的卷）
# 前置：本机 80/443 空闲（caddy 要占）。演练用独立 project 名，不动同名以外的容器。
set -uo pipefail

# 与 alerting-rehearsal 同规矩：注入**演练专用**口令（非生产密钥），且刻意不用 ${VAR:?}——
# 解析期全局求值会打断没设变量的其它 overlay（Q185／Q200 #33）。
export LOOM_MASTER_KEY="${LOOM_MASTER_KEY:-loom-rehearsal-only-master-key}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-loom-rehearsal-only-pg}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-loom-rehearsal-only-minio}"
export LOOM_GATEWAY_DOMAIN="${LOOM_GATEWAY_DOMAIN:-localhost}"

cd "$(dirname "$0")"
PROJECT=loom-gateway

# 演练专用 override：把 infra 的宿主端口收回网格内——本机若已跑着一套 infra-* 栈，
# 5432/6379 会撞；撞了就不是「网关面」的问题，而是脚本在跟无关的端口较劲。
OVERRIDE_DIR="$(mktemp -d)"
trap 'rm -rf "$OVERRIDE_DIR"' EXIT
cat > "$OVERRIDE_DIR/ports.yml" <<'EOF'
services:
  postgres:
    ports: !reset []
  redis:
    ports: !reset []
  minio:
    ports: !reset []
EOF

FILES=(-f docker-compose.yml -f docker-compose.gateway.yml -f "$OVERRIDE_DIR/ports.yml")
COMPOSE="docker compose ${FILES[*]} -p ${PROJECT}"

c_bold=$'\033[1m'; c_green=$'\033[32m'; c_red=$'\033[31m'; c_off=$'\033[0m'
pass=0; fail=0

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
  if [ "$needle" = "__EMPTY__" ]; then
    if [ -z "$out" ]; then
      echo "${c_green}  PASS${c_off} $desc"; pass=$((pass+1))
    else
      echo "${c_red}  FAIL${c_off} $desc${c_off}   （期望无宿主绑定，实得：$(printf %.120s "$out")）"; fail=$((fail+1))
    fi
    return
  fi
  if printf '%s' "$out" | grep -qF -- "$needle"; then
    echo "${c_green}  PASS${c_off} $desc"; pass=$((pass+1))
  else
    echo "${c_red}  FAIL${c_off} $desc${c_off}   （未命中：$needle｜实得：$(printf '%.120s' "$out")）"; fail=$((fail+1))
  fi
}

wait_backend() {
  local waited=0
  while [ "$(docker inspect -f '{{.State.Health.Status}}' "${PROJECT}-backend-1" 2>/dev/null || echo starting)" != "healthy" ]; do
    [ "$waited" -ge 240 ] && return 1
    sleep 10; waited=$((waited + 10))
  done
  return 0
}

up_stack() {
  echo "${c_bold}== 起栈：base ＋ gateway ＋（演练用）infra 端口收回 =="${c_off}
  # --wait 若因旁路服务不齐而超时，回退普通 up -d，后续断言自身收敛。
  $COMPOSE up -d --build --wait --wait-timeout 300 >/dev/null 2>&1 \
    || $COMPOSE up -d --build >/dev/null 2>&1
  wait_backend || { echo "${c_red}backend 未在 240s 内 healthy，演练中止${c_off}"; exit 1; }
  $COMPOSE up -d caddy >/dev/null 2>&1
  sleep 6
}

stage_publishing() {
  echo "${c_bold}== 阶段 1：对外发布面只剩网关 =="${c_off}
  # 判据取**内核层面的真实绑定**（`docker port`），不用 `docker compose port`——
  # 实测后者对「没有端口映射的服务」回一行 "invalid IP:0" 且**退出码 0**，拿它判空会假红。
  ci "frontend 不发布任何宿主端口（绕过网关直打 3000 这条路不存在）" \
    "docker port ${PROJECT}-frontend-1" "__EMPTY__"
  ci "backend 不发布任何宿主端口" "docker port ${PROJECT}-backend-1" "__EMPTY__"
  ci "caddy 真绑宿主 80（ACME 与 308 跳转用）" "docker port ${PROJECT}-caddy-1" "80/tcp -> 0.0.0.0:80"
  ci "caddy 真绑宿主 443" "docker port ${PROJECT}-caddy-1" "443/tcp -> 0.0.0.0:443"
  c "caddy 在跑" test "$(docker inspect -f '{{.State.Status}}' "${PROJECT}-caddy-1")" = running
}

stage_allow() {
  echo "${c_bold}== 阶段 2：放行面真的通到后端 =="${c_off}
  ci "空库读口经网关回真实值 []（穿过 caddy→FastAPI→PostgreSQL）" \
    "curl -sk --max-time 15 'https://localhost/api/admin/publish-slots?actor_id=ops-actor&roles=operations'" "[]"
  ci "POST /mcp 无凭证 → 鉴权层的答复（证明命中的是后端不是前端）" \
    "curl -sk --max-time 15 -X POST -H 'content-type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}' https://localhost/mcp" \
    "invalid or revoked agent API key"
  ci "POST /mcp 无凭证的状态码是 401" \
    "curl -sk --max-time 15 -o /dev/null -w '%{http_code}' -X POST https://localhost/mcp" "401"
  ci "A2A 卡片可公开取回（agent-card.json）" \
    "curl -sk --max-time 15 https://localhost/.well-known/agent-card.json" '"url"'
  ci "A2A 卡片可公开取回（agent.json）" \
    "curl -sk --max-time 15 https://localhost/.well-known/agent.json" '"name"'
  ci "前端由网关兜底应答（非 API 路径不落到后端）" \
    "curl -skL --max-time 20 -o /dev/null -w '%{http_code}' https://localhost/" "200"
}

stage_block() {
  echo "${c_bold}== 阶段 3：拦截面拦在网关（body 是网关那句 not found） =="${c_off}
  for path in /docs /docs/oauth2-redirect /redoc /openapi.json /healthz /metrics; do
    ci "网关拦 $path" \
      "curl -sk --max-time 15 -w ' [%{http_code}]' https://localhost$path" "not found [404]"
  done
}

stage_redirect_and_knob() {
  echo "${c_bold}== 阶段 4：跳转与 LOOM_PUBLIC_BASE_URL 旋钮（Q280 缺陷的正向验证） =="${c_off}
  ci "http → 308 且 Location 是 https" \
    "curl -s --max-time 15 -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost/api/x" "308 https://localhost/api/x"
  ci "env 未注入 ⇒ 卡片 url 为相对路径（compose 的 :- 默认留空，仓内不预设域名）" \
    "curl -sk --max-time 15 https://localhost/.well-known/agent-card.json" '"url":"/api/a2a/tasks"'

  echo "     重建 backend 并注入 LOOM_PUBLIC_BASE_URL=https://rehearsal.test …"
  LOOM_PUBLIC_BASE_URL=https://rehearsal.test $COMPOSE up -d --no-deps backend >/dev/null 2>&1
  wait_backend || { echo "${c_red}  backend 重建后未 healthy${c_off}"; fail=$((fail+1)); return; }
  sleep 5
  ci "旋钮经 compose 进入容器 ⇒ 卡片 url 变绝对（Q280 修复的实证）" \
    "curl -sk --max-time 15 https://localhost/.well-known/agent-card.json" '"url":"https://rehearsal.test/api/a2a/tasks"'
  ci "另一张卡片同样变绝对" \
    "curl -sk --max-time 15 https://localhost/.well-known/agent.json" '"url":"https://rehearsal.test/api/a2a/tasks"'
}

case "${1:-up}" in
  up)   up_stack; stage_publishing; stage_allow; stage_block; stage_redirect_and_knob ;;
  run)  stage_publishing; stage_allow; stage_block; stage_redirect_and_knob ;;
  down) $COMPOSE down -v ;;
  *)    echo "usage: $0 up|run|down"; exit 2 ;;
esac

echo "${c_bold}== 演练结果：${c_green}PASS=$pass${c_off}  ${c_red}FAIL=$fail${c_off} =="${c_off}
[ "$fail" = 0 ]
