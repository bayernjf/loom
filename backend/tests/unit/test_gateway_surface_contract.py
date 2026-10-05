"""Q279 网关放行面契约（甲案落地：infra/caddy/Caddyfile ＋ docker-compose.gateway.yml）。

网关是这仓库第一个「配置写在应用外、后果落在应用内」的组件：Caddyfile 少一行路由，
后端照样启动、常规测试照样全绿，只是那条路在公网变成 Next.js 的 200 HTML——静默失败。
所以这里钉的是**面的覆盖**，不是字符串长相：

- 后端能服务的**每一条真实路径**（含 FastAPI 自带的 docs 面）都必须在网关里被判成
  「转后端」或「网关拦截」之一；新增 `@router.post("/webhooks")` 而没写网关策略 ⇒ 判红。
- 上游名字与端口回扣 compose 服务与容器实际监听口，不靠记忆。
- 域名默认值在两处文件＋docs/17 里必须同值；compose 侧必须是 `:-` 形式（实测：env 存在
  但为空时站点地址变空串，Caddy 报 `unrecognized global option: handle`）。
"""

import re
from pathlib import Path

import yaml
from fastapi.routing import APIRoute

from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
CADDYFILE = REPO_ROOT / "infra" / "caddy" / "Caddyfile"
BASE_COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
GATEWAY_OVERLAY = REPO_ROOT / "infra" / "docker-compose.gateway.yml"
ENTRYPOINT = REPO_ROOT / "backend" / "docker-entrypoint.sh"
DOCS_DEPLOY = REPO_ROOT / "docs" / "17_部署与运维.md"

# 裁决口径（Q279，负责人「你搞吧」按工程侧推荐落定）：这三组公网可达，这三组网关拦死。
TO_BACKEND = {".well-known", "api", "mcp"}
BLOCKED = {"docs", "redoc", "openapi.json", "healthz", "metrics"}


def _all_paths() -> list[str]:
    """后端真实可服务的每个路径：APIRoute 全集 ＋ FastAPI 挂的 docs 面（Route 非 APIRoute）。"""
    paths: list[str] = []
    stack = list(app.routes)
    while stack:
        node = stack.pop()
        sub = getattr(node, "original_router", None)
        if sub is not None:
            stack.extend(sub.routes)
        elif isinstance(node, APIRoute):
            paths.extend(f"/{node.path.strip('/')}" for _ in (node.methods or set()))
        else:
            path = getattr(node, "path", "")
            if path.startswith("/"):
                paths.append(path)
    return sorted(set(paths))


def _root(path: str) -> str:
    return path.strip("/").split("/")[0]


def _rules() -> list[tuple[list[str], str]]:
    """Caddyfile → [(匹配器, 动作)]，按声明序；注释先剥掉。"""
    text = re.sub(r"(^|\n)\s*#[^\n]*", "", CADDYFILE.read_text())
    out = []
    for raw_matchers, body in re.findall(r"handle\s+([^\n{]*)\{([^}]*)\}", text):
        out.append((raw_matchers.split(), " ".join(body.split())))
    return out


def _matches(matcher: str, path: str) -> bool:
    return matcher == path or (matcher.endswith("/*") and path.startswith(matcher[:-1]))


def _classify(path: str) -> tuple[str, str]:
    """返回 (判定, 命中的匹配器)。判定 ∈ {backend, blocked, catchall}。"""
    for matchers, action in _rules():
        hit = next((m for m in matchers if _matches(m, path)), None)
        if hit:
            kind = "backend" if "reverse_proxy" in action else "blocked"
            return kind, hit
    return "catchall", ""


def test_the_path_enumeration_is_not_empty() -> None:
    """正向对照：枚举必须真的看见面，否则后面全是空转。"""
    paths = _all_paths()
    assert len(paths) > 150, len(paths)
    roots = {_root(p) for p in paths}
    assert {".well-known", "api", "mcp", "healthz", "metrics"} <= roots, sorted(roots)
    assert {"docs", "redoc", "openapi.json"} <= roots, sorted(roots)


def test_the_parser_reads_every_handle_block() -> None:
    """解析器覆盖率：文件里几个 handle 块，_rules() 就必须收到几个。"""
    raw = CADDYFILE.read_text()
    declared = len(re.findall(r"^\thandle\b", raw, re.MULTILINE))
    assert len(_rules()) == declared, (len(_rules()), declared)
    assert _rules()[-1][0] == [], "最后一个块必须是兜底转前端（无匹配器）"


