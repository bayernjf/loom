"""DBA ⇄ ORM schema drift check against a real PostgreSQL (Q207).

Why it exists: the Q153 / Q171 / Q179 rounds each did this comparison by hand in a
throwaway pg16 container and then threw the comparison away, so "zero drift" has to
be re-earned by hand every few dozen slices. This turns it into a gate that CI can
run on every push.

Compared, against a live database (normally `alembic upgrade head` on fresh PG16):
  * table sets (ORM declared vs DB present);
  * per table: column names, nullability, coarse type class;
  * primary keys, foreign keys (column pairs), unique constraints, indexes
    - matched as (kind, table, columns, uniqueness), NOT by name: the repo has no
      metadata naming convention and its migrations are hand-written, so names on
      the two sides legitimately differ;
  * a failure the hand rounds structurally could not see: a model module that
    `alembic/env.py` never imports. Such a table is invisible to migrations AND to
    autogenerate, so "model matches migration" can hold while the table was never
    migrated at all.

Deliberately NOT checked (say it rather than fake it): column lengths and full type
precision (String(36) and Text both map to class "text"), index storage method,
defaults, and CHECK constraints. A length regression therefore passes this gate -
the same class of defect Q154 caught by hand (request_id varchar(36) vs a 40-char
uuid) is out of scope here and stays with the real-infra tests.

Usage:
    LOOM_DATABASE_DSN=postgresql+asyncpg://loom:loom@127.0.0.1:55455/loom \
        python scripts/dba_schema_check.py [--expect-tables 62]

Exit 0 = no drift, 1 = drift (each difference printed), 2 = bad invocation.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import pkgutil
import re
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.db import Base

# Tables owned by nothing in this repo: alembic bookkeeping, and the reference-
# system table the PostGIS-flavoured pgvector image ships with.
EXTERNAL_TABLES = frozenset({"alembic_version", "spatial_ref_sys"})

# ---------------------------------------------------------------- ORM side


def import_model_modules() -> list[str]:
    """Import every app.**.models module so Base.metadata is complete."""
    import app

    found = []
    for mod in pkgutil.walk_packages(app.__path__, prefix="app."):
        if mod.name.endswith(".models"):
            importlib.import_module(mod.name)
            found.append(mod.name)
    return sorted(found)


def env_py_registered() -> set[str]:
    """Model modules that alembic/env.py imports - i.e. what migrations can see."""
    src = (BACKEND / "alembic" / "env.py").read_text(encoding="utf-8")
    pkgs = re.findall(r"^from\s+(app\.[\w.]+)\s+import\s+models\b", src, re.MULTILINE)
    mods = re.findall(r"^import\s+(app\.[\w.]*\.models)\b", src, re.MULTILINE)
    # env.py imports the *package*; the walk yields module names - normalise first.
    return {f"{m}.models" for m in pkgs} | set(mods)


def classify(sql_type: str) -> str:
    """Coarse type class from a SQL type string. Pure, so it is unit-testable."""
    s = sql_type.lower()
    if "vector" in s:
        return "vector"
    if s.startswith(("varchar", "character varying", "text", "char")):
        return "text"
    if s.startswith("timestamp"):
        # "without time zone" contains "time zone" - order matters or both sides
        # collapse to timestamptz and the check silently loses timezone drift.
        if "without time zone" in s:
            return "timestamp"
        if "time zone" in s or "timezone" in s:
            return "timestamptz"
        return "timestamp"
    if s.startswith("smallint"):
        return "smallint"
    if s.startswith("int"):
        return "integer"
    if s.startswith("bigint"):
        return "bigint"
    if s.startswith(("numeric", "decimal", "float", "double", "real")):
        return "number"
    if s.startswith("boolean"):
        return "boolean"
    if s.startswith(("jsonb", "json")):
        return "jsonb"
    if "array" in s:
        return "array"
    if s.startswith("uuid"):
        return "uuid"
    return s


def orm_type_class(coltype) -> str:
    """Class of an ORM column type as PostgreSQL would create it.

    Compiling with the PostgreSQL dialect is not cosmetic: the generic dialect
    renders DateTime (not TIMESTAMPTZ) and LargeBinary (not BYTEA), which would
    invent drift on every timestamp column.
    """
    return classify(str(coltype.compile(dialect=postgresql.dialect())))


def strip_external(payload: dict) -> dict:
    """Drop the tables this repo does not own, so they never read as drift."""
    columns = {k: v for k, v in payload["columns"].items() if k not in EXTERNAL_TABLES}
    keys = Counter({k: n for k, n in payload["keys"].items() if k[1] not in EXTERNAL_TABLES})
    return {"tables": sorted(columns), "columns": columns, "keys": keys}


def collect_orm() -> dict:
    md = Base.metadata
    columns: dict[str, dict[str, tuple[str, str]]] = {}
    keys: Counter = Counter()
    for tbl in sorted(md.tables):
        t = md.tables[tbl]
        columns[tbl] = {
            c.name: ("null" if c.nullable else "not null", orm_type_class(c.type))
            for c in t.columns
        }
        pk = [c.name for c in t.primary_key.columns]
        if pk:
            keys[("pk", tbl, ",".join(pk), "")] += 1
        for f in t.foreign_keys:
            keys[("fk", tbl, f"{f.parent.name}=>{f.column.name}", f.column.table.name)] += 1
        for cons in t.constraints:
            if isinstance(cons, UniqueConstraint):
                cols = ",".join(sorted(c.name for c in cons.columns))
                if cols:
                    keys[("unique", tbl, cols, "")] += 1
        for idx in t.indexes:
            cols = ",".join(c.name for c in idx.columns)
            keys[("unique" if idx.unique else "plain", tbl, cols, "")] += 1
    return strip_external({"tables": [], "columns": columns, "keys": keys})


# ------------------------------------------------------------------ DB side

COLS_SQL = """
    SELECT table_name, column_name, is_nullable, data_type, udt_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, ordinal_position
