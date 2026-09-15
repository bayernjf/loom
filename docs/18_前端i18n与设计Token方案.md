# 18. 前端 i18n 与设计 Token 方案

> **状态**：✅ **2026-09-16 经负责人拍板定稿（Q96，02 C1.40）**——四项接缝全按推荐甲案：next-intl / CSS Modules + tokens.css / V1 仅 zh-CN 且字典多语言延 V3 / 色值借 Ant Design 5 默认调色板作工程初值（只借值、不引组件库）。本文 2026-09-13 起草稿的“建议”表述据此生效为实现强制依据；具体可落码值见 §2.3、§3.6。旧稿“拍板后追加 Q75”编号作废——Q75 已用于 RBAC 裁决，本项编号 Q96。
> **定位**：只覆盖**界面层**（管理后台 + 客户前端 UI）的国际化与视觉基础。内容侧多语言（Q58）是业务规则，不在此重定义，仅做边界对齐。
> **关联**：14（技术栈 Next.js 15 + React 19 + TS）、09（客户前端 8 菜单/13 管理菜单展示口径）、08（M12 客户前端基础版；V3 国际化/白牌定制）、02 Q58/Q73、15（前端目录落位）。
> **事实纪律**：业务规则一律引用 Q 编号/文档；本文新增的只是工程选型建议与数值约定（色板/字号/间距等无原文来源，属设计工程建议，非业务事实）。

---

## 1. 两个"多语言"必须分开

| 层 | 是什么 | 口径 | 归属 |
|---|---|---|---|
| **内容多语言** | 生成的文章/视频成品按语言独立成件 | 语言 = 发布位目标市场 ∩ 产品录入语言；每语言版独立复检/入成品库/客户审；支持语言清单配置化 CRUD | Q58（已定稿）；02 §C2 语言列表 CRUD；段 12（V2/P4） |
| **界面 i18n（本文档）** | 后台/前端 UI 自身的文案、格式、RTL 等 | V1 仅中文；架构上不硬编码文案，V3 随"国际化（多语言界面）"启用外语 | Q73 路线图（界面国际化列 V3）；本文档 |

> 另需区分第三类——**运营数据的多语言展示**（G1 类目名、G2 字段名、contentGoals 字典、动作字典等）。这些是后台可配业务数据，不是 UI 文案。V1 一律存中文规范名（canonical，zh-CN），**不预留也不立即实现 name_i18n 结构**；V3 启用界面多语言时再按统一模式扩展（建议 `{ "zh-CN": "…", "en-US": "…" }` JSONB，中文名始终为兜底 canonical），届时需在 04/10 对应实体补字段并走数据迁移。禁止 V1 在代码里为字典表预埋翻译列（无消费方）。

---

## 2. 界面 i18n 方案（Q96 定稿）

> **接缝①拍板（Q96）**：库 = **next-intl**（自研轻量字典否掉，V3 外语期会重写）；接缝③拍板：V1 仅 zh-CN、首个外语 V3 再启用（工程默认 en-US，语种顺序届时按客户输入定）、运营数据字典多语言延 V3 且 V1 不预留 name_i18n 字段。

### 2.1 技术选型建议：next-intl + App Router 语言前缀路由

- 栈已定为 Next.js 15 App Router + React 19（14）。建议 **next-intl**：App Router/RSC 原生支持、ICU MessageFormat（复数/日期/插值标准语法）、消息可按组件静态切片；**不建议** next-i18n/react-i18next（Pages Router 时代方案，与 RSC/15 契合度差）。
- 路由：`/[locale]/...` 语言前缀；V1 仅注册 `zh-CN`，路由层默认把无前缀请求 308 到 `/zh-CN`。V3 加语言时只增注册不改组件。
- 消息文件：`frontend/messages/{locale}.json`（V1 只建 `zh-CN.json`），扁平点分 key、按功能域命名空间，例如：
  - `intake.status.ai_recognizing`、`fieldpool.gate.approve`、`common.action.submit`
  - key 用**语义**不用文案（✅ `gate.rejectedReason` / ❌ `gate.请填写驳回原因`）。
