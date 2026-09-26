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

> **只想打通第一张 `final_id`？看 §0.2「最小可发证清单」**——§0 这张表是完整模板口径，其中若干项（四维分/risk/fit 权重/slot_type_defaults）不参与发证判定，首批不必向业务方索取。

> **怎么确认填够了（Q210，2026-09-26，02 C1.154）**：业务方在真实部署库回填四表后，跑 `python backend/scripts/check_master_data.py`（可加 `--json`）即可看还差哪类 active 数据。脚本**只读**五张表、与发证解析器同口径（只看 `status=="active"`、不看 `gate`），缺任一必填项退出码 1、齐备 0；并单独提示 `cp_law_sensitive_domains` 是否为零行（Guard⑥ 默认放行、可配置非豁免）。它是给人手动跑的工具，**不进 CI**（CI 默认 DSN 是本地库、无真实主数据，跑它只会永远红）。

> **怎么填（同生态 Q210 补，02 C1.154）**：`backend/scripts/seed_master_data_template.py` 是与自检器**同 ORM 口径**的回填骨架——顶部 `CONFIG` 全是 `<REPLACE_ME_...>` 占位哨兵，改完真实值再 `--dsn` 跑；**未改完会被脚本中止**（防止占位符写进库，不臆造业务事实）。`--demo` 用示例假值跑通机制、`--dry-run` 只打印将写入的行、填完后跑上面的自检器核对。本模板只覆盖自检器口径的最小集；完整主数据（product_spaces / PWS 冻结 / 合规报告等）才能真跑通段1→6→10 产出 `final_id`，见本模板头部注释与全文 §0。

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


## 0.2 最小可发证清单（2026-09-26，据代码反推，不是照本文件 §1-§5 抄）

> **为什么要单列这一节**：§1-§5 是"完整录入模板"，但**过七项 Guard 真正需要的东西比它少得多**。
> 首批的目的只是"在真部署里出一张真 `final_id`"（docs/20 §9.2 认定的唯一剩余硬阻塞），
> 所以对外要东西时请按这张表要，别把整份模板甩出去——那会把一件小任务说成一个大工程。
> 下面每条都给了代码位置，判定依据是 `app/final/final_whitelist/service.py` 与 `fcw_rules.py` 的实际实现。

### A. 工程已经备好、不需要业务方给的

| 东西 | 状态 | 依据 |
|---|---|---|
| PCP **模板** 4 套（`short_video`/`community`/`photo_text`/`ecommerce`） | 已随种子落地 ⇒ **PCP 实例只是"选一个模板码"**，不是手填 17 项权重 | `app/platform/platform_adaptation/seeds.py`；Q39 |
| `content_goals` 目的字典 | 已随迁移 0005 播种 ⇒ `goal` 不用业务方发明（现有 5 码见 §3） | `alembic/versions/0005_m5_stage5.py` |
| 七项 Guard、发证口、内部角色与配置中心 | 全部已落地；且自 Q203 起 `final_id` 唯一出口有运行期守卫（作用域外写入判红） | `fcw_rules.py`；`exit_guard.py`；02 C1.147 |
| 敏感领域字典 `cp_law_sensitive_domains` | **零行种子**（迁移 0007 只建表）⇒ 首批若不主动启用敏感类目治理，Guard⑥ 走"无法审单即放行"分支 | `compliance_center/service.py:164-196`（命中才建单）、`:603-624`（`law_review_required = 有单`）|

> ⚠️ 最后一行是**可配置项，不是永久豁免**：合规团队一旦填了敏感领域字典，产品命中就转 48h 法审待办（Q49），Guard⑥ 立刻变成真门槛。首批选产品时请有意**避开**打算启用为敏感类目的行业，否则"打通第一张 `final_id`"会挂在等法务上。

### B. 真需要人给的四样（按依赖顺序）

