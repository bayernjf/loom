"""Unit coverage for scripts/dba_schema_check.py (Q207).

The script's live database half is exercised in CI's migration job and by hand; this
file pins the halves that are pure logic, so a regression in the mapping or the
comparison is caught even where no PostgreSQL is available.

Two of these are deliberately "verify the verifier" tests: they assert the checker
FIRES on a planted difference, because a checker that has only ever been seen
passing proves nothing.
"""

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dba_schema_check.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("dba_schema_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["dba_schema_check"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- registration


def test_every_model_module_is_visible_to_alembic(mod):
    """The invariant that was broken: env.py saw 14 of 24 modules (44 of 62 tables).

    A table missing from target_metadata is invisible to autogenerate, so one
    `--autogenerate` run would have proposed dropping those 18 tables.
    """
    modules = set(mod.import_model_modules())
    assert modules, "no app.**.models module found - the walk itself is broken"
    assert modules - mod.env_py_registered() == set()


def test_env_registered_reads_the_package_import_form(mod, tmp_path, monkeypatch):
    """env.py uses `from app.x import models as _z`; the parser must accept it."""
    env = tmp_path / "alembic" / "env.py"
    env.parent.mkdir()
    env.write_text(
        "from app.one import models as _a  # noqa\n"
        "import app.two.models as _b\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "BACKEND", tmp_path)
    assert mod.env_py_registered() == {"app.one.models", "app.two.models"}


# ---------------------------------------------------------------- type mapping


@pytest.mark.parametrize(
    ("orm_type", "db_type", "udt"),
    [
        ("VARCHAR(36)", "character varying", "varchar"),
        ("TEXT", "text", "text"),
        ("TIMESTAMP WITH TIME ZONE", "timestamp with time zone", "timestamptz"),
        ("TIMESTAMP WITHOUT TIME ZONE", "timestamp without time zone", "timestamp"),
        ("INTEGER", "integer", "int4"),
        ("BIGINT", "bigint", "int8"),
        ("SMALLINT", "smallint", "int2"),
        ("NUMERIC(10, 4)", "numeric", "numeric"),
        ("FLOAT", "double precision", "float8"),
        ("BOOLEAN", "boolean", "bool"),
        ("JSONB", "jsonb", "jsonb"),
        ("BYTEA", "bytea", "bytea"),
        ("UUID", "uuid", "uuid"),
        ("ARRAY(TEXT)", "array", "_text"),
        ("VECTOR(1536)", "USER-DEFINED", "vector"),
    ],
)
def test_orm_and_db_type_classes_agree(mod, orm_type, db_type, udt):
    """The mapping is the whole reason the checker is trusted; keep both sides aligned."""
    assert mod.classify(orm_type) == mod.db_type_class(db_type, udt)


def test_orm_types_are_compiled_with_the_postgresql_dialect(mod):
    """The generic dialect would render DATETIME / LARGEBINARY and fake up drift.

    Every timestamp column in this repo would have looked wrong, so the mistake is
    loud here rather than silent in CI.
    """
    from sqlalchemy import DateTime, LargeBinary, String
    from sqlalchemy.dialects import postgresql

    assert mod.orm_type_class(DateTime(timezone=True)) == "timestamptz"
    assert mod.orm_type_class(DateTime()) == "timestamp"
    assert mod.orm_type_class(LargeBinary()) == "bytea"
    assert mod.orm_type_class(String(36)) == "text"
    # The distinction being guarded: the generic dialect renders DATETIME, which the
    # PG-side mapper would never match.
    assert "DATETIME" in str(DateTime().compile())
    assert "TIMESTAMP" in str(
        DateTime().compile(dialect=postgresql.dialect())
    )


def test_timestamptz_and_timestamp_do_not_collapse(mod):
    """Regression guard for the checker itself.

    A substring test for "time zone" also matched "timestamp without time zone",
    which would have made a nullability-to-timezone regression invisible on both
    sides - green, and blind.
    """
    assert mod.classify("TIMESTAMP WITH TIME ZONE") == "timestamptz"
    assert mod.classify("TIMESTAMP WITHOUT TIME ZONE") == "timestamp"
    assert mod.db_type_class("timestamp with time zone", "timestamptz") == "timestamptz"
    assert (
        mod.db_type_class("timestamp without time zone", "timestamp") == "timestamp"
    )


def test_unknown_udt_is_reported_not_silently_text(mod):
    assert mod.db_type_class("USER-DEFINED", "citext") == "udt:citext"


# ---------------------------------------------------------------- comparison


def _shape(mod, tables, cols, keys):
    columns = {t: {c: ("not null", "text") for c in cs} for t, cs in cols.items()}
    return {
        "tables": sorted(tables),
        "columns": columns,
        "keys": Counter(keys),
    }


def test_compare_is_quiet_when_shapes_match(mod):
    tables = ["a", "b"]
    cols = {"a": {"id"}, "b": {"id"}}
    keys = [("pk", "a", "id", ""), ("pk", "b", "id", "")]
    db = _shape(mod, tables, cols, keys)
    orm = _shape(mod, tables, cols, keys)
    assert mod.compare(db, orm, []) == []


def test_compare_fires_on_a_duplicate_index(mod):
    """Set-based comparison hides a redundant index; the multiset must not."""
    tables, cols = ["a"], {"a": {"id", "x"}}
    base = [("pk", "a", "id", ""), ("plain", "a", "x", "")]
    db = _shape(mod, tables, cols, base + [("plain", "a", "x", "")])
    orm = _shape(mod, tables, cols, base)
    problems = mod.compare(db, orm, [])
    assert len(problems) == 1
    assert "DB 侧多出" in problems[0] and "x1" in problems[0]


def test_compare_fires_on_missing_column_and_type_class(mod):
    db = _shape(mod, ["a"], {"a": {"id"}}, [("pk", "a", "id", "")])
    db["columns"]["a"]["note"] = ("null", "text")
    db["columns"]["a"]["id"] = ("not null", "integer")
    orm = _shape(mod, ["a"], {"a": {"id"}}, [("pk", "a", "id", "")])
    problems = mod.compare(db, orm, [])
    assert any("列 a.note：DB 有、ORM 无" in p for p in problems)
    assert any("列 a.id" in p for p in problems)


def test_compare_fires_on_an_unregistered_model_module(mod):
    tables, cols, keys = ["a"], {"a": {"id"}}, [("pk", "a", "id", "")]
    db = _shape(mod, tables, cols, keys)
    orm = _shape(mod, tables, cols, keys)
    problems = mod.compare(db, orm, ["app.zzz.models"])
    assert any("app.zzz.models" in p for p in problems)


def test_external_tables_are_dropped_before_comparison(mod):
    """alembic_version must not read as drift, on either side."""
    assert "alembic_version" in mod.EXTERNAL_TABLES
    stripped = mod.strip_external(
        {
            "tables": [],
            "columns": {
                "a": {"id": ("not null", "text")},
                "alembic_version": {"version_num": ("not null", "text")},
            },
            "keys": Counter(
                [("pk", "a", "id", ""), ("pk", "alembic_version", "version_num", "")]
            ),
        }
    )
    assert stripped["tables"] == ["a"]
    assert list(stripped["keys"]) == [("pk", "a", "id", "")]
    orm = _shape(mod, ["a"], {"a": {"id"}}, [("pk", "a", "id", "")])
    assert mod.compare(stripped, orm, []) == []