- 语言解析优先级：URL 前缀 > `Accept-Language`（仅在无匹配时兜底）> 默认 zh-CN。V3 再加用户偏好（账号设置）覆盖；不引入自定义 cookie 黑盒。
- 枚举不翻译：后端继续返回**枚举码**（如 `pending_gate`/`ops_assist`/`escalated`），前端在消息表映射展示文案与状态色 token。后端任何 API 不返回中文句子（错误返回 `code` + 参数，文案由前端拼，见 11 OpenAPI 通用规范后续对账）。
- 不翻译的对象：fid/category_id/审计 action 码/PT 协议名/日志——这些是标识符。
- 格式：日期/数字/货币一律 `Intl.*`（ICU），存储与传输全 UTC（17），V1 展示时区 `Asia/Shanghai`（配置项，非硬编码默认即可，V3 按用户时区）。
- 文案规则：禁止字符串拼接做句式（中文语序与英文不同）；带数量的用 ICU plural（`{count, plural, other {…}}`）；CJK 与拉丁混排不做特殊处理（依赖字体栈）。

### 2.2 V1 落地范围（随 M12 客户前端 + 已有管理端页面）

1. 装 next-intl，建 `[locale]` 段与 `zh-CN.json`，**不开启任何外语**；
2. 用户可见文案 100% 走消息表（评审检查项；V1 不引入额外 lint 插件，V3 启用外语前补 `eslint-plugin` 级硬编码中文扫描）；
3. 后端枚举码 → 前端消息 key 的映射表集中在 `frontend/messages/zh-CN.json` 对应命名空间，与 docs/13 状态词一一对应；
4. M12 验收追加一条：页面无硬编码业务文案、无前端自创状态词（状态口径以 13/01 为准）。


### 2.3 落码结构（Q96 定稿，照此落码）

```
frontend/
  package.json                 # 新增依赖：next-intl（与 Next.js 15 兼容版本），无其他 i18n 依赖
  middleware.ts                # next-intl 标准 matcher：无语言前缀请求 308 → /zh-CN
  i18n/
    routing.ts                 # defineRouting({ locales: ["zh-CN"], defaultLocale: "zh-CN" })
    request.ts                 # getRequestConfig：按 locale import 对应 messages
  messages/
    zh-CN.json                 # V1 唯一消息文件；扁平点分 key，按功能域命名空间
  app/
    [locale]/
      layout.tsx               # import ../../tokens.css；NextIntlClientProvider 包裹；generateStaticParams=[zh-CN]
      page.tsx …               # 现有 app/page.tsx、layout.tsx 迁入，原 app/ 目录不留页面
  tokens.css                   # 见 §3.6，:root 全量 primitive+semantic 变量
  tokens.ts                    # 同值 TS 镜像（图表/Canvas 消费），配一致性测试（见 §3.5）
```

落码步骤（顺序即依赖序）：
1. `npm i next-intl`；建 i18n/routing.ts、i18n/request.ts、middleware.ts（next-intl App Router 官方三件套结构，不自造变体）；
2. `app/*` 迁入 `app/[locale]/*`，layout 注入 NextIntlClientProvider 并 import tokens.css；
3. 建 messages/zh-CN.json，现有页面文案全部改 `useTranslations`/`getTranslations`；命名空间按后端域：`common.*`、`intake.*`（含 `intake.status.*`，与 docs/13 状态词一一对应）、`fieldpool.*`、`pwc.*`、`pws.*`、`skill7.*`（候选/裁决/工作台）、`dashboard.*`、`tenant.*`（Q95 租户管理/引导）、`error.*`（错误码映射）；
4. 后端错误体只消费 `code`+参数，前端按 `error.<code>` 拼文案（HTTP 403/404/409/422 各有通用兜底 key）；枚举码、fid、审计 action 码不进消息表；
5. 时间展示统一 `Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", … })`，时区作为配置常量不散落组件；
6. M12 页面验收口径（评审项，V1 不上 lint 插件）：页面无硬编码中文业务文案、无前端自创状态词。