| # | 要做的事 | 谁来 | 必填到什么程度 | 卡不卡发证 |
|---|---|---|---|---|
| 1 | 选一个真产品并录入（段1 intake → ProductSpace） | 业务/运营 | 一个真实产品即可，先只要 1 个 | **卡**（后面所有材料都挂在它身上） |
| 2 | 建 **1 个发布位**：`platform` / `code` / `name` / `slot_type` | 运营（值由业务定） | `slot_type` 的**类型名要业务方给**——原 13 类目录随基准 HTML 永久丢失（Q115），工程不得编 | **卡**，但只查两件事：`status=active` 且 `platform` 与请求一致（`service.py:132-141`）——**`gate` 档不参与发证判定** |
| 3 | 给该 产品×平台 建 **PCP** | 运营 | `POST /api/product-spaces/{id}/pcp` 只要 `{platform, template_code}`（选模板，不填权重） | **卡**：无 active PCP → 409 材料缺失（`service.py:164-178`） |
| 4 | 建 **三包** CSP / CSTP / CEP 各一条 | **业务/内容**（这才是真需要人判断的部分） | payload 定键见 §3：CSP 6 键（目的/阶段/角度/强度/CTA/情绪）、CSTP 1 键（结构）、CEP 4 键（语气/人称/显性/软化） | **卡**（Guard③，`fcw_rules.py` g3） |

### C. 光填表出不来 `final_id`——Guard①②⑦ 来自"跑一遍链"

发证还要求 PWS `frozen` 且为 active 版（g1/g7）、有合规清洗报告且 `cleaning_passed && !block_required`（g2）。
这三样**不是数据录入**，而是有人把 段1→5→6→10 走一遍并在 Gate 上裁决（01 铁律：AI 只产候选、人工 Gate 裁决）。

所以本清单实际要向您要**两个人**：**录入的人**（B 表第 1/4 行）与**跑链裁决的人**（段5 PWC 批准、段6 冻结、段10 清洗）。
如果没人跑链，第一张"真 `final_id`"只会以工程自造测试数据的形式出现——那种数据**不作数**，也违反"禁工程臆造"红线。

### D. 可以留空、完全不影响发证的（别为这些等工期）

发布位四维分 `traffic`/`safe`/`conv`/`load`、`risk`、`source_url`、`chars_max`/`dur_min`/`dur_max`、`gate` 档；
fit 权重矩阵（缺了只是 `score_incomplete`——Q54 定死评分**仅用于排序、永不做门槛**）；`slot_type_defaults`（§0 表第 4 行已标"消费侧 V2 才接入"）。

**这一条的实际用途**：四维分按 Q35 属"人工评估分"，是整份模板里最贵的一项。它不卡发证 ⇒
**首批不应向业务方索取打分**。把打分列进首批清单，是最可能造成"主数据一直回不来"的假阻塞。

### E. 一次验收实际怎么跑（命令级，含 Q203 的令牌前置）

1. **引导签发令牌**（Q203 之后发证口无条件要）：门控关下自报 `platform_admin` 调
   `POST /api/admin/staff-keys`，明文只回一次（口径见 §0.1 与 docs/21 §2）。
2. 按 docs/21 SOP 走 段1→6→10（录入 → 字段池 → 原子 → PWC 人工批准 → PWS 冻结 → CCR 清洗）。
3. `POST /api/fcw/assemble` 带 `Authorization: Bearer loom_staff_…`，body
   `{product_space_id, platform, slot_id, goal, actor}` → **200 即出 `final_id`**；
   若 **409**，响应回带七项 Guard 逐项明细，据此定位缺哪一路材料（不会静默失败）。
4. **模型选择建议拆成两次**：第一次打通用 synthetic（不花钱、可反复跑），"真 agnes 全链"另立一次点工——
   ATOM-AFFINITY 至今仍是 synthetic（Q148），把"验真模型"与"验能发证"绑一起做，只会两件事都变慢。

**判"首批完成"的唯一标准**：在 staging/真部署的库里出现一张 `final_id`，其六路材料与 `fcw.issued` 审计
指向**真实业务数据**（不是测试夹具、不是工程臆造的行）。

## 0.3 业务方回填操作指引（一步一步）

> 本节能让业务/运营在**真实部署库**里把"够发证的四样"填齐并自检齐备，不要求懂 API 细节——字段含义见 §1–§5，命令级发证见 §0.2 §E 与 docs/21。
> 本指引只覆盖"填数据＋自检"；**真出 `final_id` 还需要另一个人跑链裁决**（见 §0.2 §C、§0.2 §E 第 2/3 步），本指引不替代那一步。
> **纯业务方版（去技术细节）**：`docs/19_业务方回填指引.md` —— 可直接转发给业务/运营。

### 两个人
- **录入人（您）**：提供并写入"四样"（§0.2 §B）。
- **跑链裁决人**：按 docs/21 SOP 把 段1→6→10 走一遍并在 Gate 裁决，产出 PWS 冻结与合规清洗报告（Guard①②⑦，§0.2 §C）。没人跑链，第一张 `final_id` 出不来，且工程自造数据不作数（违反禁臆造红线）。

