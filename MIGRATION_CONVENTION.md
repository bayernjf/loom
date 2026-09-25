# Migration Convention

Loom 的迁移规范，覆盖两类迁移：**数据库迁移**（代码启动后适用）与**文档迁移**（规格并入 docs 时适用）。

## 1. 数据库迁移

> **Loom 现行口径（2026-09-13 起）**：技术选型已定稿 SQLAlchemy 2.x + Alembic（14/15），后端迁移落 `backend/alembic/versions/`，由**手写**新建（**不用 `--autogenerate`**：实测 41 个迁移文件零个带 autogenerate 标记，而本仓迁移常含纯种子、手写约束/FK/partial index，自动生成会给出不完整甚至含误删语句的脚本；2026-09-25 Q198 按仓库实况订正，原句写的是通用做法），迁移信息通过 `LOOM_DATABASE_DSN` 环境变量传入（禁止在文件中写凭证）。下述 SQL 文件命名/头注释/幂等规则作为**通用项目模板**保留；Loom 迁移同样遵守其一文件一变更、snake_case 描述、只追加不改写历史的精神（Alembic 用 revision 链 + downgrade 表达）。

### 1.1 目录

- **Supabase 项目** → `supabase/migrations/`
- **其他项目**（自托管 Postgres / SQLite 等）→ `db/migrations/`

所有新迁移文件放入对应目录。

### 1.2 文件命名

```
NNN_verb_snake_case.sql
```

- `NNN` — 三位数字，从 `001` 起，严格递增且全局唯一。**不重复、不跳号。**
  - **Loom 实况**：Alembic 侧用**四位**前缀（`0001_…` 至 `0041_…`，2026-09-25 实测 41 个版本文件），上述三位数是通用模板口径；revision id 列宽已因 0021 起长 id 被加宽到 128（02 C1.62 顺带修复），新建时**照四位与既有命名**，别照本行模板写成三位。
- 描述为英文 `snake_case`，动词开头：`create_` / `add_` / `alter_` / `fix_` / `drop_`。
- 一个文件只做一个变更；多步骤变更拆成连续文件（如 `001_...`、`002_...`）。

示例：

```
001_create_profiles.sql
002_add_theme_preference.sql
003_fix_updated_at_trigger.sql
```

### 1.3 头注释（必需）

每个迁移文件必须以如下头注释开头（全部英文）：

```sql
-- =====================================================
-- Migration 001: Add theme preference to profiles
-- File: 001_add_theme_preference.sql
-- Date: 2026-09-10 14:30
-- Depends on: 0XX_xxx.sql
-- Ref: https://prd/requirement/42
-- Run: Supabase SQL Editor, execute once
-- =====================================================
-- Note: why this migration exists, background, impact.
-- -----------------------------------------------------
```

| 字段 | 必需 | 格式 |
|---|---|---|
| `-- Migration NNN:` | 是 | `Migration 001: One-line title` |
| `-- File:` | 是 | 文件名，必须与实际文件一致 |
| `-- Date:` | 是 | `YYYY-MM-DD HH:mm`，24 小时制，精确到分钟 |
| `-- Depends on:` | 否 | 依赖的上一个迁移；无则省略 |
| `-- Ref:` | 否 | PRD / 需求 / issue 链接 |
| `-- Run:` | 否 | 执行方式（Supabase SQL Editor、CLI 等） |
| `-- Note:` | 建议 | 背景、原因、影响；可多行 |

规则：

- `-- Date:` 创建时设置一次，之后**永不修改**。
- 后续修订在 `-- Note:` 区追加 `-- Updated: <YYYY-MM-DD HH:mm> <reason>`。
- 废弃迁移：历史文件保持不动，新建 drop 迁移；若必须标记原文件，在头注释顶部加 `-- Obsoleted: YYYY-MM-DD HH:mm`。

### 1.4 SQL 风格

- **幂等** — 使用 `IF NOT EXISTS` / `IF EXISTS` / `DROP ... IF EXISTS`，保证可重复执行安全。
- 每个新列/新表加 `COMMENT ON`。
- 标识符用 `snake_case`；语句保持简单可读。

### 1.5 示例

```sql
-- =====================================================
-- Migration 001: Add theme preference to profiles
-- File: 001_add_theme_preference.sql
-- Date: 2026-09-10 14:30
-- Depends on: none
-- Ref: https://prd/requirement/42
-- Run: Supabase SQL Editor, execute once
-- =====================================================
-- Note: Persists cross-device theme preference, default
--       "glass". Aligns with docs/10 schema.
-- -----------------------------------------------------
ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS theme_preference TEXT DEFAULT 'glass';
COMMENT ON COLUMN profiles.theme_preference
  IS 'Page theme: glass/dark/light';
```

### 1.6 Do / Don't

| Do | Don't |
|---|---|
| 编号严格递增 | 复用编号（如两个 `002_`） |
| `-- Date:` 创建时设置且不变 | 之后修改原始日期 |
| 每条语句幂等 | 假设迁移只在全新库上跑一次 |
| 一个文件一个变更 | 把无关变更塞进一个文件 |
| 就地标记废弃或新建 drop 迁移 | 删除 / 重写历史迁移文件 |

## 2. 文档迁移（规格并入 docs）

> 适用：把新来源（HTML 原型、业务方素材、旧 md）并入 docs 唯一事实源体系时。

- **切分去向**：按消费场景归入对应文档（01–17），并在 [docs/README 信息保全映射表](docs/README_文档地图与治理.md) 登记 Part → 目标文档的映射。
- **零丢失**：迁移前做段落级核验（逐段检查 line 引用 / Q 编号 / 状态词 / 专名是否落入目标文档），核验记录写入 README §5.3。
- **不新增事实**：迁移只搬运、不新增业务事实；原文空缺处标【原文未给出，待补】。
- **行号溯源**：`line NNNN` 引用保留，指向基准文件 `Docs/Loom_后台_V6.0-需求说明（不是原型).html`；基准文件行号变化需同步核对——**该基准 HTML 已于 2026-09-17 经负责人确认永久丢失（Q115），故本句在 Loom 侧失效：`line NNNN` 降级为历史痕迹，改动时无需（也无法）同步核对**。
- **归档删除**：原文件删除前必须完成核验并记录（参考 v3.md 归档：231 段核验零丢失）。
