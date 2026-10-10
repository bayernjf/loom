"""写口凭证接线自检（Q242，接替 Q203 在 test_fcw_api 里的那份同型检查）。

行为用例已经钉住「无令牌 401 / 角色不足 403」，但那条判红只会说"状态码不对"，
看不出是 `Depends` 被摘了。这条把接线本身钉住：逐个路由数**标记过的依赖**
（`require_internal_actor` 在闭包上留的 `loom_requires_internal_credential`），
少一个即判红，报错直接指向路由。

反向对照同样重要：只读口与**有意不加闸**的写口必须一个标记都没有，否则这条
检查会退化成"逢路由就说有"。
"""

from fastapi.routing import APIRoute

from app.main import app

OPS = ("operations",)
REVIEWER = ("product_reviewer",)
COMPLIANCE = ("internal_compliance",)

# 全部挂了 require_internal_actor 的写口 → 期望角色。
GATED: dict[tuple[str, str], tuple[str, ...]] = {
    # 段4 原子（Q242）
    ("/api/product-spaces/{product_space_id}/atom-batches/llm-expand", "POST"): OPS,
    ("/api/atom-candidates/{candidate_id}/approve", "POST"): REVIEWER,
    ("/api/atom-candidates/batch-approve", "POST"): REVIEWER,
    ("/api/atom-candidates/{candidate_id}/reject", "POST"): REVIEWER,
    ("/api/atom-clusters/{cluster_id}/resolve", "POST"): REVIEWER,
    ("/api/atom-candidates/{candidate_id}/risk-override", "POST"): REVIEWER,
    ("/api/atoms/{atom_id}/freeze", "POST"): OPS,
    ("/api/atoms/{atom_id}/unfreeze", "POST"): OPS,
    ("/api/atoms/{atom_id}/compliance-suspend", "POST"): COMPLIANCE,
    ("/api/atoms/{atom_id}/compliance-resume", "POST"): COMPLIANCE,
    ("/api/atoms/{atom_id}/deprecate", "POST"): OPS,
    ("/api/atoms/{atom_id}/archive", "POST"): OPS,
    ("/api/atoms/{atom_id}/reject", "POST"): REVIEWER,
    # 段10 三包（Q242）
    ("/api/product-spaces/{product_space_id}/packages", "POST"): OPS,
    ("/api/packages/{package_id}", "PUT"): OPS,
    ("/api/packages/{package_id}", "DELETE"): OPS,
    # 段7/8 平台底表（Q242）
    ("/api/admin/publish-slots", "POST"): OPS,
    ("/api/admin/publish-slots/{slot_id}", "PUT"): OPS,
    ("/api/admin/publish-slots/{slot_id}", "DELETE"): OPS,
    ("/api/admin/fit-weights", "PUT"): OPS,
    ("/api/admin/platform-rules", "POST"): OPS,
    ("/api/admin/platform-rules/{rule_id}", "DELETE"): OPS,
    ("/api/admin/slot-type-defaults", "PUT"): OPS,
    ("/api/product-spaces/{product_space_id}/pcp", "POST"): OPS,
    ("/api/pcp/{pcp_id}", "PUT"): OPS,
    # 段7 PLATFORM-ADAPTER 只读预览口（Q296 甲：只读但走已验真身份闸，Q242 同族）
    ("/api/admin/platform-adapter/preview", "POST"): OPS,
    # 段7 PLATFORM-ADAPTER 候选 + HumanGate（Q300 乙：advisory，approve 不触 final_id）
    ("/api/admin/platform-adapter/candidates", "POST"): OPS,
    ("/api/admin/platform-adapter/candidates/{candidate_id}/approve", "POST"): OPS,
    ("/api/admin/platform-adapter/candidates/{candidate_id}/reject", "POST"): OPS,
    # 字典管理 Q38 降级动作字典（Q306）：字典族新写口一律走 Q203/Q242 现行凭证标准，
    # 不再复制 content_goals／content_languages 的 body 自报角色旧口径。
    ("/api/admin/downgrade-actions", "PUT"): ("dictionary_admin",),
    ("/api/admin/downgrade-actions/{code}/archive", "POST"): ("dictionary_admin",),
    # 字典管理 Q43 17 池选项字典（Q308）：同一族，写口只认字典管理员。
    ("/api/admin/pool-options", "PUT"): ("dictionary_admin",),
    ("/api/admin/pool-options/{pool}/archive", "POST"): ("dictionary_admin",),
    # 段11 E1.1 发证（Q203）
    ("/api/fcw/assemble", "POST"): OPS,    ("/api/fcw/assembly-tasks", "POST"): OPS,
    # 段9 layerSpaces 通用底座（Q262/Q46）：增删改仅平台级管理员。
    ("/api/admin/layer-spaces/items", "POST"): ("platform_admin",),
    ("/api/admin/layer-spaces/items/{item_id}", "PUT"): ("platform_admin",),
    ("/api/admin/layer-spaces/items/{item_id}", "DELETE"): ("platform_admin",),
    # 段7/8 动态信号与 PCP 每周重算 HumanGate（Q259）：写口同样要已验真令牌。
    ("/api/admin/platform-dynamic-events", "POST"): OPS,
    ("/api/admin/platform-dynamic-events/{event_id}", "PUT"): OPS,
    ("/api/admin/platform-dynamic-events/{event_id}", "DELETE"): OPS,
    ("/api/admin/pcp-recalc/candidates", "POST"): OPS,
    ("/api/admin/pcp-recalc/candidates/{candidate_id}/approve", "POST"): OPS,
    ("/api/admin/pcp-recalc/candidates/{candidate_id}/reject", "POST"): OPS,
    # 段11 组装预检与冻结管理（Q249/Q250）：预检只读但走同一受闸口，吊销是写口。
    ("/api/fcw/assemble/preview", "POST"): OPS,
    ("/api/admin/fcw/{final_id}/revoke", "POST"): OPS,
    # 段6 PWS 冻结/吊销（Q329，Q242 乙案）：BO-07 whitelist_owner 不可签发 staff 令牌
    # （Q178 限五内部角色），两口改判 operations（require_internal_actor），与
    # FCW final_id revoke（Q250）同口径；whitelist_owner 保留为 Q28 原文角色随 V2 回评。
    ("/api/product-spaces/{product_space_id}/pws/freeze", "POST"): OPS,
    ("/api/pws/{pws_id}/revoke", "POST"): OPS,
    # Q325（02 C1.268）拍板：Q277 三条登记写口补角色闸，只认已验真 staff 令牌的 operations
    # （Q277 时点在 UNGATED 的理由"契约未规定调用角色、代码亦无闸"已随裁决失效）。
    ("/api/intakes/{intake_id}/ops-decision", "POST"): OPS,
    ("/api/product-spaces/{product_space_id}/pwc/funnel", "POST"): OPS,
    ("/api/product-spaces/{product_space_id}/pwc/consume", "POST"): OPS,
    # 段12 video-studio 分段编目（Q336，①甲）：写口只认已验真 staff 令牌的 operations。
    ("/api/admin/content/{content_id}/video-segments", "POST"): OPS,
    ("/api/admin/video-segments/{segment_id}", "PUT"): OPS,
}

