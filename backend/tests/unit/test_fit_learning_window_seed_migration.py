"""Contract coverage for the Q352 fit-learning observation-window seed (0058).

The knob is what makes the advisory window operations-tunable instead of a magic
number in code (Q9), and Q352 also fixed the 0057 lesson: a downgrade must not
delete a row operations has since retuned. The migration itself is exercised on
real PG in the migration job (`upgrade head` → `downgrade -1` → `upgrade`); this
file pins the pure-logic halves so a silent edit to the seed row or the
fingerprint — or a rebase that breaks the revision chain — is caught without a
PostgreSQL.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0058_fit_learning_window_seed.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("fit_learning_window_seed_0058", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["fit_learning_window_seed_0058"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0058_fit_learning_window_seed"
    assert mod.down_revision == "0057_q7_sensitive_industry_seeds"


def test_seed_row_is_the_registered_knob(mod):
    # 单一事实源对账：迁移种的必须是 config_center/seeds.py 里那一行，不二次抄写。
    assert mod._SEED[0] == mod._SEED_KEY == "platform.fit_learning_window_days"
    _key, category, value_type, value, source_ref, validation = mod._SEED
    assert (category, value_type, value) == ("platform", "int", 90)
    assert validation == {"min": 1, "max": 365}
    assert "原文未给出" in source_ref


def test_downgrade_checks_the_json_fingerprint_before_deleting(mod):
    # Q351 纪律：运营经配置中心改过 value/validation 的定制行必须整行保留。
    # 两个 JSONB 列在 SQL 里没有可用的等值算子（jsonb = integer 当场报错），
    # 所以指纹是先 SELECT 出来在 Python 里比，再决定删不删。
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade", 1)[1]
    for needle in (
        "sa.select",
        "config_items.c.value",
        "config_items.c.validation",
        # 只钉前三条是装饰性的：把比较条件整行删掉仍然全绿（Q354 批种植实测），
        # 所以必须钉住比的确实是**种子那两个值**。
        "stored[0] != value",
        "stored[1] != validation",
    ):
        assert needle in downgrade_body, needle
    assert "DELETE FROM config_items" not in downgrade_body
    assert downgrade_body.index("sa.select") < downgrade_body.index("sa.delete")


def test_downgrade_only_removes_its_own_version_history(mod):
    # 全新库上 v1 版本行是 0010 播的（change_note="C2 seed"），不是本迁移造的；
    # 删它等于抹掉别人的回滚面，故版本行删除必须钉在自己的 change_note 上。
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade", 1)[1]
    assert "config_versions.c.change_note == _SEED_VERSION_NOTE" in downgrade_body
    assert mod._SEED_VERSION_NOTE == "Q352 seed"