### 2.4 V3 启用外语时（路线图已列"国际化（多语言界面）"）

- 建议首个外语 `en-US`（非业务裁决，仅工程默认；实际语种顺序待负责人/客户输入决定）；
- 加语言切换器（账号级偏好）、运营数据 name_i18n 扩展（见 §1）、消息翻译完整性检查（缺 key 构建期失败）；
- RTL（阿拉伯语等）不在 V1/V3 承诺范围，需要时 token 层已用逻辑属性（`margin-inline-start` 等）预留。

---

## 3. 设计 Token 方案（Q96 定稿）

> **接缝②拍板（Q96）**：载体 = **CSS Modules + tokens.css CSS 变量**（Tailwind 否掉、Ant Design 组件库否掉——不引 antd 依赖，仅借其色值，见 §3.6）；V1 仅浅色。

### 3.1 分层模型：Primitive → Semantic → Component

```
Primitive（原始值，只定义不直接消费）
  --color-blue-600: #1677ff; --space-1: 4px; --radius-2: 8px; …
Semantic（语义层，组件唯一允许引用的层）
  --color-surface-1 / --color-text-primary / --color-border-subtle
  --color-state-success / --color-state-warning / --color-state-danger / --color-state-info
Component（组件级覆写，能少则少）
  --button-primary-bg: var(--color-brand-500);
```

- 组件**禁止直接消费 Primitive 或裸色值**，只引用 Semantic（V1 靠评审，V3 白牌前补 stylelint 规则强制）。
- 主题切换机制：CSS 自定义属性 + `:root`（浅色）/ `[data-theme="dark"]`（深色）。**V1 只做浅色**，但所有色值走变量，深色/白牌是"换一套变量"而非改组件。
- 白牌定制（V3 路线图）落点：租户级主题包 = 一组 Semantic 变量覆盖（`:root[data-tenant="x"]`），组件零改动。这是选 CSS 变量而非预处理器变量的主要原因。

### 3.2 Token 类别与命名（kebab-case，全小写）

| 类别 | 前缀 | 示例 | V1 约定 |
|---|---|---|---|
| 颜色（语义） | `--color-*` | `--color-text-primary`、`--color-surface-1/2/3`、`--color-border-subtle/strong`、`--color-brand-*`、`--color-state-success/warning/danger/info` | 中性灰阶 + 单一品牌色；状态色四态固定 |
| 字体 | `--font-*` | `--font-family-sans`、`--font-size-{xs..2xl}`、`--font-weight-*`、`--line-height-*` | 见 3.3 |
| 间距 | `--space-{1..8}` | 4px 基准：4/8/12/16/24/32/48/64 | 禁止 5/7/13 等非刻度值（评审） |
| 圆角 | `--radius-{1..4}` | 4/8/12/16 | — |
| 阴影 | `--shadow-{1..3}` | 悬浮/弹层/模态三档 | — |
| 层级 | `--z-{dropdown,sticky,modal,popover,toast}` | 固定枚举，禁止魔法数字 | — |
| 断点 | `--bp-{sm,md,lg,xl}` | 后台以桌面为主：≥1280 主设计宽度 | 客户前端移动适配在 V2/V3 评估 |
| 动效 | `--motion-duration-*`、`--motion-ease-*` | 100/200ms | 尊重 `prefers-reduced-motion` |
| 布局 | `--layout-content-max`、`--sidebar-width` | 后台双栏/表单口径 | — |

### 3.3 中文字体栈与字号

- `--font-family-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;`（系统字体栈，零网络字体、CJK 合规无版权风险；数字/英文可挂 `Inter`/`SF Pro` 但 V1 不引外部字体文件）。
- 字号阶：12/13/14/16/18/20/24/30（后台基准正文 14px，表格密集场景 13px）。行高 CJK 1.6–1.7、西文 1.5。
- 等宽（fid/ID/JSON 展示）：`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`。

### 3.4 业务状态色映射（与 docs/13 状态机/闸门口径对齐）