"""

PK_SQL = """
    SELECT c.relname, string_agg(a.attname::text, ',' ORDER BY x.ord)
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS x(k, ord)
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = x.k
    WHERE con.contype = 'p' AND c.relnamespace = 'public'::regnamespace
    GROUP BY c.relname
"""

FK_SQL = """
    SELECT c.relname, fc.relname, a.attname, ra.attname
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_class fc ON fc.oid = con.confrelid
    JOIN LATERAL unnest(con.conkey, con.confkey) AS x(k, rk) ON true
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = x.k
    JOIN pg_attribute ra ON ra.attrelid = con.confrelid AND ra.attnum = x.rk
    WHERE con.contype = 'f' AND c.relnamespace = 'public'::regnamespace
"""

UQ_SQL = """
    SELECT c.relname, string_agg(a.attname::text, ',' ORDER BY a.attname)
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    CROSS JOIN LATERAL unnest(con.conkey) AS x(k)
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = x.k
    WHERE con.contype = 'u' AND c.relnamespace = 'public'::regnamespace
    GROUP BY c.relname
"""

# Indexes that exist only because a PK/UQ/FK constraint created them are left out:
# those are compared as constraints above, and pgvector/expression indexes are
# matched on their column list only (expressions render as NULL in pg_index).
IDX_SQL = """
    SELECT c.relname,
           coalesce(string_agg(a.attname::text, ',' ORDER BY x.ord), ''),
           i.indisunique
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indrelid
    LEFT JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS x(k, ord) ON true
    LEFT JOIN pg_attribute a
           ON a.attrelid = i.indrelid AND a.attnum = x.k AND x.k > 0
    WHERE c.relnamespace = 'public'::regnamespace
      AND NOT i.indisprimary
      AND NOT EXISTS (
            SELECT 1 FROM pg_constraint con WHERE con.conindid = i.indexrelid
      )
    GROUP BY c.relname, i.indisunique, i.indexrelid
