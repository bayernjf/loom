"""客户访问令牌（Client Access Token）身份层（P0，2026-10-30）。

补齐 Q178 明确后置的「客户侧真实认证与 actor↔tenant 绑定」缺口：本表每行是一枚
绑定到**具体租户**的客户令牌（``loom_client_`` 前缀），用于客户内容决策端点
（approve/reject/revise/正文编辑）的真实认证。与内部人员 PAT（``loom_staff_``）、
机器 Agent Key（``loom_``）三类凭证分表、分前缀，不可互换。

库内只存 SHA-256 哈希（库泄露不暴露可用令牌），明文令牌仅签发时返回一次；
验签同时强制令牌租户与请求 ``tenant_id`` 一致，认证身份携带 ``whitelist_owner``
角色，请求体自报的 ``actor`` 不再作为身份。
"""
