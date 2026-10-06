"""Contract guard for the GitHub Actions CI workflow (Q111).

The workflow is the staging gate collection from docs/17 and docs/08: every
locally agreed gate must be wired in, so a workflow edit cannot silently drop
a gate. This test parses the YAML statically; it does not execute Actions.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _steps(job: dict) -> str:
    return "\n".join(
        (step.get("run", "") if isinstance(step, dict) else "")
        for step in job.get("steps", [])
    )


def test_workflow_wires_every_agreed_gate() -> None:
    data = yaml.safe_load(WORKFLOW.read_text())

    assert "pull_request" in data[True]
    push_branches = data[True]["push"]["branches"]
    assert "main" in push_branches and "dev" in push_branches


def test_superseded_runs_are_cancelled_per_ref() -> None:
    """Q301：同一 ref 上的新推送必须取消旧 run（PR #150 曾堆出一串 cancelled 重复 run）。"""
    data = yaml.safe_load(WORKFLOW.read_text())
    concurrency = data.get("concurrency")
    assert concurrency is not None, "缺 concurrency 组 ⇒ 连推多次会把同 ref 的旧 run 全跑完"
    assert concurrency.get("cancel-in-progress") is True, (
        "cancel-in-progress 必须为 true：同 ref 新推送时旧 run 应立即取消，而不是排队烧额度"
    )
    group = concurrency.get("group", "")
    assert group == "ci-${{ github.ref }}", f"并发组应按 ref 隔离，实际为 {group!r}"

    jobs = data["jobs"]
    backend_runs = _steps(jobs["backend"])
    assert "ruff check ." in backend_runs
    assert "python -m pytest" in backend_runs
    assert "python eval/runner.py" in backend_runs

    frontend_runs = _steps(jobs["frontend"])
    assert "npm run typecheck" in frontend_runs
    for checker in (
        "check-tokens",
        "check-nav",
        "check-content",  # Q122：第 8 个 checker（客户内容页）
        "check-products",
        "check-workbench",
        "check-compliance",
        "check-admin",
        "check-settings",  # Q118：第 7 个 checker 接入 CI（Q117 审计发现本地有、CI 漏跑）
    ):
        assert f"scripts/{checker}.mjs" in frontend_runs


def test_every_committed_checker_script_is_wired() -> None:
    # Q118：目录里新增 check-*.mjs 而 CI 漏接时必须红——CI 集合与磁盘集合一致。
    data = yaml.safe_load(WORKFLOW.read_text())
    frontend_runs = _steps(data["jobs"]["frontend"])

    scripts_dir = REPO_ROOT / "frontend" / "scripts"
    on_disk = {p.name for p in scripts_dir.glob("check-*.mjs")}
    in_ci = {
        token.split("/")[-1]
        for token in frontend_runs.split()
        if token.startswith("scripts/check-") and token.endswith(".mjs")
    }
    assert on_disk == in_ci, f"checker drift: disk={on_disk} ci={in_ci}"


def test_migration_gate_is_wired() -> None:
    """Q207：真 PG16 的迁移门必须在 CI；job 被删或某步被摘就判红（Q118 同一手法）。"""
    data = yaml.safe_load(WORKFLOW.read_text())
    jobs = data["jobs"]
    assert "migration" in jobs, (
        "迁移门被摘掉了：ORM⇄迁移漂移与迁移可逆性会重新变成无人值守的事"
    )
    mig = jobs["migration"]
    assert mig["services"]["postgres"]["image"] == "pgvector/pgvector:pg16", (
        "漂移检查必须跑在带 vector 类型的 PG16 上（Q86 的 embedding 列）"
    )
    runs = _steps(mig)
    assert "alembic upgrade head" in runs
    assert "python scripts/dba_schema_check.py" in runs
    assert "alembic downgrade -1" in runs
    # CI 故意不钉死表数：新增表是常态，钉住会让每次合法迁移都假红。
    assert "--expect-tables" not in runs
    # `alembic check` 实测在 HEAD 上报 19 条命名差异（永久红），不得当门用。
    assert "alembic check" not in runs