| 业务语义 | token | 典型状态 |
|---|---|---|
| 成功/通过/已批准/active/frozen | `--color-state-success` | approved、active、frozen、审核通过 |
| 警示/待办/细看/升级 | `--color-state-warning` | pending_gate、needs_detail（conf<0.85）、escalated、72h 临期 |
| 危险/驳回/阻断/急停 | `--color-state-danger` | rejected、blocked、revoked、disabled_expression、block_required |
| 信息/中性进行中 | `--color-state-info` | submitted、in_review、modeling、冷却中 |
| 失效/归档 | 中性灰阶（非状态色） | archived、deprecated、superseded |

> 状态色只表达 docs 已有状态词，不新增业务语义；同一状态在管理后台与客户前端必须同色（单一 token 源）。色值本身无原文依据，V1 由设计/负责人给定具体 HEX 后写入 primitive 层【具体色值待设计产出，本文不给数字拍板】。

### 3.5 技术载体建议（V1 最小方案）

- 样式方案：**CSS Modules + `tokens.css`（CSS 变量）**，与现有裸 Next 脚手架零新增重依赖；**V1 不引入 Tailwind**（无设计体系沉淀时 utility 类反而固化随手值；V3 白牌若证实需要再评估 Tailwind theme 映射，届时语义变量仍是单一源）。
- 文件：`frontend/app/tokens.css`（`:root` 全量变量，V1 唯一事实源）；组件用 `*.module.css` 引用变量；TS 侧如需 token（图表/Canvas）从 `tokens.css` 同源导出一份 `frontend/app/tokens.ts`（手写常量镜像，加测试断言与 CSS 一致；V3 白牌多主题前再上 W3C Design Tokens JSON + 构建生成，避免现在过早引入 Style Dictionary 构建链）。
- 可访问性：状态色/文字色对比度满足 WCAG AA（正文 ≥4.5:1），颜色不作为唯一信息载体（状态同时有文案/图标，与"客户无感知中性话术"等口径不冲突）。

---

### 3.6 具体值初版（Q96 接缝④拍板：借 Ant Design 5 默认调色板，2026-09-16）

> 色值无业务原文来源（line NNNN 无视觉规格），属工程建议值；负责人 Q96 拍板借用 Ant Design 5 默认 token 色板作为 primitive 初值，**只抄值不装 antd 依赖、不引其组件/主题系统**。设计日后产出品牌视觉时只换 primitive 层，semantic/component 与组件代码不动。

Primitive（只定义，组件不直接引用）：

```css
:root {
  /* 文本/中性（AntD5 黑透明阶） */
  --color-text-primary: rgba(0, 0, 0, 0.88);
  --color-text-secondary: rgba(0, 0, 0, 0.65);
  --color-text-tertiary: rgba(0, 0, 0, 0.45);
  --color-text-disabled: rgba(0, 0, 0, 0.25);
  --color-text-on-brand: #ffffff;
  /*  surfaces */
  --color-surface-1: #ffffff;   /* 卡片/弹层 */
  --color-surface-2: #fafafa;   /* 斑马纹/浅底区块 */
  --color-surface-3: #f5f5f5;   /* 页面底色 */
  /* 边框 */
  --color-border-subtle: #f0f0f0;
  --color-border-strong: #d9d9d9;
  /* 品牌（AntD blue 阶，#1677ff = blue-6） */
  --color-brand-1: #e6f4ff;     /* 选中底/浅底 */
  --color-brand-5: #4096ff;     /* hover */
  --color-brand-6: #1677ff;     /* 默认主色 */
  --color-brand-7: #0958d9;     /* active/文字态（AA） */
  /* 状态四态：base=图标/边框，strong=文字（AA 对比度），bg=浅底 */
  --color-success: #52c41a;  --color-success-strong: #389e0d;  --color-success-bg: #f6ffed;
  --color-warning: #faad14;  --color-warning-strong: #d48806;  --color-warning-bg: #fffbe6;
  --color-danger:  #ff4d4f;  --color-danger-strong:  #cf1322;  --color-danger-bg:  #fff2f0;
  --color-info:    #1677ff;  --color-info-strong:    #0958d9;  --color-info-bg:    #e6f4ff;
}
```

