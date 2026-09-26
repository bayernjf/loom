# Private Beta 首批主数据录入模板

> **用途**：受控 private beta 验收（docs/08 §2.2 Checklist #2、#6）前，由业务方/运营按本模板提供并录入首批平台主数据。字段与后端现行 Pydantic 契约逐列对齐（`platform_adaptation/schemas.py`、`layer_strategy/schemas.py`），不含任何虚构平台数据——`【业务方填】`处必须由业务方给数，工程侧不代填。
> **背景**：原 14 平台 100+ 发布位目录随基准 HTML 永久丢失（Q115），故本期主数据由业务方重建。最小目标＝够产出 **1 个真实 final_id**。
> **裁决依据**：阈值口径已经负责人确认（Q149）；G2 提交闸以现有 12 字段为 beta 基线。

## 0. 最小集合（1 个 final_id 需要哪些）

| # | 数据 | 数量 | 端点 | 是否必须 |
|---|---|---|---|---|
| 1 | publish_slots 发布位 | ≥1（建议 2–3） | `POST /api/admin/publish-slots` | 必须 |
| 2 | PCP 平台配置实例 | 1（绑定 product_space×platform） | `POST /api/product-spaces/{id}/pcp` | 必须 |
| 3 | 三包实例 CSP / CSTP / CEP | 各 1 | `POST /api/product-spaces/{id}/packages` | 必须 |
| 4 | slot_type_defaults | 按需 | `PUT /api/admin/slot-type-defaults` | 可选（消费侧 V2 才接入） |
| 5 | fit 权重矩阵 | 按需 | `PUT /api/admin/fit-weights` | beta 目的为 ENGAGEMENT/CONVERSION 时已有种子，可选 |

> 段10 合规清洗报告（Guard② 的 cleaning_passed）由跑链过程产生，**不在本模板范围**。
> 三包/PCP 创建后 `gate`/`risk` 默认 `approved`、`status` 默认 `active`（Q42 人工直编口径），无需另走审批端点。

## 0.1 actor 口径

所有写口 body 内带（**Q196 起：该字段是兼容输入，不是可信来源**）：

```json
{"actor": {"id": "ops:谁干的", "roles": ["operations"]}}
```

> **读法（Q196／02 C1.140，2026-09-25）**：若部署侧已开 `LOOM_STAFF_AUTH_ENABLED`，审计里记的操作人是**令牌持有人**，上面这个 `id` 只在被推翻时作为 `detail.declared_actor` 留证；门控关（beta 默认）时按自报记录，来源标 `detail._actor_via=declared`。**因此录入模板里的 `id` 请写真实可辨识的人（如 `ops:张三`），不要共用一个账号名**——审计溯源靠它，共用会毁掉对账能力。

`id` 为操作人标识（溯源用）；写口要求 `operations` 角色。

> **Q204 订正（2026-09-26，02 C1.148）——两类写口的口径不同，别混**：
> ① **本模板的录入写口**（publish-slots / PCP / 三包 / fit 权重 / slot-type-defaults）沿用 Q178：
>    `LOOM_STAFF_AUTH_ENABLED` 关闭时接受上面的自报 `actor`，开启后必须有 staff 令牌且角色够。
> ② **发证口**（`POST /api/fcw/assemble`、`POST /api/fcw/assembly-tasks`）自 **Q203** 起**无条件**要求已验真的
>    `loom_staff_` Bearer：缺/坏/吊销 → 401，令牌角色不含 `operations` → 403，上面这个 `actor` 字段被令牌身份覆盖。
>    ⇒ 跑 §5 验收第③步（全链出真 `final_id`）**之前**必须先按 Q178 引导流程签一枚 operations 令牌，
>    否则门控关着也会撞 401。引导：门控关下自报 `platform_admin` 调 `POST /api/admin/staff-keys`，明文只回一次。


## 1. publish_slots 发布位

`POST /api/admin/publish-slots`，body 形如 `{"item": {...}, "actor": {...}}`。

