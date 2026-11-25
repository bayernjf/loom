# Loom 真实模型链路验收 — 2026-11-25

## 结论

- 真实模型链路已打通，当前 `ARTICLE-GEN` 解析到 Loom 项目的 `content` 别名：
  `doubao-seed-evolving`，assignment `asn_ea33a7e7bfe8574af9107c434cdff1bc`。
- 验收对象：tenant `t-e2e-c174c8ee7f9f` 的 review 态内容
  `fefb41e6-df6e-11f1-a89a-16173182c4db`。
- 请求路径：客户 `POST /api/content/{id}/revise` → 运营
  `POST /api/content/{id}/regenerate`，最终 `status=review`、`regenerate_count=1`。
- 三条 Skill run 全部 `succeeded`，均使用同一 assignment：
  `ARTICLE-GEN`（1401 input / 1492 output tokens）、
  `ARTICLE-SEMANTIC-CHECK`（688 / 213）、
  `ARTICLE-QC`（488 / 717）。
- 成稿 191 字符，`quality_score=0.90`；`review_hits` 的 bans/downgrades 均为空，
  construction / country_rules / semantic 三组均通过。

完整响应见 `result.json`。

## 根因

1. `backend/.env.shell` 仍使用旧 Loom token，model-hub 投影缓存停留在 3 个 Agnes
   3.0 模型，容器因此没有解析到 `loom` 项目的模型分配。
2. `infra/.env` 中 `MODEL_HUB_URL` / `MODEL_HUB_TOKEN` 为空，backend 容器启动时
   `sync_hub_projection()` 静默失败并按旧路由回退 synthetic。
3. 改用当前 Loom 项目 token、补齐 `MODEL_HUB_URL=http://model-hub:8791` 并重建
   backend 后，projection revision 82 返回 1 条 `content -> doubao-seed-evolving`；
   launchd C1 sidecar 同步重启并加载新 token。

## `doubao-seed-1-6` 状态

- Ark preset 中存在 `doubao-seed-1-6`，已导入为
  `mdl_dddd6c4ae5de157b646aa4141b3d122b`。
- Shallow test 返回 `InvalidEndpointOrModel.NotFound`：
  `The model or endpoint doubao-seed-1-6-250615 does not exist or you do not have access to it`。
- 这是 Ark 账号对该 model/endpoint 的访问权限问题，不是 Loom token 或投影缓存问题。
  模型已保持 disabled，需在 Ark 控制台完成 SSO / 开通后再登记启用。
- 当前 Loom 真实模型链路不受影响，继续使用 `doubao-seed-evolving`。

## 边界

- 本证据只验证“真实模型生成 + 复检 + 质量分”的链路，不等同于成稿质量验收。
- 最新 growth-os dogfood 内容 `cd099720-e6a1-11f1-9230-9ed4b69628fb` 仍是
  synthetic 占位，未在本轮被改写；本轮验证对象是 `fefb...` 这条 review 内容。
- `backend/.env.shell` 与 `infra/.env` 是 gitignored 本地配置；仓库只提交本目录证据
  与 handoff/docs 状态，不提交 token。

## 复现要点

1. model-hub 的 `loom` 项目保持 `content -> doubao-seed-evolving` assignment。
2. 本地 env 使用该项目的 active token，backend 容器使用
   `MODEL_HUB_URL=http://model-hub:8791`。
3. 重建 backend 后确认 `hub.sync_hub_projection()` 返回 `loom` 的 revision 与
   `content` 别名。
4. 以客户令牌 revise、运营 staff 令牌 regenerate；两条请求都需通过正式鉴权。
