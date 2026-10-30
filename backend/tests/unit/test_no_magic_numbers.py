"""Q9「全局魔法数字一律配置化」的可执行守卫（棘轮式）。

Q9 定稿原文（docs/02 §10.9 附注）：「所有拍脑袋数值一律配置化，禁止写死在代码中」。
此前这一条**只有人工登记、没有强制手段**——docs/25 Q9 行的缺口原文就是
「"禁止硬编码"无强制手段：无 lint／哨兵测试扫残留魔法数字」。

本守卫刻意不做成「零容忍全清」，因为那是假话：实测量存里绝大多数浮点**本就该留在代码里**
（指标桶、轮询间隔、锁 TTL、Σ 容差、替身固定分）。真正要禁的是**业务阈值与比例**
继续长进代码。所以采用**棘轮**：`ALLOWLIST` 逐文件登记当前存量值集合，测试实扫后要求
**完全相等**——

- 新增任何未登记的浮点 ⇒ 红（须改走配置中心，或显式登记并附 Q 溯源）；
- 登记项在代码里消失 ⇒ 也红（防止"把登记删掉"来绕过棘轮）。

范围与排除（写死在本文件里，不靠配置，避免守卫自身可被配置放宽）：

- 只扫 `app/**/*.py` 的**浮点常量**（`ast.Constant` 且 `isinstance(value, float)`）。
  走 AST 而不是正则：注释与字符串里的数字天然不计入——下面两条用例专门钉住这一点，
  免得本守卫退化成"看起来在扫、其实靠正则误判"。
- 排除**配置载体自身**：`app/core/config.py`（env 默认值）与所有 `*seeds.py`
  （配置中心种子表，它们的职责就是承载数值）。
- **整数不在本批范围**：状态码／时长／数量三类语义分散且量大，另批再扩；
  本批先把"比例与阈值"这一类钉住。

`PENDING_BUSINESS_CALIBRATION` 是与棘轮独立的第二条判据：被登记为「工程甲案、业务待给真值」
的数值（当前只有 fit_score 自学习的归一化基准，即 docs/19 清单二第 16 项②）必须显式列在那里。
否则"等业务给规则"这件事会在代码里被悄悄当成既成事实——Q352 接 advisory 时就是这么挂着的。
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"

# 配置载体自身：数值放这里是对的，不该被守卫判红。
EXCLUDED_NAMES = {"config.py"}
EXCLUDED_SUFFIXES = ("seeds.py",)

# 逐文件登记当前存量的浮点值集合（值集合，不是出现次数——本守卫管"有没有新数值"）。
# 分类注释说明"为什么这个数可以留在代码里"，新增登记必须同样带一句理由。
ALLOWLIST: dict[str, set[float]] = {
    # 规则层的 0.0/1.0（分位、满分、缺省占比）与纯结构性零值——不是业务阈值。
    "app/content/quality.py": {0.0, 1.0},
    "app/core/effects/service.py": {0.0},
    "app/core/model_registry/extraction.py": {0.0, 1.0},
    # 0.0＝无定价时的默认单价；300.0＝5min 后台刷新间隔；2.0＝停止线程等待秒数。
    "app/core/model_registry/hub.py": {0.0, 2.0, 300.0},
    "app/product/atom/atom_rules.py": {0.0, 1.0},
    "app/product/condition/pwc_rules.py": {0.0},
    "app/product/condition/service.py": {0.0},
    "app/product/modeling/c1.py": {1.0},
    "app/product/modeling/c7.py": {1.0},
    "app/product/whitelist_center/pws_rules.py": {1.0},
    # Σ≤1.0 等校验的浮点容差：不是业务数值，是数值比较的 epsilon。
    "app/platform/platform_adaptation/pa_rules.py": {1e-09, 1.0},
    # 0.0＝Q368 硬闸 #12 的 AI 候选强制零分（AI 无源不得编造主观分，四维恒 0 待人工评估）。
    "app/platform/platform_adaptation/service.py": {1e-09, 0.0},
    # 指标库：Prometheus histogram 桶边界 + 时序窗口秒数（埋点口径，非业务规则）。
    "app/core/metrics/business.py": {0.0, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0},
    "app/core/metrics/registry.py": {
        0.0, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 1e15,
    },
    # 运行时序：广播间隔、锁 TTL、worker 轮询、驱动超时兜底（env 可覆盖的实现默认值）。
    "app/core/config_center/broadcast.py": {1.0, 30.0},
    "app/core/exports/worker.py": {5.0},
    "app/core/imports/worker.py": {5.0},
    "app/core/locking/service.py": {60.0},
    "app/core/model_registry/drivers.py": {0.5, 30.0},
    "app/final/fcw_worker/worker.py": {5.0},
    # synthetic 替身的固定分数：仓内无真凭证时的确定性输出（Q82 起）。
    "app/core/model_registry/synthetic.py": {
        0.0, 0.04, 0.2, 0.55, 0.62, 0.75, 0.78, 0.8, 0.82, 0.85, 0.88, 0.9, 0.92, 0.95, 0.99, 1.0,
    },
    # fit_score 自学习建议的归一化基准：见 PENDING_BUSINESS_CALIBRATION。
    "app/platform/platform_adaptation/fit_learning.py": {0.0, 1.0, 100.0, 1000.0, 100000.0},
}

# 工程甲案、业务待给真值（禁臆造红线：不得由工程代裁）。
# 当前仅 docs/19 清单二第 16 项②「归一化基准」：代码里已就地标注【实现补：工程草案值】。
PENDING_BUSINESS_CALIBRATION: dict[str, set[float]] = {
    "app/platform/platform_adaptation/fit_learning.py": {100.0, 1000.0, 100000.0},
}


def is_excluded(path: Path) -> bool:
    """配置载体自身豁免（env 默认值与配置中心种子表）。"""
    return path.name in EXCLUDED_NAMES or path.name.endswith(EXCLUDED_SUFFIXES)


def scan_file(path: Path) -> set[float]:
    """一个文件里的浮点常量集合；只认 AST 常量，注释与字符串里的数字不算。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    }