def test_real_infra_gate_is_wired() -> None:
    """Q209：真容器集成门必须在 CI；job 被删／service 被摘／env 没注入就判红。

    这一族测的是替身（FakeRedis/FakeStreams/sqlite 单连接）证不了的东西：真 PG
    跨连接池的提交可见性与行级锁串行化、真 Redis 的 SET NX/Lua 释放、Streams
    消费组分片与 XCLAIM 接管、pub/sub 跨连接投递。
    """
    data = yaml.safe_load(WORKFLOW.read_text())
    jobs = data["jobs"]
    assert "real-infra" in jobs, (
        "real-infra 门被摘掉了：多副本原语会退回「只在内存替身下自洽」的状态"
    )
    job = jobs["real-infra"]
    services = job.get("services") or {}
    assert services.get("postgres", {}).get("image") == "pgvector/pgvector:pg16", (
        "fence 表的条件 UPDATE 与行级锁必须在真 PG 上验，sqlite 单连接复现不了"
    )
    redis_image = (services.get("redis") or {}).get("image", "")
    assert redis_image.startswith("redis:"), "Streams/lease/pub-sub 需要真 Redis"
    env = job.get("env") or {}
    assert env.get("LOOM_TEST_REAL_PG_DSN"), "缺 PG DSN ⇒ 用例全 skip ⇒ 静默绿灯"
    assert env.get("LOOM_TEST_REAL_REDIS_URL"), "缺 Redis URL ⇒ 用例全 skip ⇒ 静默绿灯"
    runs = _steps(job)
    assert "tests/integration/test_real_infra.py" in runs


def _job_run(job_name: str, step: str = "") -> str:
    """取该 job 的 run 脚本；给 step 就只取名字含该串的那一步（默认全部拼接）。"""
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"][job_name]
    if not step:
        return _steps(job)
    for item in job.get("steps", []):
        if isinstance(item, dict) and step in item.get("name", ""):
            return item.get("run", "")
    raise AssertionError(f"{job_name} 没有名字含 {step!r} 的 step")


def _run_step_script(
    job_name: str, stub_name: str, summary: str, stub_exit: int = 0, step: str = ""
) -> int:
    """把 CI 里该 step 脚本原样取出来跑，用假的可执行文件（python/docker）喂输出行。

    为什么不只是断言哨兵「文本存在」：env 没设时这一族是「全 skip + exit 0」，
    没有哨兵的 job 会永远绿而从没跑过一行真断言（Q193/Q204 同型教训），而静态
    断言挡不住有人把哨兵改成一句 echo。所以这里喂三种末行真跑它的退出码。
    """
    run = _job_run(job_name, step)
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / stub_name
        stub.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$FAKE_SUMMARY"\n'
            'exit "${FAKE_EXIT:-0}"\n'
        )
        stub.chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            FAKE_SUMMARY=summary,
            FAKE_EXIT=str(stub_exit),
        )
        return subprocess.run(
            ["bash", "-c", run], cwd=tmp, env=env, capture_output=True, check=False
        ).returncode


def _run_sentinel_block(job_name: str, summary: str, pytest_exit: int = 0) -> int:
    return _run_step_script(job_name, "python", summary, pytest_exit)


@pytest.mark.parametrize(
    "summary,expected_exit",
    [
        ("9 skipped in 1.35s", 1),  # env 没生效：全 skip，必须红
        ("no tests ran in 0.03s", 1),  # 收集不到：多半路径被改，必须红
        ("9 passed in 6.49s", 0),  # 真跑过：绿
    ],
)
def test_real_infra_skip_sentinel_fires(summary: str, expected_exit: int) -> None:
    assert _run_sentinel_block("real-infra", summary) == expected_exit, (
        f"哨兵对 summary={summary!r} 的判定不对：expected exit {expected_exit}"
    )


# ---------------------------------------------------------------- Q227 fullchain-e2e


def test_fullchain_e2e_gate_is_wired() -> None:
    """Q227：fullchain-rehearsal（真 PG + alembic + e2e）必须在 CI；job 被删／
    service 被摘／env 没注入就判红。此前这一套只在手动脚本里跑，CI 绿不证明
    生产路径（Q224 又一次证实）。
    """
    data = yaml.safe_load(WORKFLOW.read_text())
    jobs = data["jobs"]
    assert "fullchain-e2e" in jobs, (
        "fullchain-e2e 门被摘掉了：真 PG + alembic + e2e 全链会退回「只在手动脚本里跑」"
    )
    job = jobs["fullchain-e2e"]
    services = job.get("services") or {}
    assert services.get("postgres", {}).get("image") == "pgvector/pgvector:pg16", (
        "e2e 需要带 vector 类型的 PG16（embedding 列在模型网关迁移里）"
    )
    env = job.get("env") or {}
    assert env.get("LOOM_DATABASE_DSN"), "缺 LOOM_DATABASE_DSN ⇒ alembic upgrade 找不到库"
    assert env.get("LOOM_E2E_PG_DSN"), "缺 LOOM_E2E_PG_DSN ⇒ e2e 用例全 skip"
    runs = _steps(job)
    assert "alembic upgrade head" in runs, "缺 alembic upgrade ⇒ 测的是现成库而非全新迁移"
    assert "tests/e2e" in runs, "e2e 测试路径丢失"
    assert "-k synthetic" in runs, (
        "fullchain-e2e 应该只跑 synthetic 变体（不花真 LLM token），real-LLM 留给手动演练"
    )


