"""内部运营个人访问令牌（PAT）身份层（Q178，甲案第一切片）。

与 Q88 ``agent_api_keys``（机器/Agent 凭证）刻意分域：本表绑定到**具体内部人员**
（staff_id/staff_name/roles），用于管理面/运营端点的真实认证。库内只存 SHA-256
哈希，明文令牌仅签发时返回一次。门控 ``LOOM_STAFF_AUTH_ENABLED`` 默认关闭：关闭时
管理面维持 V1 actor 自报口径，开启后内部角色端点以令牌验真身份为准（见 rbac）。

客户侧真实认证与 actor↔tenant 绑定后置，不在本切片范围。
"""
