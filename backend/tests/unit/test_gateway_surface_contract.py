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
