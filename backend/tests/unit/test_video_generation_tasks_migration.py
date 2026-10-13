"""Contract coverage for the Q354 video-generation-task table + daily-cap seed (0059).

The migration is exercised on real PG by the Migration job (`upgrade head` →
`downgrade -1` → `upgrade`), so this file pins only the halves that a real round-trip
would not name out loud: that the revision chain stayed linear, that the seeded knob is
the same row `config_center/seeds.py` registers (single source of truth, not a copy),
that the anti-double-payment guard is a **partial** unique index declared identically on
both sides (Q288: dropping `sqlite_where` silently turns it into "one task per content
ever"), and that the downgrade still obeys the Q351/Q352 fingerprint rule.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0059_video_generation_tasks.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("video_generation_tasks_0059", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["video_generation_tasks_0059"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0059_video_generation_tasks"
    assert mod.down_revision == "0058_fit_learning_window_seed"


def test_seed_row_is_the_registered_knob(mod):
    # 单一事实源对账：迁移种的必须是 config_center/seeds.py 里那一行，不二次抄写。
    assert mod._SEED[0] == mod._SEED_KEY == "content.video_real_daily_seconds_cap"
    _key, category, value_type, value, source_ref, validation = mod._SEED
    assert (category, value_type, value) == ("content", "int", 120)
    assert validation == {"min": 0}
    assert "原文未给出" in source_ref


def test_open_task_guard_is_partial_and_declared_the_same_way_on_both_sides(mod):
    """`unique=True` 少了 partial 条件＝"一条成品这辈子只能有一条任务"，语义完全不同。

    模型侧漏 `sqlite_where` 会让 SQLite 建出普通唯一索引（集成用例
    `test_terminated_task_frees_the_slot` 当场判红），PG 侧漏 `postgresql_where` 只有真
    PG 看得见——所以两侧必须与同一个常量逐字相等。
    """
    from app.content.video_studio.models import VideoGenerationTask

    guard = next(
        idx for idx in VideoGenerationTask.__table_args__
        if getattr(idx, "name", None) == "uq_video_task_one_open_per_content"
    )
    assert guard.unique is True
    assert len(guard.columns) == 1 and guard.columns[0].name == "content_id"
    assert guard.dialect_kwargs["postgresql_where"].text == mod._OPEN_STATUSES_SQL
    assert guard.dialect_kwargs["sqlite_where"].text == mod._OPEN_STATUSES_SQL
    source = MIGRATION.read_text(encoding="utf-8")
    assert source.count("_OPEN_STATUSES_SQL") == 3  # 定义 ＋ upgrade 两处（pg/sqlite 同常量）
    assert "status IN ('pending_approval','submitted')" in mod._OPEN_STATUSES_SQL


def test_downgrade_checks_the_json_fingerprint_before_deleting(mod):
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade", 1)[1]
    for needle in (
        "sa.select",
        "config_items.c.value",
        "config_items.c.validation",
        # 光是"先 SELECT"不承重：把比较条件整行删掉也照样满足上面三条，所以必须钉住
        # 比的是**种子那两个值**（Q352 批的教训＝装饰性 needle 让门变成摆设）。
        "stored[0] != value",
        "stored[1] != validation",
    ):
        assert needle in downgrade_body, needle
    assert "DELETE FROM config_items" not in downgrade_body
    assert downgrade_body.index("sa.select") < downgrade_body.index("sa.delete")


def test_downgrade_only_removes_its_own_version_history(mod):
    # 全新库上 v1 版本行是 0010 播的（change_note="C2 seed"），不是本迁移造的。
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade", 1)[1]
    assert "config_versions.c.change_note == _SEED_VERSION_NOTE" in downgrade_body
    assert mod._SEED_VERSION_NOTE == "Q354 seed"
