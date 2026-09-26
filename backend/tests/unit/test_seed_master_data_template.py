"""Q210 生态：主数据 seed 模板的守卫与演示路径测试。

不验证业务数据（哨兵值不能落库），只验证：① 未改完的 CONFIG 被哨兵拦下；
② --demo 用示例假值能插库并让自检器判为「可发证」。
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import seed_master_data_template as seed_tpl


def test_unedited_config_is_flagged():
    bad = seed_tpl._is_unedited(seed_tpl.CONFIG)
    assert bad, "出厂 CONFIG 应被哨兵识别为未改完"
    assert "PLATFORM" in bad
    assert "GOAL_CODE" in bad


def test_demo_cfg_has_no_sentinels():
    assert seed_tpl._is_unedited(seed_tpl._demo_cfg()) == []


def test_demo_seed_self_checks_ready(capsys):
    seed_tpl.sys.argv = ["seed_master_data_template.py", "--demo"]
    rc = seed_tpl.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "已可发证" in out
    assert "Guard⑥" in out  # cp_law_sensitive_domains 零行提示也存在