def test_every_served_path_has_an_explicit_gateway_policy() -> None:
    misrouted = []
    for path in _all_paths():
        root = _root(path)
        kind, matcher = _classify(path)
        if root in TO_BACKEND:
            expected = "backend"
        elif root in BLOCKED:
            expected = "blocked"
        else:
            misrouted.append((path, root, kind, "未登记的顶层根"))
            continue
        if kind != expected:
            misrouted.append((path, root, kind, matcher))
    assert not misrouted, (
        "网关策略与代码面漂移，逐条为 (路径, 顶层根, 网关判定, 命中匹配器)："
        f"{misrouted}；新增入站面请在 infra/caddy/Caddyfile 写 handle 块，"
        "并把该根加进 TO_BACKEND 或 BLOCKED（改放行面属裁决，须登记 Q 编号）"
    )


def test_a_path_that_nothing_matches_is_not_mistaken_for_blocked() -> None:
    """反向对照：未写策略的根会被前端 catch-all 吞掉，判定必须是 catchall 而不是 blocked。"""
    assert _classify("/webhooks/new") == ("catchall", "")
    assert _classify("/mcp") == ("backend", "/mcp")


def test_compose_overlay_leaves_the_gateway_as_the_only_host_facing_service() -> None:
    loader = yaml.SafeLoader
    loader.add_constructor("!reset", lambda l, n: l.construct_sequence(n))
    base = yaml.safe_load(BASE_COMPOSE.read_text())["services"]
    overlay = yaml.load(GATEWAY_OVERLAY.read_text(), Loader=loader)["services"]
    merged = {
        name: {**base.get(name, {}), **overlay.get(name, {})}
        for name in base.keys() | overlay.keys()
    }

    assert merged["caddy"]["ports"] == ["80:80", "443:443"]
    assert merged["frontend"].get("ports", []) == [], merged["frontend"].get("ports")
    assert "ports" not in merged["backend"]
    for infra in ("postgres", "redis", "minio"):
        for published in merged[infra].get("ports", []):
            assert str(published).startswith("127.0.0.1:"), (infra, published)

    image = merged["caddy"]["image"]
    assert re.search(r":\d+\.\d+\.\d+$", image), f"镜像未钉到具体版本：{image}"
    mounts = [str(v) for v in merged["caddy"]["volumes"]]
    assert any(m.endswith("/etc/caddy/Caddyfile:ro") for m in mounts), mounts
    # 证书必须落命名卷：/data 丢了就每次重签，LE 速率限额会把「重启」变成「签不出证书」。
    assert any(":/data" in m for m in mounts) and any(":/config" in m for m in mounts), mounts


def test_the_domain_default_is_the_same_value_in_every_place() -> None:
    caddy_default = re.search(r"\{\$LOOM_GATEWAY_DOMAIN:([^}]+)\}", CADDYFILE.read_text())
    overlay_default = re.search(
        r"LOOM_GATEWAY_DOMAIN: \$\{LOOM_GATEWAY_DOMAIN:-(.*?)\}", GATEWAY_OVERLAY.read_text()
    )
    assert caddy_default and overlay_default, "两处默认值之一没写成带默认的形式"
    assert caddy_default.group(1) == overlay_default.group(1), (
        caddy_default.group(1), overlay_default.group(1)
    )
    assert caddy_default.group(1) in DOCS_DEPLOY.read_text(), "docs/17 没写明同一个域名"


def test_the_overlay_default_must_be_the_empty_safe_form() -> None:
    body = GATEWAY_OVERLAY.read_text()
    assert re.search(r"LOOM_GATEWAY_DOMAIN: \$\{LOOM_GATEWAY_DOMAIN:-[^}]+\}$", body, re.MULTILINE), (
        "compose 侧必须写 ${VAR:-default}：空 env 会传成空串打断 Caddy"
    )
    assert "${LOOM_GATEWAY_DOMAIN:?}" not in body, (
        "禁止 :? 形式——Q200 #33 已定：解析期全局求值会打断其它 overlay/彩排"
    )


def test_the_public_base_url_actually_reaches_the_backend_container() -> None:
    """Q280＝空库真栈首启查出来的缺陷，不是推理。

    compose 从不转发 `LOOM_PUBLIC_BASE_URL`，于是运维在 `.env` 里设了也进不了容器，
    A2A 卡片对外报的是相对路径 `/api/a2a/tasks`（`app/core/a2a/card.py:50,57` 读
    `settings.public_base_url`，该字段默认空串）——外部 Agent 拿到这个地址没法用。
    判据＝旋钮必须存在且默认留空：留空＝沿用相对路径，不预设任何仓内域名。
    """
    env = yaml.safe_load(BASE_COMPOSE.read_text())["services"]["backend"]["environment"]
    assert env.get("LOOM_PUBLIC_BASE_URL") == "${LOOM_PUBLIC_BASE_URL:-}", env.get("LOOM_PUBLIC_BASE_URL")