Semantic（组件唯一允许引用层；在 tokens.css 同文件下一段落定义）：

```css
:root {
  --color-bg-page: var(--color-surface-3);
  --color-bg-card: var(--color-surface-1);
  --color-border: var(--color-border-strong);
  --color-brand: var(--color-brand-6);
  --color-brand-hover: var(--color-brand-5);
  --color-brand-active: var(--color-brand-7);
  --color-state-success: var(--color-success);
  --color-state-warning: var(--color-warning);
  --color-state-danger: var(--color-danger);
  --color-state-info: var(--color-info);
  /* 状态文字一律走 *-strong，禁止直接用 base 色排正文（AA） */
}
```

其余类别沿用本文件 §3.2–3.3 已定刻度，落码即这些值：间距 4/8/12/16/24/32/48/64；圆角 4/8/12/16；字号 12/13/14/16/18/20/24/30（正文 14、表格 13）；阴影三档：

```css
--shadow-1: 0 1px 2px 0 rgba(0,0,0,0.06);                                  /* 卡片 */
--shadow-2: 0 6px 16px 0 rgba(0,0,0,0.08), 0 3px 6px -4px rgba(0,0,0,0.12);/* 悬浮/弹层 */
--shadow-3: 0 9px 28px 8px rgba(0,0,0,0.05), 0 6px 16px 0 rgba(0,0,0,0.08), 0 3px 6px -4px rgba(0,0,0,0.12); /* 模态 */
```

z 层级固定枚举：`--z-dropdown:1000; --z-sticky:1020; --z-fixed:1030; --z-modal-popover:1040; --z-toast:1050;`（popover/modal 同级以 DOM 顺序定）。业务状态→状态色映射严格按 §3.4 表，同色同源。

## 4. 迭代落位

| 阶段 | i18n | Token |
|---|---|---|
| V1（M12 客户前端 8 菜单基础版 + 管理端页面） | zh-CN 单语；`[locale]` 路由 + next-intl + 文案全量走消息表（§2.3 结构）；枚举码不翻译；时间 UTC 存储/上海展示 | tokens.css 初版（§3.6 AntD5 借值已可落码）；CSS Modules；状态色映射 13 状态词；无深色 |
| V2 | 无界面外语；内容多语言按 Q58 独立推进（与本方案解耦） | 按实际页面补 token，不新增机制 |
| V3（路线图已列国际化/白牌） | 启用 en-US（语种顺序待拍板）；语言切换器；运营数据 name_i18n 扩展（04/10 加字段迁移） | 深色主题（如需要）、租户白牌变量包、stylelint 硬编码拦截、W3C token 构建链（多主题证实需要时） |

### 4.1 拍板结果（Q96，2026-09-16，四项接缝全甲；旧第 5 项并入接缝③）

1. i18n 库：**next-intl**（否掉自研轻量字典）；
2. V1 样式载体：**CSS Modules + tokens.css**（否掉 Tailwind 与 AntD 组件库；AntD 仅借色值，不装依赖）；
3. V1 仅 zh-CN、首个外语 V3 再上、工程默认 en-US（语种顺序 V3 按客户输入定）；运营数据字典（G1/G2/contentGoals/动作字典）多语言延 V3，V1 只存中文 canonical、不预留 name_i18n 字段；
4. token 具体色值：**借 Ant Design 5 默认调色板作工程初值**（§3.6 全量列出，可直接落码）；设计产出后只换 primitive 层；
5. （旧第 5 项）同 3：延 V3，V1 不预埋翻译列。

### 4.2 明确不做（防止过度建设）

- V1 不做：外语消息文件、翻译管理平台（TMS）、RTL、深色模式、租户主题包、字典表翻译列、W3C token 构建工具链、网络中文字体；
- 不把内容多语言（Q58）塞进界面 i18n；不在前端自创/硬编码业务状态词。