@pytest.mark.parametrize(
    "summary,expected_exit",
    [
        ("1 skipped in 0.85s", 1),  # env 没生效：skip，必须红
        ("no tests ran in 0.03s", 1),  # 收集不到：-k synthetic 失效或路径被改
        ("1 passed, 1 deselected in 0.84s", 0),  # synthetic 跑过、real-LLM deselected：绿
    ],
)
def test_fullchain_e2e_skip_sentinel_fires(summary: str, expected_exit: int) -> None:
    assert _run_sentinel_block("fullchain-e2e", summary) == expected_exit, (
        f"哨兵对 summary={summary!r} 的判定不对：expected exit {expected_exit}"
    )


# ---------------------------------------------------------------- Q229 infra-static


def test_infra_static_gate_is_wired() -> None:
    """Q229（A3 裁「只加廉价等价门」）：六套演练里不需要多容器/宿主网络的静态半边进 CI。

    搬的是等价断言而非脚本本体：compose 各 overlay 组合静态可解析 + promtool 规则语法。
    ha/load/restore/rpo-rto/pitr 仍本地手动（多容器/宿主网络），是登记的代价判断。
    """
    data = yaml.safe_load(WORKFLOW.read_text())
    jobs = data["jobs"]
    assert "infra-static" in jobs, (
        "infra-static 门被摘掉了：compose 解析与 PromQL 语法会退回「只在本地演练里验」"
    )
    job = jobs["infra-static"]
    # 静态门一旦起 service 就不再廉价；这一族要证的东西本来就不需要容器。
    assert not job.get("services"), "infra-static 不得起任何 service"
    runs = _steps(job)

    # 磁盘上每个 compose overlay 都必须被这道门验过：新增 overlay 而漏接即红
    # （Q118 的 checker 漂移手法——CI 集合与磁盘集合一致）。
    import re

    on_disk = {p.name for p in (REPO_ROOT / "infra").glob("docker-compose*.yml")}
    in_gate = set(re.findall(r"docker-compose[\w.-]*\.yml", runs))
    assert on_disk == in_gate, f"compose overlay 漂移: disk={on_disk} gate={in_gate}"

    # 默认部署路径必须能在不注入任何 secret 时解析（Q185：护栏只许待在 opt-in overlay）。
    assert "config -q" in runs, "缺 compose 静态解析断言"
    # promtool 两条都要查：config（挂载 + rule_files 接线）与 rules（PromQL 语法）。
    assert "check config" in runs and "check rules" in runs, (
        "promtool 只查了一半：config 证接线、rules 证语法，缺哪个都留盲区"
    )


@pytest.mark.parametrize(
    "summary,expected_exit",
    [
        ("SUCCESS: 0 rules found", 1),  # 规则文件被清空/挂载错：语法绿但规则没装载
        ("CHECK FAILED: bad expression", 1),  # 未报出规则数，无法判定
        ("SUCCESS: 10 rules found", 0),  # 正常：绿（刻意不钉条数，加规则不该假红）
        ("SUCCESS: 11 rules found", 0),  # 加一条规则仍绿 ⇒ 条数没被钉死
    ],
)
def test_infra_static_rules_sentinel_fires(summary: str, expected_exit: int) -> None:
    assert _run_step_script(
        "infra-static", "docker", summary, step="Prometheus"
    ) == expected_exit, f"哨兵对 summary={summary!r} 的判定不对：expected exit {expected_exit}"


def test_coverage_is_wired_and_gates_nothing() -> None:
    """覆盖率＝只测不设门（Q221）：接线要在，阈值不能在。"""
    data = yaml.safe_load(WORKFLOW.read_text())
    backend = data["jobs"]["backend"]
    runs = _steps(backend)
    assert "--cov=app" in runs, "后端 pytest 未接覆盖率测量 ⇒ docs/16 §4 的阈值仍是不可判定"
    assert "scripts/coverage_report.py" in runs, "缺覆盖率读数步骤"
    assert "--cov-fail-under" not in runs, (
        "出现了 --cov-fail-under ⇒ 阈值被静默变成硬门；docs/16 §4 是【建议】，"
        "把它变成门需要负责人裁决"
    )
    names = [s.get("name", "") for s in backend.get("steps", []) if isinstance(s, dict)]
    assert any("Coverage report" in n for n in names), f"没有独立的覆盖率读数步骤：{names}"