"""


def db_type_class(data_type: str, udt_name: str) -> str:
    t = data_type.lower()
    if t == "user-defined":
        return "vector" if "vector" in udt_name.lower() else f"udt:{udt_name}"
    if t == "text" or t.startswith(("character varying", "character (")):
        return "text"
    if t.startswith("timestamp"):
        if "without time zone" in t:
            return "timestamp"
        return "timestamptz" if "time zone" in t else "timestamp"
    if t == "smallint":
        return "smallint"
    if t == "integer":
        return "integer"
    if t == "bigint":
        return "bigint"
    if t in ("numeric", "double precision", "real"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t in ("json", "jsonb"):
        return "jsonb"
    if t == "uuid":
        return "uuid"
    if t.startswith("array"):
        return "array"
    return t


async def collect_db(engine) -> dict:
    columns: dict[str, dict[str, tuple[str, str]]] = {}
    keys: Counter = Counter()
    async with engine.connect() as conn:
        for tbl, col, nullable, dtype, udt in (await conn.execute(text(COLS_SQL))).all():
            columns.setdefault(tbl, {})[col] = (
                "null" if nullable == "YES" else "not null",
                db_type_class(dtype, udt),
            )
        for tbl, cols in (await conn.execute(text(PK_SQL))).all():
            keys[("pk", tbl, cols, "")] += 1
        for tbl, reftbl, col, refcol in (await conn.execute(text(FK_SQL))).all():
            keys[("fk", tbl, f"{col}=>{refcol}", reftbl)] += 1
        for tbl, cols in (await conn.execute(text(UQ_SQL))).all():
            keys[("unique", tbl, cols, "")] += 1
        for tbl, cols, uniq in (await conn.execute(text(IDX_SQL))).all():
            keys[("unique" if uniq else "plain", tbl, cols, "")] += 1
    return strip_external({"tables": [], "columns": columns, "keys": keys})


# ------------------------------------------------------------------- compare


def compare(db: dict, orm: dict, unregistered: list[str]) -> list[str]:
    problems: list[str] = []
    for tbl in sorted(set(orm["tables"]) - set(db["tables"])):
        problems.append(f"表 {tbl}：ORM 声明了，DB 里没有（迁移没建？）")
    for tbl in sorted(set(db["tables"]) - set(orm["tables"])):
        problems.append(f"表 {tbl}：DB 里有，ORM 没声明（遗留表？）")

    for tbl in sorted(set(db["tables"]) & set(orm["tables"])):
        dcols, ocols = db["columns"][tbl], orm["columns"][tbl]
        for c in sorted(set(ocols) - set(dcols)):
            problems.append(f"列 {tbl}.{c}：ORM 有、DB 无")
        for c in sorted(set(dcols) - set(ocols)):
            problems.append(f"列 {tbl}.{c}：DB 有、ORM 无")
        for c in sorted(set(dcols) & set(ocols)):
            if dcols[c] != ocols[c]:
                problems.append(
                    f"列 {tbl}.{c}：DB={dcols[c]} 但 ORM={ocols[c]}"
                )

    # Compared as a multiset: a second index over the same columns must show up,
    # otherwise a redundant duplicate index - the classic slow-query cause -
    # is invisible to a set-based comparison.
    for key in sorted(db["keys"] - orm["keys"]):
        problems.append(f"DB 侧多出 {key} x{db['keys'][key] - orm['keys'][key]}")
    for key in sorted(orm["keys"] - db["keys"]):
        problems.append(f"ORM 侧声明了但 DB 没有 {key} x{orm['keys'][key] - db['keys'][key]}")

    for mod in unregistered:
        problems.append(
            f"模型模块 {mod} 没被 alembic/env.py 导入：迁移看不见它，"
            "于是「模型⇄迁移一致」会在它的表根本没被创建的情况下依然成立"
        )
    return problems


async def run(dsn: str, expect_tables: int) -> int:
    modules = import_model_modules()
    unregistered = [m for m in modules if m not in env_py_registered()]
    engine = create_async_engine(dsn)
    try:
        db = await collect_db(engine)
    finally:
        await engine.dispose()
    orm = collect_orm()

    ncols = sum(len(v) for v in db["columns"].values())
    nocols = sum(len(v) for v in orm["columns"].values())
    kinds = {"pk": 0, "fk": 0, "unique": 0, "plain": 0}
    for k in db["keys"]:
        kinds[k[0]] += 1
    print(
        f"模型模块 {len(modules)} 个（env.py 未注册 {len(unregistered)}）；"
        f"DB：表 {len(db['tables'])}／列 {ncols}／PK {kinds['pk']}／"
        f"FK {kinds['fk']}／唯一约束或唯一索引 {kinds['unique']}"
        f"／普通索引 {kinds['plain']}"
    )
    print(f"ORM metadata：表 {len(orm['tables'])}／列 {nocols}")

    problems = compare(db, orm, unregistered)
    if expect_tables and len(db["tables"]) != expect_tables:
        problems.append(f"表数 {len(db['tables'])} 与预期 {expect_tables} 不符")

    if problems:
        print("\n".join(f"  ✗ {p}" for p in problems))
        print(f"DRIFT：{len(problems)} 处")
        return 1
    print("NO DRIFT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("LOOM_DATABASE_DSN", ""))
    ap.add_argument("--expect-tables", type=int, default=0)
    ns = ap.parse_args()
    if not ns.dsn:
        print("需要 LOOM_DATABASE_DSN 或 --dsn", file=sys.stderr)
        return 2
    return asyncio.run(run(ns.dsn, ns.expect_tables))


if __name__ == "__main__":
    sys.exit(main())
