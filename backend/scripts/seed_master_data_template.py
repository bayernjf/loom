"""主数据回填 seed 模板（Q210 生态，与 `check_master_data.py` 同口径）。

用途：业务方按 docs/19 §0.2「最小可发证清单」回填四表时，本模板给出**一份可直接改值运行**
的骨架。它用与自检器相同的 ORM 模型写库，因此**结构永远和 schema 对齐**，不会因列名漂移
而写出错列；写完后直接调用 `evaluate` 打印「可发证」判定，并可接 `check_master_data.py` 复核。

判定口径（与 `check_master_data.py` / 发证解析器一致）：只看 `status=="active"`，不看 `gate`。
最小可发证 = 1 个 active 发布位（取其 platform）＋ 该 platform 下 1 条 active PCP
（product_space×tenant×platform）＋ 该 (ps, tenant, platform, goal) 三包 CSP/CSTP/CEP 齐备
＋ 1 个 active 目的字典。

⚠ **本文件是模板，不是真实业务数据**：顶部 CONFIG 全是 `<REPLACE_ME_...>` 哨兵值。
   运行真实回填前必须把每个哨兵改成业务真实值；**未改完就运行会被脚本中止**，防止把占位符
   写进生产库（不臆造业务事实）。`--demo` 模式用一组明显是示例的假值跑通机制，仅供验证脚本本身。

完整主数据（product_spaces / PWS 冻结 / 合规报告等）才能真跑通段1→6→10 产出 `final_id`，
本模板只覆盖**自检器口径的最小集**——那是一切的前置。详见 docs/19。

用法：
    # 验证脚本机制（不碰真实库，用内存库演示插入＋自检）：
    python scripts/seed_master_data_template.py --demo
    # 只打印将写入什么、不落库：
    python scripts/seed_master_data_template.py --dry-run
    # 真实回填（先把 CONFIG 哨兵全部改成真实值）：
    python scripts/seed_master_data_template.py --dsn "$LOOM_DATABASE_DSN"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

import check_master_data as cmd  # 同目录自检器
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import Base
from app.decision.compliance_center.models import CpLawSensitiveDomain
from app.decision.layer_strategy.models import KIND_CEP, KIND_CSP, KIND_CSTP, Package
from app.platform.platform_adaptation.models import PcpWeightTable, PublishSlot
from app.product.condition.models import ContentGoal

# ╔════════════════════════════════════════════════════════════════════════╗
# ║  CONFIG —— 回填前把每个 <REPLACE_ME_...> 换成业务真实值。                  ║
# ║  三个 id 用你系统里已有的真实 UUID/编码；platform 在发布位与 PCP/三包必须一致。 ║
# ╚════════════════════════════════════════════════════════════════════════╝
CONFIG = {
    # 平台编码：必须同时出现在发布位、PCP、三包（自检器据此匹配发布平台）。
    "PLATFORM": "<REPLACE_ME_PLATFORM>",  # 例：wechat / douyin / xiaohongshu
    # 租户与产品空间：PCP 与三包必须同 (tenant, product_space)。
    "TENANT_ID": "<REPLACE_ME_TENANT_ID>",
    "PRODUCT_SPACE_ID": "<REPLACE_ME_PRODUCT_SPACE_ID>",
    # 目的字典 code：必须是 content_goals 里 active 的一个；三包 goal 与之相同。
    "GOAL_CODE": "<REPLACE_ME_GOAL_CODE>",  # 例：EDUCATION / CONVERSION
    # 发布位：code 全局唯一，name/slot_type 按真实值填。
    "SLOT_CODE": "<REPLACE_ME_SLOT_CODE>",
    "SLOT_NAME": "<REPLACE_ME_SLOT_NAME>",
    "SLOT_TYPE": "<REPLACE_ME_SLOT_TYPE>",  # 例：short_video / community /图文种草
    # 三包 payload：按各包型必填键填真实内容（键集见 app/decision/layer_strategy/models.py
    # 的 KIND_PAYLOAD_KEYS）。这里是占位结构，业务方替换值。
    "CSP_PAYLOAD": {
        "goal": "<REPLACE_ME_GOAL_CODE>",
        "stage": "<REPLACE_ME_STAGE>",
        "angle": "<REPLACE_ME_ANGLE>",
        "intensity": "<REPLACE_ME_INTENSITY>",
        "cta": "<REPLACE_ME_CTA>",
        "emotion": "<REPLACE_ME_EMOTION>",
    },
    "CSTP_PAYLOAD": {"struct": "<REPLACE_ME_STRUCT>"},
    "CEP_PAYLOAD": {
        "tone": "<REPLACE_ME_TONE>",
        "perspective": "<REPLACE_ME_PERSPECTIVE>",
        "explicit": "<REPLACE_ME_EXPLICIT>",
        "soften": "<REPLACE_ME_SOFTEN>",
    },
    # PCP 权重：17 池权重初值（按平台类型模板派生；此处占位，业务方替换）。
    "PCP_WEIGHTS": {"<REPLACE_ME_DIMENSION>": 1.0},
    # 可选：敏感领域清单。留空列表 ⇒ cp_law_sensitive_domains 为零行，Guard⑥ 走默认放行
    # （可配置非永久豁免，首批选产品应避开拟启用敏感类目的行业）。填了则 Guard⑥ 按清单审。
    "SENSITIVE_DOMAINS": [],  # 例：[{"code":"MEDICAL","name":"医疗健康"}, ...]
}

_SENTINEL = "<REPLACE_ME_"


def _is_unedited(cfg: dict) -> list[str]:
    """返回仍带哨兵前缀的字段名；空列表＝已全部改完。"""
    bad: list[str] = []
    flat = {
        "PLATFORM": cfg["PLATFORM"],
        "TENANT_ID": cfg["TENANT_ID"],
        "PRODUCT_SPACE_ID": cfg["PRODUCT_SPACE_ID"],
        "GOAL_CODE": cfg["GOAL_CODE"],
        "SLOT_CODE": cfg["SLOT_CODE"],
        "SLOT_NAME": cfg["SLOT_NAME"],
        "SLOT_TYPE": cfg["SLOT_TYPE"],
        "CSP_PAYLOAD": str(cfg["CSP_PAYLOAD"]),
        "CSTP_PAYLOAD": str(cfg["CSTP_PAYLOAD"]),
        "CEP_PAYLOAD": str(cfg["CEP_PAYLOAD"]),
        "PCP_WEIGHTS": str(cfg["PCP_WEIGHTS"]),
    }
    for k, v in flat.items():
        if _SENTINEL in str(v) or "REPLACE_ME" in str(v):
            bad.append(k)
    return bad


def build_rows(cfg: dict) -> dict:
    """把 CONFIG 落成 ORM 对象（未落库）。"""
    platform = cfg["PLATFORM"]
    tenant = cfg["TENANT_ID"]
    ps = cfg["PRODUCT_SPACE_ID"]
    goal = cfg["GOAL_CODE"]

    slot = PublishSlot(
        slot_id=str(uuid.uuid4()),
        platform=platform,
        code=cfg["SLOT_CODE"],
        name=cfg["SLOT_NAME"],
        slot_type=cfg["SLOT_TYPE"],
        status="active",
        gate="approved",
    )
    pcp = PcpWeightTable(
        pcp_id=str(uuid.uuid4()),
        tenant_id=tenant,
        product_space_id=ps,
        platform=platform,
        weights=dict(cfg["PCP_WEIGHTS"]),
        status="active",
        template_code="PT-PCP-V1.5",
    )
    cg = ContentGoal(code=goal, status="active")
    packages = [
        Package(
            kind=KIND_CSP, tenant_id=tenant, product_space_id=ps,
            platform=platform, goal=goal, payload=dict(cfg["CSP_PAYLOAD"]),
            status="active",
        ),
        Package(
            kind=KIND_CSTP, tenant_id=tenant, product_space_id=ps,
            platform=platform, goal=goal, payload=dict(cfg["CSTP_PAYLOAD"]),
            status="active",
        ),
        Package(
            kind=KIND_CEP, tenant_id=tenant, product_space_id=ps,
            platform=platform, goal=goal, payload=dict(cfg["CEP_PAYLOAD"]),
            status="active",
        ),
    ]
    sens = [
        CpLawSensitiveDomain(
            domain_id=str(uuid.uuid4()), code=d["code"], name=d["name"],
            status="active",
        )
        for d in cfg["SENSITIVE_DOMAINS"]
    ]
    return {"slot": slot, "pcp": pcp, "content_goal": cg, "packages": packages, "sens": sens}


async def _ensure_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=cmd._REQUIRED_TABLES
        )


async def seed(session, rows: dict) -> None:
    session.add(rows["slot"])
    session.add(rows["pcp"])
    session.add(rows["content_goal"])
    for p in rows["packages"]:
        session.add(p)
    for s in rows["sens"]:
        session.add(s)
    await session.commit()


async def _run(dsn: str, cfg: dict) -> int:
    engine = create_async_engine(dsn)
    await _ensure_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session, build_rows(cfg))
        facts = await cmd.collect_facts(session)
    await engine.dispose()
    return cmd.evaluate(facts)


def _demo_cfg() -> dict:
    """明显是示例的假值，仅供 --demo 验证脚本机制（不写真实库语义）。"""
    c = dict(CONFIG)
    c.update(
        PLATFORM="wechat",
        TENANT_ID="demo-tenant",
        PRODUCT_SPACE_ID="demo-ps",
        GOAL_CODE="EDUCATION",
        SLOT_CODE="SLOT-DEMO-1",
        SLOT_NAME="示例短视频位",
        SLOT_TYPE="short_video",
        CSP_PAYLOAD={"goal": "EDUCATION", "stage": "awareness", "angle": "trust",
                     "intensity": "medium", "cta": "learn_more", "emotion": "reassuring"},
        CSTP_PAYLOAD={"struct": "problem_solution"},
        CEP_PAYLOAD={"tone": "warm", "perspective": "first_person",
                     "explicit": "soft", "soften": "lightly"},
        PCP_WEIGHTS={"reach": 1.0},
        SENSITIVE_DOMAINS=[],
    )
    return c


def main() -> int:
    parser = argparse.ArgumentParser(description="主数据回填 seed 模板")
    parser.add_argument("--dsn", default=None, help="真实库 DSN（缺省取 settings）")
    parser.add_argument("--demo", action="store_true",
                        help="用示例假值跑通机制（内存库），不碰真实库")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将写入的行，不落库")
    args = parser.parse_args()

    if args.demo:
        cfg = _demo_cfg()
    else:
        cfg = CONFIG
        bad = _is_unedited(cfg)
        if bad:
            print(f"❌ 以下字段仍是占位哨兵，请先改成真实值再运行：{bad}",
                  file=sys.stderr)
            return 2

    rows = build_rows(cfg)

    if args.dry_run:
        print("== dry-run：将写入以下行（不落库）==")
        print(f"  publish_slots : platform={rows['slot'].platform} "
              f"code={rows['slot'].code} slot_type={rows['slot'].slot_type}")
        print(f"  pcp_weight_tables : tenant={rows['pcp'].tenant_id} "
              f"ps={rows['pcp'].product_space_id} platform={rows['pcp'].platform}")
        print(f"  content_goals : code={rows['content_goal'].code}")
        for p in rows["packages"]:
            print(f"  packages[{p.kind}] : goal={p.goal} platform={p.platform}")
        print(f"  cp_law_sensitive_domains : {len(rows['sens'])} 行")
        return 0

    if args.demo:
        dsn = "sqlite+aiosqlite:///:memory:"
        # 内存库跨引擎不共享，这里在同一引擎内完成插入与自检。
        engine = create_async_engine(dsn)
        asyncio.run(_ensure_tables(engine))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async def _demo_seed_and_check():
            async with sf() as s:
                await seed(s, rows)
                facts = await cmd.collect_facts(s)
            return cmd.evaluate(facts)
        result = asyncio.run(_demo_seed_and_check())
        asyncio.run(engine.dispose())
    else:
        dsn = args.dsn or get_settings().database_dsn
        result = asyncio.run(_run(dsn, cfg))

    print(cmd._format_report(result))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