### 前置条件
1. 一个正在运行的 staging / 真部署后端，连着**真实的** PostgreSQL（`check_master_data.py` 与 seed 脚本都连真实库，不连本地测试库）。
2. 该库连接串 `LOOM_DATABASE_DSN`（或 seed 脚本的 `--dsn` 参数）。
3. 一枚 `operations` 的 staff 令牌——**仅发证那一步要**（Q203，§0.1、§0.2 §E.1）；录入写口在门控关时按自报 `actor` 即可。
4. 一个您自己定义的**平台码**（英文大写短码，全库一致，如 `EXAMPLE`）；原 13 类目录已丢失，类型码由您定（§1、§0.2 §B.2）。

### 步骤

**第 0 步 · 定平台码与首个产品**
- 先定一个平台码（如 `EXAMPLE`），后面所有 `platform` 字段都用它，保持一致。
- 选一个真实产品作为首个 `final_id` 的载体（§0.2 §B.1）。

**第 1 步 · 建产品空间（段1 intake → ProductSpace）**
- 按 docs/21 段1 SOP 录入该产品，得到 `product_space_id`；后面 PCP / 三包都挂它身上。

**第 2 步 · 用 seed 模板把"四样"一次性填入**
- 打开 `backend/scripts/seed_master_data_template.py`，顶部 `CONFIG` 全是 `<REPLACE_ME_...>` 占位哨兵。**把每个占位符换成真实业务值**（字段含义见 §1 发布位 / §2 PCP / §3 三包）：
  - 发布位：至少 `platform` / `code` / `name` / `slot_type`（§1）；四维分 / `risk` / `source_url` 等**可不填**（§0.2 §D）。
  - PCP：填 `platform` + `template_code`（四选一，§2），`weights` 传 `null`；挂在**第 1 步**的 `product_space_id` 上。
  - 三包：CSP 6 键 / CSTP 1 键 / CEP 4 键（§3），各一条 `active`；同样挂在 `product_space_id` 上。
- 先跑 `python backend/scripts/seed_master_data_template.py --dry-run`：只打印将写入的行、**不落库**，用来核对。
- 想先看机制是否通，可跑 `--demo`（用示例假值跑通插入＋自检），确认无误后再用真实值：
  `python backend/scripts/seed_master_data_template.py --dsn "$LOOM_DATABASE_DSN"`。
- ⚠️ **占位符没改完脚本会自己中止**，防止 `<REPLACE_ME>` 写进库（不臆造业务事实）。

**第 3 步 · 自检齐备**
- 回填后跑：`python backend/scripts/check_master_data.py`（可加 `--json`）。
  - 退出码 **0** = 四样 active 数据齐备，可以进入跑链。
  - 退出码 **1** = 还差哪类，命令行会直接告诉您（如"缺 PCP""三包不齐"）；补上对应数据重跑即可。
  - 脚本**单独提示** `cp_law_sensitive_domains` 是否零行（Guard⑥ 默认放行，§0.2 §A 末行）——首批产品请**有意避开**打算启用为敏感类目的行业，否则会卡在等法务。

**第 4 步 · 交跑链裁决人（关键，别跳过）**
- 把 `product_space_id` / `platform` / `slot_id` / `goal` 交给跑链人，按 §0.2 §E.2–3 跑 段1→6→10 并在 Gate 裁决，得到 PWS 冻结 + 合规清洗报告（Guard①②⑦）。

**第 5 步 · 发证（需要 staff 令牌）**
- 跑链人按 §0.2 §E.1 先签一枚 `operations` 令牌；再 `POST /api/fcw/assemble` 带 `Authorization: Bearer loom_staff_…`，body `{product_space_id, platform, slot_id, goal, actor}`。
  - **200** = 出 `final_id`，首批完成。
  - **409** = 响应回带七项 Guard 逐项明细，据此补材料重跑（不会静默失败）。

### 完成标准
库里出现一张 `final_id`，其六路材料与 `fcw.issued` 审计指向**真实业务数据**（非测试夹具、非工程臆造），即判首批完成（§0.2 §E 末段）。

### 别为这些等工期（§0.2 §D）
四维分 `traffic/safe/conv/load`、`risk`、`source_url`、时长类、`gate` 档、fit 权重矩阵、`slot_type_defaults`——**全部不卡发证**，首批不必向业务方索取打分。

### 审计溯源提醒（§0.1）
所有写口 `actor.id` 请写**真实可辨识的人**（如 `ops:张三`），不要多人共用一个账号名——审计对账靠它。

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