def test_the_same_domain_rule_is_written_where_the_operator_will_read_it() -> None:
    """Q287：两个对外旋钮（LOOM_GATEWAY_DOMAIN＝站点地址、LOOM_PUBLIC_BASE_URL＝卡片 base）
    必须**同域**。应用对『卡片指向别域』不设防（演练已实证），所以规则必须活在两处：
    运维读的运行手册（docs/17 §1.1）与部署前唯一能拦住人的演练预检（gateway-rehearsal.sh）。"""
    docs17 = DOCS_DEPLOY.read_text()
    assert "同域" in docs17 and "LOOM_GATEWAY_DOMAIN" in docs17 and "LOOM_PUBLIC_BASE_URL" in docs17, (
        "docs/17 没把两个对外旋钮写成同域规则"
    )
    harness = (REPO_ROOT / "infra" / "gateway-rehearsal.sh").read_text()
    assert "配置冲突" in harness and "LOOM_PUBLIC_BASE_URL 的主机" in harness, (
        "演练预检丢了同域检查——别域卡片会静默上线"
    )


def test_topology_free_bool_switches_actually_reach_the_backend_container() -> None:
    """Q291＝Q280"旋钮没接到制品"一族的系统性收口（不是再补一个，是反向枚举）。

    四个**与拓扑无关**、文档已承诺部署期可拧的布尔开关，此前 base/overlay 都不转发 ⇒
    运维照 docs/17 §1、docs/22 在 `.env` 里设了也进不了容器：
      - LOOM_SCHEDULER_ENABLED（SLA sweep 总闸，默认开，config.py:23）
      - LOOM_STAFF_AUTH_ENABLED（Q178/Q203 身份总闸，默认关）
      - LOOM_DISCARD_PURGE_ENABLED（Q187 discarded 物理清理，默认关）
      - LOOM_MCP_ENABLED（Q232 MCP 对外面，默认关）
      - LOOM_PCP_WEEKLY_SCAN_ENABLED（Q294 每周重算提醒第六作业，默认关）
    判据＝旋钮经 base compose backend.environment 转发，且 `${VAR:-默认}` 与代码默认一致。
    刻意**不**进 base 的是 worker/锁/广播族（restock/export/import/fcw worker、
    distributed_lock、config_cache_broadcast）——它们只在多副本/演练时由 ha overlay 打开，
    放进 base 会让单机形态多起消费循环，属另一类旋钮，这里钉住分界不被顺手挪进来。
    """
    env = yaml.safe_load(BASE_COMPOSE.read_text())["services"]["backend"]["environment"]
    expected = {
        "LOOM_SCHEDULER_ENABLED": "true",
        "LOOM_STAFF_AUTH_ENABLED": "false",
        "LOOM_DISCARD_PURGE_ENABLED": "false",
        "LOOM_MCP_ENABLED": "false",
        "LOOM_PCP_WEEKLY_SCAN_ENABLED": "false",
    }
    for var, default in expected.items():
        assert env.get(var) == f"${{{var}:-{default}}}", (var, env.get(var))

    # 拓扑绑定族刻意留在 base 之外（只由 ha/演练 overlay 打开）。
    topology_bound = {
        "LOOM_RESTOCK_WORKER_ENABLED",
        "LOOM_EXPORT_WORKER_ENABLED",
        "LOOM_IMPORT_WORKER_ENABLED",
        "LOOM_FCW_WORKER_ENABLED",
        "LOOM_DISTRIBUTED_LOCK_ENABLED",
        "LOOM_CONFIG_CACHE_BROADCAST_ENABLED",
    }
    assert not (topology_bound & set(env)), topology_bound & set(env)


def test_reverse_proxy_targets_are_real_services_on_real_ports() -> None:
    base = yaml.safe_load(BASE_COMPOSE.read_text())["services"]
    backend_port = re.search(r"--port (\d+)", ENTRYPOINT.read_text()).group(1)
    frontend_port = re.search(
        r"localhost:(\d+)/", str(base["frontend"]["healthcheck"]["test"])
    ).group(1)

    targets = set(re.findall(r"reverse_proxy (\S+)", CADDYFILE.read_text()))
    assert targets == {"backend:8000", "frontend:3000"}, targets
    for host_port in targets:
        name, _, port = host_port.partition(":")
        assert name in base, f"上游 {name} 不是 compose 服务名"
        expected = {"backend": backend_port, "frontend": frontend_port}[name]
        assert port == expected, f"{host_port} 与容器实际监听口 {expected} 不符"