def scan_app(app_dir: Path | None = None) -> dict[str, set[float]]:
    root = app_dir or APP_DIR
    found: dict[str, set[float]] = {}
    for path in sorted(root.rglob("*.py")):
        if is_excluded(path):
            continue
        values = scan_file(path)
        if values:
            found[_key(path, root)] = values
    return found


def _key(path: Path, root: Path) -> str:
    return str(path.relative_to(root.parent)) if root.name == "app" else str(path)


# --- 判据 ---


def test_ratchet_scan_matches_allowlist():
    """棘轮本体：实扫存量 == 登记存量。新增未登记浮点、或登记项消失，都判红。"""
    found = scan_app()
    new_keys = sorted(set(found) - set(ALLOWLIST))
    gone_keys = sorted(set(ALLOWLIST) - set(found))
    new_values = {
        path: sorted(found[path] - ALLOWLIST[path]) for path in found.keys() & ALLOWLIST.keys()
    }
    new_values = {p: v for p, v in new_values.items() if v}
    gone_values = {
        path: sorted(ALLOWLIST[path] - found[path]) for path in found.keys() & ALLOWLIST.keys()
    }
    gone_values = {p: v for p, v in gone_values.items() if v}
    assert not (new_keys or gone_keys or new_values or gone_values), (
        "Q9 魔法数字登记与实存不一致："
        f"未登记文件={new_keys}，登记但已无该文件={gone_keys}，"
        f"未登记值={new_values}，已消失的登记值={gone_values}。"
        "新增数值须走配置中心（本批不豁免）；确属实现常量才可登记，并附一句为什么它可以留在代码里。"
    )


def test_pending_business_calibration_is_still_declared():
    """待业务给真值的数值必须持续显式登记——防止"等业务"在代码里变成既成事实。"""
    for path, values in PENDING_BUSINESS_CALIBRATION.items():
        assert path in ALLOWLIST, f"{path} 已在 ALLOWLIST 中消失，待校准登记须与棘轮同步"
        assert values <= ALLOWLIST[path], f"{path} 的待校准值不在棘轮登记里：{values}"
        assert values & scan_app()[path], f"{path} 的待校准值在代码里已不存在，登记须同步清理"


def test_scanner_ignores_comments_and_strings(tmp_path):
    """自证判据不是"看起来在扫"：注释与文档字符串里的数字不算常量。"""
    app = tmp_path / "app"
    app.mkdir()
    (app / "doc_only.py").write_text(
        '"""文档里写 0.85 与 1e-09 都不算。"""\n'
        "# 注释里的 0.42 也不算\n"
        "TEXT = '字符串里的 3.14 同样不算'\n",
        encoding="utf-8",
    )
    assert scan_app(app) == {}


def test_scanner_flags_real_constant(tmp_path):
    """反向判据：真常量必须被抓到——否则上一条会因"扫不出任何东西"而假绿。"""
    app = tmp_path / "app"
    app.mkdir()
    (app / "real.py").write_text("THRESHOLD = 0.73\n", encoding="utf-8")
    assert scan_app(app) == {"app/real.py": {0.73}}


def test_config_carriers_are_excluded_by_design(tmp_path):
    """排除规则本身也要被钉住：否则"排除"能被人当成藏数值的后门。"""
    app = tmp_path / "app"
    (app / "core").mkdir(parents=True)
    (app / "core" / "config.py").write_text("TIMEOUT = 12.5\n", encoding="utf-8")
    (app / "core" / "config_center").mkdir()
    (app / "core" / "config_center" / "seeds.py").write_text("DEFAULTS = [1.25]\n", encoding="utf-8")
    (app / "biz.py").write_text("RATE = 1.25\n", encoding="utf-8")
    assert scan_app(app) == {"app/biz.py": {1.25}}