# 必须一个标记都没有：只读口，以及有意不加闸的写口。
UNGATED: tuple[tuple[str, str], ...] = (
    ("/api/fcw/assembly-tasks/{task_id}", "GET"),
    ("/api/product-spaces/{product_space_id}/packages", "GET"),
    ("/api/admin/publish-slots", "GET"),
    ("/api/admin/fit-weights", "GET"),
    # Q75：前置状态即闸，revive 有意不设角色闸。
    ("/api/atom-candidates/{candidate_id}/revive", "POST"),
    # 段4 的这两口 docs/05 未给角色，Q242 刻意不动。
    ("/api/product-spaces/{product_space_id}/atom-batches", "POST"),
    ("/api/atom-candidates/{candidate_id}/evidence", "POST"),
    # Q277 登记在 docs/05 的三口已由 Q325 裁决补角色（operations），整条移进 GATED。
    # 钉在 UNGATED＝"当前刻意不加闸"是判据；负责人裁决补角色后，须整条移进 GATED 并写期望角色。
    # Q262 读口：query actor 闸（require_layer_spaces_view），非凭证依赖。
    ("/api/admin/layer-spaces", "GET"),
    ("/api/admin/layer-spaces/items/{item_id}/impact", "GET"),
)


def _find_route(path: str, method: str) -> APIRoute:
    # 本仓 FastAPI 用 `_IncludedRouter` 懒包含，故要顺着 original_router 找。
    stack = list(app.routes)
    while stack:
        node = stack.pop()
        sub = getattr(node, "original_router", None)
        if sub is not None:
            stack.extend(sub.routes)
        elif (
            isinstance(node, APIRoute) and node.path == path and method in node.methods
        ):
            return node
    raise AssertionError(f"找不到 {method} {path}")


def _marked_calls(route: APIRoute) -> list:
    return [
        d.call
        for d in route.dependant.dependencies
        if getattr(d.call, "loom_requires_internal_credential", None) is not None
    ]


def test_every_gated_write_route_carries_the_credential_dependency():
    for (path, method), roles in GATED.items():
        route = _find_route(path, method)
        marked = _marked_calls(route)
        assert len(marked) == 1, f"{method} {path} 上挂着 {len(marked)} 个凭证依赖"
        assert tuple(marked[0].loom_requires_internal_credential) == roles, (
            f"{method} {path} 要求的角色不是 {roles}"
        )


def test_read_and_deliberately_ungated_routes_have_no_credential_dependency():
    for path, method in UNGATED:
        assert _marked_calls(_find_route(path, method)) == [], f"{method} {path}"


def _all_routes() -> list[APIRoute]:
    """`app.routes` 把 include 包成 `_IncludedRouter`（取不到 path），必须顺着 original_router 走。"""
    out: list[APIRoute] = []
    stack = list(app.routes)
    while stack:
        node = stack.pop()
        sub = getattr(node, "original_router", None)
        if sub is not None:
            stack.extend(sub.routes)
        elif isinstance(node, APIRoute):
            out.append(node)
    return out


def test_the_gated_list_is_complete_no_route_can_carry_a_credential_unmarked():
    """反向枚举：手工清单必然落后（Q276 就是这么漏掉 8 口的），所以改由机器求交集。

    断言两个方向：① 代码里任何带凭证依赖的路由都必须在 `GATED` 内（新增口忘记登记即判红）；
    ② `GATED` 里每个角色集合与路由实际要求一致（已由上一条用例覆盖角色，这里只保证集合相等）。
    """
    marked = {
        (m.upper(), route.path)
        for route in _all_routes()
        for m in (route.methods or set())
        if _marked_calls(route)
    }
    contract = {(method, path) for (path, method) in GATED}
    assert marked == contract, (
        f"只在代码里（清单漏登）：{sorted(marked - contract)}；"
        f"只在清单里（口已删除或改闸）：{sorted(contract - marked)}"
    )
    assert not ({(m, p) for (p, m) in UNGATED} & contract), "同一口既在 GATED 又在 UNGATED"
