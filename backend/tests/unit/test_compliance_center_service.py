"""PT-COMPLIANCE-V2.0 `latest_report` country 过滤回归测试。

修复前 `CcrReport.country.is_(country)` 在 country 非 None 时编译出非法的
``country IS $2``（Postgres ``IS`` 只能跟 NULL/TRUE/FALSE，导致 500）。
回归锁：None 走 ``IS NULL``，非 None 走等值比较，绝不再生成 ``IS <参数>``。
"""

import pytest
from sqlalchemy.dialects import postgresql

from app.decision.compliance_center import service as svc


class _CapturingSession:
    """捕获传给 ``scalars`` 的 select 语句，供编译检查；结果返回空。"""

    def __init__(self):
        self.stmt = None

    async def scalars(self, stmt):
        self.stmt = stmt
        return _EmptyScalarResult()


class _EmptyScalarResult:
    def all(self):
        return []


def _compiled(session: _CapturingSession) -> str:
    assert session.stmt is not None
    return str(session.stmt.compile(dialect=postgresql.dialect()))


async def test_latest_report_country_none_compiles_is_null():
    session = _CapturingSession()
    await svc.latest_report(session, "pws-1", None)
    sql = _compiled(session)
    assert "country IS NULL" in sql


async def test_latest_report_country_value_compiles_equality_not_is():
    session = _CapturingSession()
    await svc.latest_report(session, "pws-1", "CN")
    sql = _compiled(session)
    # 修复前这里生成 `country IS %(country_1)s`，Postgres 直接语法错误。
    assert "country IS" not in sql
    assert "country = " in sql
