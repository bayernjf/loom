"""`backend/.env` 载体契约（Q239）。

`.env` 只承载 `Settings` 字段。pydantic-settings 默认 `extra="forbid"`，所以往
`.env` 里放一个 `Settings` 不认识的名字（例如 `LOOM_LLM_BASE_URL_AGNES`）不是
"静默无效"，而是 `Settings()` 抛 `ValidationError`、**整个进程起不来**。

另一半：本仓没有 `load_dotenv`，pydantic-settings 只把 `.env` 读进 `Settings`
对象、**不写进 `os.environ`**；而 `app/core/model_registry/drivers.py` 是直接读
`os.environ["LOOM_LLM_BASE_URL_<PROVIDER>"]` 的。⇒ 直接读 os.environ 的变量必须
走可 source 的 shell 载体，不能进 `.env`。

本文件守的是第一半（`.env.example` 只能放 Settings 字段）；第二半写在
`.env.example` 的说明里，由 `test_settings_forbids_unknown_env_keys` 钉住"崩"这个
前提确实成立（否则这条契约会退化成"静默无效"）。
"""

import pathlib
import re

import pytest
from pydantic import ValidationError

from app.core.config import Settings

# tests/unit/x.py -> backend/
ENV_EXAMPLE = pathlib.Path(__file__).resolve().parents[2] / ".env.example"

# 只认行首的大写键，故 `#   POSTGRES_PASSWORD=…` 这类注释行不会被误捕。
KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)


def _keys(text: str) -> list[str]:
    return KEY_RE.findall(text)


def _offenders(keys: list[str]) -> list[str]:
    """返回既非 `LOOM_` 前缀、又不是 `Settings` 字段的键。"""
    fields = set(Settings.model_fields)
    return [
        k
        for k in keys
        if not k.startswith("LOOM_") or k[len("LOOM_") :].lower() not in fields
    ]


def test_env_example_carries_only_settings_fields():
    keys = _keys(ENV_EXAMPLE.read_text())
    assert keys, "解析不出任何键——是解析器坏了，不是契约成立"
    assert _offenders(keys) == [], (
        f"{ENV_EXAMPLE.name} 里出现 Settings 不认识的名字：{_offenders(keys)}。"
        "把它们放进 .env 会让 Settings() 抛 ValidationError、进程起不来；"
        "直接读 os.environ 的变量请走 backend/.env.shell（Q239）。"
    )


def test_the_scan_can_fire():
    """正向对照：只在真文件上跑绿的检查等于没有检查。"""
    assert _offenders(["LOOM_MASTER_KEY"]) == []
    assert _offenders(["LOOM_LLM_BASE_URL_AGNES"]) == ["LOOM_LLM_BASE_URL_AGNES"]
    assert _offenders(["POSTGRES_PASSWORD"]) == ["POSTGRES_PASSWORD"]


def test_settings_forbids_unknown_env_keys():
    """`extra="forbid"` 是这条契约"启动即崩、而非静默无效"的前提。"""
    assert Settings.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError) as exc:
        Settings(loom_llm_base_url_agnes="https://example.invalid/v1")
    assert exc.value.errors()[0]["type"] == "extra_forbidden"
