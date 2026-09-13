# Benchmark

Loom 的性能与容量基准登记表。**当前处于文档阶段，无代码可测**——本文件先定范围与登记格式，代码启动后按实测回填。

## How to run

> TODO: fill in the concrete commands once a benchmark harness exists（代码启动后补，与 docs/16 测试策略联动）。

## Scope

What is measured（按实测逐项启用，来源标注 docs 对应文档）：

- 13 段链端到端吞吐（白名单产线：录入 → PWS 冻结 → final_id，graph/sec）
- 原子相撞与 PWC 组合吞吐（段 4/5，预筛漏斗 Q21 后的实际量级）
- 合规清洗扫描延迟（段 10，词库扫描 + block_required 一票否决路径）
- Guard / 人工审核台并发（approveAtomGuard、HumanGate、SLA 待办队列）
- 事件写入与审计吞吐（writeAudit append-only、C7 缓存命中率）
- 多租户隔离下的资源占用（Q33，单实例承载客户数上限）
- 冷启动与重启时间（服务端 / 管理后台）
- 省 token 策略效果（10 条省 token 策略，D7.2 策略 7）

## Results

| Date | Baseline (commit / version) | Scenario | Metric | Value | Notes |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

## Known limits

> TODO: document capacity limits and resource ceilings as they are measured（V1 目标 5–10 客户，见 08 迭代计划）。