| 字段 | 含义 | 必填 | 约束/默认 |
|---|---|---|---|
| `platform` | 平台码（英文大写/短码，全库一致使用） | ✅ | String |
| `code` | 发布位编码，全库唯一 | ✅ | 唯一；重复 409 |
| `name` | 发布位中文名 | ✅ | |
| `slot_type` | 发布位类型 | ✅ | 原文 13 类目录同基准 HTML 已丢失，由业务方定义类型码 |
| `chars_max` | 最大字符数 | ⬜ | ≥0 整数 |
| `dur_min` | 最短时长（秒） | ⬜ | ≥0 整数 |
| `dur_max` | 最长时长（秒） | ⬜ | ≥0 整数 |
| `traffic` | 四维分·流量 | ⬜ | 0–100，默认 0，**人工评估分（Q35）** |
| `safe` | 四维分·安全 | ⬜ | 0–100，默认 0 |
| `conv` | 四维分·转化 | ⬜ | 0–100，默认 0 |
| `load` | 四维分·承载 | ⬜ | 0–100，默认 0 |
| `risk` | 风险档 | ⬜ | 默认可空 |
| `gate` | 闸门档 | ⬜ | 默认 `approved` |
| `source_url` | 发布位规则来源链接 | ⬜ | |

**业务方填写表（每发布位一行；下行为格式示例，非真实数据）**：

| platform | code | name | slot_type | chars_max | dur_min | dur_max | traffic | safe | conv | load | source_url |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `【业务方填】` | `【业务方填】` | `【业务方填】` | `【业务方填】` | | | | | | | | |
| `EXAMPLE` | `example_feed_main` | `示例·主信息流` | `feed` | `1000` | | | `60` | `70` | `40` | `30` | `https://example.com/rules` |

## 2. PCP 平台配置实例

`POST /api/product-spaces/{product_space_id}/pcp`（需先有产品空间）。

```json
{
  "platform": "【与第 1 表一致的平台码】",
  "template_code": "【四选一】",
  "weights": null,
  "actor": {"id": "ops:xxx", "roles": ["operations"]}
}
```

`template_code` 现有 4 套种子模板（Q39，17 池权重 Σ=1）：

| template_code | 名称 |
|---|---|
| `short_video` | 短视频型 |
| `community` | 社区讨论型 |
| `photo_text` | 图文种草型 |
| `ecommerce` | 电商型 |

`weights` 传 `null` 用模板初值；要覆盖时传 17 池权重且 Σ=1，否则 422。

## 3. 三包实例 CSP / CSTP / CEP

`POST /api/product-spaces/{product_space_id}/packages`，每（产品×平台×目的×包型）一条 active。`goal` 现有 5 码：`ENGAGEMENT / CONVERSION / EDUCATION / TRUST / RETENTION`。

`payload` 键集按 kind 严格校验（缺键/多键均 422）：

| kind | payload 必含键 |
|---|---|
| `csp`（策略包） | `goal, stage, angle, intensity, cta, emotion` |
| `cstp`（结构包） | `struct` |
| `cep`（表达包） | `tone, perspective, explicit, soften` |

`conf` 可选，0–1。格式示例（值为示例非口径）：

```json
{
  "item": {
    "kind": "csp",
    "platform": "EXAMPLE",
    "goal": "ENGAGEMENT",
    "payload": {
      "goal": "awareness",
      "stage": "launch",
      "angle": "user_story",
      "intensity": "medium",
      "cta": "learn_more",
      "emotion": "trust"
    },
    "conf": 0.8
  },
  "actor": {"id": "ops:xxx", "roles": ["operations"]}
}
```

```json
{"item": {"kind": "cstp", "platform": "EXAMPLE", "goal": "ENGAGEMENT",
  "payload": {"struct": "hook → pain → solution → proof → cta"}, "conf": 0.8},
 "actor": {"id": "ops:xxx", "roles": ["operations"]}}
```

```json
{"item": {"kind": "cep", "platform": "EXAMPLE", "goal": "ENGAGEMENT",
  "payload": {"tone": "professional", "perspective": "second_person",
    "explicit": false, "soften": "hedged"}, "conf": 0.8},
 "actor": {"id": "ops:xxx", "roles": ["operations"]}}
```

## 4. 可选：fit 权重补配

beta 目的若用 EDUCATION/TRUST/RETENTION（现有无权重，fit_score 会返回 null + incomplete），业务方给四维权重（`traffic/safe/conv/load`，Σ=1，不归一化）：

`PUT /api/admin/fit-weights`，body：

```json
{"goal": "TRUST", "weights": {"traffic": 0.1, "safe": 0.5, "conv": 0.1, "load": 0.3},
 "actor": {"id": "ops:xxx", "roles": ["operations"]}}
```

## 5. 录完之后

交回工程侧：① 起 staging 栈；② 灌入本模板数据；③ 跑段1→6→10→11 全链，`POST /api/fcw/assemble` 过七 Guard 产出真实 final_id（**Q203：该口只认已验真 `loom_staff_` Bearer 令牌**，无令牌 401；引导签发见 Q178／docs/21 §2）；④ 重跑 pytest/ruff/eval 101、前端 next build，完成 Checklist #6 验收。
