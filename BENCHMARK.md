# Benchmark

Loom 的性能与容量基准登记表。**代码已实现并有实测台账**（原「当前处于文档阶段，无代码可测」为 2026-09-13 建档时口径，Q198 订正；实测结论与断言数一律以 docs/17 §7 各演练小节与 docs/02 C1 为准，本文件不复制数字）——本文件先定范围与登记格式，代码启动后按实测回填。

## How to run

六套端到端演练就是本表的数据来源，全部**本地手动、不进 CI**（要起多容器、断言依赖宿主网络）；脚本自身只跑负载与断言，**不产出基准数字文件**，实测值只登记在 docs/17 §7 对应小节。命令均在 `infra/` 下执行，且都需要本机 Docker；脚本一律用一次性容器/独立宿主端口，不触碰本机 atlas-pg。

| 场景 | 制品 | 权威结果 |
|---|---|---|
| 多副本迁移串行 + 分片消费 + 抢锁互斥 | `./ha-rehearsal.sh`（四阶段 16 断言） | docs/17 §7.1（Q157） |
| 异机备份恢复逐表零差异 | `./restore-rehearsal.sh`（源/异机两独立容器） | docs/17 §7.2（Q158） |
| 持续高压负载（export job 提交/消费、锁竞争、读口） | `./load-rehearsal.sh up\|run\|down`，旋钮 `LOOM_LOAD_MINUTES`／`LOOM_LOAD_RATE`／`LOOM_CHURN_EVERY`／`LOOM_CHURN_BURST` | docs/17 §7.3（Q173） |
| RPO·RTO 量化（故障注入 + 计时恢复） | `./rpo-rto-rehearsal.sh up\|down`（`KEEP=1` 保留容器） | docs/17 §7.4（Q175） |
| WAL 归档 + 对象存储 PITR | `./wal/pitr-rehearsal.sh`（自包含网络与命名卷） | docs/17 §7.5（Q182） |
| 指标采集 → 规则求值 → 告警转发 → 看板 | `./alerting-rehearsal.sh up\|run\|down`（叠 staging + monitoring overlay） | docs/17 §7.6（Q185/Q188/Q192/Q193） |
| 全链 golden path（真 PG 变体） | `./fullchain-rehearsal.sh`（一次性 pg16 容器；默认 synthetic 不花钱，`LOOM_E2E_REAL_LLM=1`＋`LOOM_E2E_AGNES_KEY` 才走真 agnes，需负责人授权） | docs/17 §7 的 Q169–Q172 补记段与 02 C1；**同一 golden path 的 sqlite 变体在后端 pytest 里进 CI**，真 PG 变体不进 |

此外每次 push 由 CI 的 `Migration gate` 在真 PG16 上跑迁移往返与 ORM⇄DB 漂移检查（docs/17 §7.7，Q207）——那是**一致性门，不是基准**，不产出性能数字。

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

> **口径**：本表刻意不复制数字（见文件头），只登记「场景 → 制品 → 权威结果」。注意两套东西不是一回事：上面八条是**建档时规划的业务吞吐维度**，而今天真实存在的六套演练测的是**基础设施行为**（异步作业吞吐与不丢单、多副本锁互斥、备份/恢复/PITR、告警链路）。**八条业务维度至今没有一条有专属 harness**，所以它们没有行；补一行之前要先有测它的脚本，且数字只落 docs/17。

## Results

| 场景 | 演练制品 | 度量口径（数值不在此复制） | 权威结果 | 进 CI？ |
|---|---|---|---|---|
| 持续高压负载 | `infra/load-rehearsal.sh` | 固定时长窗口内 export job 提交数 vs 完成数、5xx 计数、抢锁 200/409 分布、drain 后队列余量 | docs/17 §7.3 | 否（本地手动） |
| RPO / RTO | `infra/rpo-rto-rehearsal.sh` | RPO＝故障时刻−备份时刻；RTO＝恢复动作全程计时（不含人员发现与决策） | docs/17 §7.4 | 否 |
| PITR 时点精确性 | `infra/wal/pitr-rehearsal.sh` | 目标时刻前一事务在、后一事务不在；RPO 上限＝`archive_timeout` | docs/17 §7.5 | 否 |
| 多副本正确性 | `infra/ha-rehearsal.sh` | 并发迁移串行化、两 consumer 分片、单 leader 互斥、广播后 reload | docs/17 §7.1 | 否 |
| 备份恢复内容一致性 | `infra/restore-rehearsal.sh` | 逐表行数差异、结构对象计数、关键表逐字段比对、恢复库再迁移幂等 | docs/17 §7.2 | 否 |
| 告警链路可用性 | `infra/alerting-rehearsal.sh` | 规则装载数与 `health`、firing 观测时刻、每故障转发次数（去重） | docs/17 §7.6 | 否 |

## Known limits

- **吞吐数字目前全部建立在 synthetic 或工程自造数据上**：`publish_slots`/`pcp_weight_tables`/`packages`/`platform_rules` 四表零行（docs/19 待业务方回填），因此没有任何一行数字可以读成"真实业务负载下的容量"。见 docs/17 §7.3「仍挂 V2」。
- **没有正式 QPS／P99 容量口径**：业务侧未给目标值，现有演练只证「不丢单、不 5xx、互斥正确」，不证容量上限（docs/17 §7.3/§7.6 末段）。
- **覆盖率门槛当前不可判定**：docs/16 §4 的「核心规则层 ≥ 90%／全系统 ≥ 70%」标着【建议】，而仓内既无 `pytest-cov` 依赖也无 `--cov` 调用，CI 三步都不产覆盖率——该目标不是"已达成"也不是"未达成"，是**没有测量手段**。要启用它得先点工装 harness。
- **告警阈值未经真实负载校准**：队列积压／流长度／上游延迟三个阈值数值是工程默认值，追认只结设计不结校准（docs/17 §7.6 仍挂①）。
- **对象存储跨 region 冗余**仍 V2。
- **V1 目标 5–10 客户**（docs/08 迭代计划）：单实例承载客户数上限从未测过，上表没有任何一行覆盖它。
