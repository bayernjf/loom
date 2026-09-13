# Contributing

感谢参与 Loom 的建设。Loom 是私域内容生产白名单平台（SaaS 后台）——当前处于**设计/文档阶段**，本仓库的核心资产是 `docs/` 规格体系（13 段链内容生产链的唯一事实源）。

## 前提

- 改动前**先读** [handoff.md](handoff.md)（当前状态/待办）与 [docs/README_文档地图与治理.md](docs/README_文档地图与治理.md)（场景导航 + 治理规则）。

## 怎么改文档

- **唯一事实源** = `docs/`。任何规格变更先改对应文档，不另建并行来源。
- **新决策**：追加 Q 编号到 02 决策记录（C1 日志），不重写或篡改历史条目。
- **事实纪律**：数字/状态/结论必须可溯源（Q 编号 / line 行号）；原文空缺处标【原文未给出，待补】，禁止编造业务事实。
- **不擅自裁决**：S 级红旗 4 条、路线图口径合并、技术选型 6 项等明确挂起事项，必须由负责人/用户拍板（拍板后同步在 02 追加 Q 记录）。
- **两套口径**：13 段链（权威，01）与展示口径（09）分置不混用；涉及展示层的改动需同步渲染口径。

## Commit messages

- 英文、祈使语气：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`。
- **原子提交**——一个逻辑变更一个 commit；`docs/` 与 readme 独立成 docs 提交；配置独立成 chore 提交。
- 完整规范见 [git-commit-message.md](git-commit-message.md)。

## 分支与 PR

- 工作分支为 `dev`（跟踪 `origin/dev`）；`main` 为发布基线，合入由负责人操作。
- 当前无代码、无 CI；代码启动后 PR 需通过 test / typecheck / build 三绿（见 docs/16 测试策略）。

## License

By contributing, you agree your contributions are licensed under the MIT License.
