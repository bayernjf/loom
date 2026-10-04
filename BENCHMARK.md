# Benchmark

Loom 的性能与容量基准登记表。**代码已实现并有实测台账**（原「当前处于文档阶段，无代码可测」为 2026-09-13 建档时口径，Q198 订正；实测结论与断言数一律以 docs/17 §7 各演练小节与 docs/02 C1 为准，本文件不复制数字）——本文件先定范围与登记格式，代码启动后按实测回填。

## How to run

**八套**端到端演练（Q282 增 `gateway-rehearsal.sh`）就是本表的数据来源，**脚本本体全部本地手动、不进 CI**（要起多容器、断言依赖宿主网络）；其中**不需要容器的那一半**自 Q229 起由 CI job `infra-static` 以**等价门**覆盖（五个 compose overlay 各自过 `docker compose config -q`、`promtool check config/rules` 校 PromQL 语法），但**进 CI 的是等价门、不是 `*rehearsal.sh` 本体**（实质判据：该文件里**没有任何 `run` 步执行 `*rehearsal*.sh`**；`grep -n rehearsal .github/workflows/ci.yml` 命中 4 处——Q227 注释 3 行＋`docker-compose.alerting-rehearsal.yml` 文件名 1 处，无一处执行脚本）；脚本自身只跑负载与断言，**不产出基准数字文件**，实测值只登记在 docs/17 §7 对应小节。命令均在 `infra/` 下执行，且都需要本机 Docker；脚本一律用一次性容器/独立宿主端口，不触碰本机 atlas-pg。

| 场景 | 制品 | 权威结果 |
|---|---|---|
| 多副本迁移串行 + 分片消费 + 抢锁互斥 | `./ha-rehearsal.sh`（四阶段 16 断言） | docs/17 §7.1（Q157） |
| 异机备份恢复逐表零差异 | `./restore-rehearsal.sh`（源/异机两独立容器） | docs/17 §7.2（Q158） |
| 持续高压负载（export job 提交/消费、锁竞争、读口） | `./load-rehearsal.sh up\|run\|down`，旋钮 `LOOM_LOAD_MINUTES`／`LOOM_LOAD_RATE`／`LOOM_CHURN_EVERY`／`LOOM_CHURN_BURST` | docs/17 §7.3（Q173） |
| RPO·RTO 量化（故障注入 + 计时恢复） | `./rpo-rto-rehearsal.sh up\|down`（`KEEP=1` 保留容器） | docs/17 §7.4（Q175） |
| WAL 归档 + 对象存储 PITR | `./wal/pitr-rehearsal.sh`（自包含网络与命名卷） | docs/17 §7.5（Q182） |
| 指标采集 → 规则求值 → 告警转发 → 看板 | `./alerting-rehearsal.sh up\|run\|down`（叠 staging + monitoring overlay） | docs/17 §7.6（Q185/Q188/Q192/Q193） |
| 全链 golden path（真 PG 变体） | `./fullchain-rehearsal.sh`（一次性 pg16 容器；默认 synthetic 不花钱，`LOOM_E2E_REAL_LLM=1`＋`LOOM_E2E_AGNES_KEY` 才走真 agnes，需负责人授权） | docs/17 §7 的 Q169–Q172 补记段与 02 C1；**同一 golden path 的 sqlite 变体在后端 pytest 里进 CI**，真 PG 变体不进 |
| 网关对外发布面／放行面／拦截面／`LOOM_PUBLIC_BASE_URL` 旋钮 | `./gateway-rehearsal.sh up|run|down`（真栈叠 base＋gateway，project=`loom-gateway`；四段 21 断言） | docs/17 §7.8（Q282） |

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

> **口径**：本表刻意不复制数字（见文件头），只登记「场景 → 制品 → 权威结果」。注意两套东西不是一回事：上面八条是**建档时规划的业务吞吐维度**，而今天真实存在的七套演练测的是**基础设施行为**（异步作业吞吐与不丢单、多副本锁互斥、备份/恢复/PITR、告警链路）。**八条业务维度至今没有一条有专属 harness**，所以它们没有行；补一行之前要先有测它的脚本，且数字只落 docs/17。