# ---------------------------------------------------------------- Q222 依赖锁


def _lock_map(path: Path) -> dict[str, str]:
    import re

    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        out[re.split(r"[\[<>=!~;]", name)[0].strip().lower().replace("_", "-")] = version.split("#")[0].strip()
    return out


def test_every_python_job_installs_from_the_dev_lock() -> None:
    """门必须测它将要发出去的那套依赖 ⇒ 三个 Python job 一律从 dev lock 装（Q222）。"""
    text = WORKFLOW.read_text()
    data = yaml.safe_load(text)
    pinned = {name for name, job in data["jobs"].items() if "pip install" in _steps(job)}
    assert pinned == {"backend", "migration", "real-infra", "fullchain-e2e"}, (
        f"装依赖的 job 集合变了：{sorted(pinned)}"
    )
    for name in pinned:
        runs = _steps(data["jobs"][name])
        assert "requirements-dev.lock" in runs, f"{name} 未从 dev lock 安装 ⇒ 门与镜像可各自浮动解析"
        assert "--no-deps" in runs, f"{name} 缺 --no-deps ⇒ 装包时仍会按开放下界重新解析"
    assert "backend[dev]" not in text, "仍有 `pip install -e ./backend[dev]` ⇒ 浮动解析回来了"


def test_image_installs_the_runtime_lock_and_nothing_else() -> None:
    """镜像走 runtime lock：既不能绕锁裸装，也不能把测试工装打进生产（Q222 曾踩）。"""
    docker = (REPO_ROOT / "backend" / "Dockerfile").read_text()
    assert "pip install -r requirements.lock" in docker
    assert "pip install . --no-deps" in docker
    assert "RUN pip install .\n" not in docker, "裸 `pip install .` 会绕过 lock 重新解析依赖"
    runtime = _lock_map(REPO_ROOT / "backend" / "requirements.lock")
    shipped = sorted(k for k in runtime if k.startswith(("mypy", "pytest", "ruff", "coverage")))
    assert not shipped, f"生产镜像将打进开发工具：{shipped}"


def test_runtime_and_dev_locks_agree_and_cover_every_declared_dependency() -> None:
    """两份 lock 的锁死关系：runtime ⊆ dev 且版本逐一对齐，各自覆盖自己那侧的声明。"""
    import re
    import tomllib

    py = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text())
    runtime = _lock_map(REPO_ROOT / "backend" / "requirements.lock")
    dev = _lock_map(REPO_ROOT / "backend" / "requirements-dev.lock")

    def norm(spec: str) -> str:
        return re.split(r"[\[<>=!~;]", spec)[0].strip().lower().replace("_", "-")

    base = [norm(d) for d in py["project"]["dependencies"]]
    extras = [norm(d) for extra in py["project"].get("optional-dependencies", {}).values() for d in extra]
    assert not [k for k in base if k not in runtime], f"runtime lock 缺声明依赖：{[k for k in base if k not in runtime]}"
    assert not [k for k in base + extras if k not in dev], "dev lock 缺 runtime＋dev 全量"
    # CI 装的 dev lock 与镜像装的 runtime lock 必须在同名同版本上重合，否则"门测的＝发出去的"是假话
    clash = sorted(f"{k}: runtime={v} dev={dev[k]}" for k, v in runtime.items() if k in dev and dev[k] != v)
    assert not clash, f"两份 lock 版本冲突：{clash}"
    assert not [k for k in runtime if k not in dev], "runtime lock 有 dev lock 之外的包 ⇒ 镜像装了门没测过的东西"
    for path in (REPO_ROOT / "backend" / "requirements.lock", REPO_ROOT / "backend" / "requirements-dev.lock"):
        body = path.read_text(encoding="utf-8")
        assert not re.search(r"^(-e |.*@ |.*; platform)", body, re.MULTILINE), f"{path.name} 含可编辑/直链/平台标记"
        lines = [ln for ln in body.splitlines() if ln and not ln.startswith("#")]
        assert not [ln for ln in lines if ln.lower().startswith("loom-backend")], f"{path.name} 混入自身包"
