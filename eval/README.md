# eval/ — Evaluation Dataset + Golden Cases（M10-Q，14 §2.6 轻量版）

AI Skill 质量回归两件套：**Evaluation Dataset**（每 Skill 回归矩阵，防 S2
"Skill 从未运行"）与 **Golden Cases**（人工精选标杆案例库）。V1 形态经
负责人拍板（**Q77**，docs/02 C1.21）。

## 目录

```
eval/
├── runner.py                 # 回归 runner：扫两套 YAML、调 target、比对、退出码闸门
├── targets.py                # target 名 → 确定性 Skill 替身函数适配器
├── datasets/skills/          # Evaluation Dataset：每 Skill 一份回归矩阵
│   ├── PWC-SCORING.yaml
│   ├── COMBO-VALIDATE.yaml
│   ├── DIM-MERGE.yaml        # WF-02 字段池（Q78 切片自带）
│   └── CAT-RECOG.yaml        # WF-01 C1 识别（Q79 切片自带）
└── golden_cases/skills/      # Golden Cases：人工策展标杆（同 schema，范围小）
    ├── PWC-SCORING.yaml
    ├── COMBO-VALIDATE.yaml
    ├── DIM-MERGE.yaml
    └── CAT-RECOG.yaml
```

## 运行（staging 回归闸门，docs/17 CI/CD）

仓库根目录，用 backend venv（runner 经 sys.path 引用 backend `app` 纯逻辑）：

```bash
backend/.venv/bin/python eval/runner.py
```

全部通过退出码 0；任一案例失败或 target 抛错退出码 1，阻断发布。

## case schema

```yaml
skill_id: PWC-SCORING          # 对齐 runtime/skills 注册表 skill_id
wf_id: WF-04
cases:
  - id: 唯一 id
    title: 人话描述
    target: score_combo        # 必须在 targets.py TARGETS 注册
    input: { ... }             # target 适配器入参（YAML 友好类型）
    expected: { ... }          # 期望输出；dict 为子集断言，float 走 tolerance
    tolerance: 0.000000001     # 可选，默认 1e-9
    source:
      refs: [Q22, "docs/06 §1.1", "line 918"]   # 每条案例必须可溯源
```

## V1 覆盖与边界（Q77）

- **首批只打 WF-04 中有确定性替身的两个 Skill**：
  - `PWC-SCORING` → Q22/Q22a/Q22b 评分（`pwc_rules.score_combo` /
    `overlap_ratio` / `max_overlap` / `is_duplicate`）；
  - `COMBO-VALIDATE` → Q48 词表确定性子串匹配（`match_words`）。
- **WF-02 替换切片补 `DIM-MERGE`（Q78，每 WF 替换切片自带 eval 回归）**：
  → PT-FP-PLAN-V2.0 结构校验（`fieldpool.planning.evaluate_plan`），
  覆盖 Q8 启用路由 / Q9 细看线 / Q10 疑重仅标记 / Q11 敏感行业 risk_control /
  Q12 Top8+备选与 below_min / line 14081 依据必填 / fid 活跃校验，共 12+3 例。
- **WF-01 替换切片补 `CAT-RECOG`（Q79，每 WF 替换切片自带 eval 回归）**：
  → c1 纯函数（`modeling.c1.weighted_conf` / `decide_branch`），覆盖 Q2 权重
  加权（Σ=1 不归一化）/ Q1 三分支边界（0.6 地板包含、阈值≥）/ Q3 Top1-Top2
  <0.1 矛盾线优先转 ops_assist，共 11+3 例。错误分支（WeightSumError/
  MissingSignalScore）runner 无错误案例 schema，由 backend 集成测试覆盖。
- **PWC-BUILDER 无案例（挂账）**：该 Skill V1 为外部投递，仓库内无确定性
  生成实现，不构造虚拟案例；真 LLM 切片落地后补。
- COMBO-VALIDATE 的结构预筛（≥2 维度/同批去重/跨租户拦截等）目前内联在
  `pwc/funnel` 服务内且耦合 DB，未作为纯 target 暴露；其行为由 backend
  集成测试覆盖，后续若抽纯函数再接入本 runner（挂账）。
- WF-03 等其余 Skill 随各自占位替换切片补数据集；C7 Layer4 提案通道随 Q79-1 后续切片。
- 案例一律人工依据 docs 原文/Q 规则编写，**禁止生产数据**（16 §4）；
  词例均为合成词。
- 真 LLM 落地后：同一批 YAML 案例改打 Skill 输出，只改 `targets.py`
  适配器，案例数据不动。