## Results

| 场景 | 演练制品 | 度量口径（数值不在此复制） | 权威结果 | 进 CI？ |
|---|---|---|---|---|
| 持续高压负载 | `infra/load-rehearsal.sh` | 固定时长窗口内 export job 提交数 vs 完成数、5xx 计数、抢锁 200/409 分布、drain 后队列余量 | docs/17 §7.3 | 否（本地手动） |
| RPO / RTO | `infra/rpo-rto-rehearsal.sh` | RPO＝故障时刻−备份时刻；RTO＝恢复动作全程计时（不含人员发现与决策） | docs/17 §7.4 | 否 |
| PITR 时点精确性 | `infra/wal/pitr-rehearsal.sh` | 目标时刻前一事务在、后一事务不在；RPO 上限＝`archive_timeout` | docs/17 §7.5 | 否 |
| 多副本正确性 | `infra/ha-rehearsal.sh` | 并发迁移串行化、两 consumer 分片、单 leader 互斥、广播后 reload | docs/17 §7.1 | 否 |
| 备份恢复内容一致性 | `infra/restore-rehearsal.sh` | 逐表行数差异、结构对象计数、关键表逐字段比对、恢复库再迁移幂等 | docs/17 §7.2 | 否 |
| 告警链路可用性 | `infra/alerting-rehearsal.sh` | 规则装载数与 `health`、firing 观测时刻、每故障转发次数（去重） | docs/17 §7.6 | 否（脚本本地）；静态一半（compose 解析＋promtool 语法）进 CI `infra-static`（Q229） |

## Known limits

- **吞吐数字目前全部建立在 synthetic 或工程自造数据上**：`publish_slots`/`pcp_weight_tables`/`packages` **三表零行**（docs/19 §0.2「最小可发证清单」待业务方回填；`platform_rules` 同为空，但 Q220 回代码验过它唯一消费者是 `platform_adaptation` 自己、**不卡第一张 `final_id`**，故不列进对外索取清单），因此没有任何一行数字可以读成"真实业务负载下的容量"。见 docs/17 §7.3「仍挂 V2」。
- **没有正式 QPS／P99 容量口径**：业务侧未给目标值，现有演练只证「不丢单、不 5xx、互斥正确」，不证容量上限（docs/17 §7.3/§7.6 末段）。
- **覆盖率有尺、无门（Q221，2026-09-27）**：docs/16 §4 的「核心规则层 ≥ 90%／全系统 ≥ 70%」标着【建议】。此前仓内既无 `pytest-cov` 依赖也无 `--cov` 调用，该目标**没有测量手段**；自 Q221 起 CI backend job 跑 `pytest --cov=app`，由 `backend/scripts/coverage_report.py` 打印读数（恒退 0，不阻断）。2026-09-27 单次实测：核心规则层 **99.34%**／全系统 **72.78%**（runner 首读，本机同命令 72.02%）。**2026-09-28 更新（Q232 后 runner 读数）**：全系统 **72.2%**（12,414 条语句）／核心规则层仍 **99.34%**——72.78% 那句按 Q222 的结论是**依赖浮动解析**造成的两侧不同套，lock 之后本机与 runner 已同数，旧读数只作该时点快照保留、不读成现行值。**仍未验证的部分**：这是单次运行、单副本 sqlite＋Fake 替身下的读数；阈值是否应成为硬门、真 PG／多副本形态下覆盖率是否一致，都还是未开的口。**阈值口径（Q229，用户裁决「维持【建议】只测量」）**：**不设 `--cov-fail-under`、不上硬门**——单次读数＋sqlite/替身样本不构成硬门的证据基础（`test_coverage_is_wired_and_gates_nothing` 继续硬守「接线要在、阈值不能在」）。
- **告警阈值未经真实负载校准**：队列积压／流长度／上游延迟三个阈值数值是工程默认值，追认只结设计不结校准（docs/17 §7.6 仍挂①）。
- **对象存储跨 region 冗余**仍 V2。
- **V1 目标 5–10 客户**（docs/08 迭代计划）：单实例承载客户数上限从未测过，上表没有任何一行覆盖它。
