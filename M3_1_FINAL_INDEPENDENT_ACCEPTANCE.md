# M3.1 Final Independent Acceptance Audit

日期：2026-10-20（Asia/Singapore）
对象：MaterialRequirementChecker-M0 当前工作树，包括未提交及未跟踪的 M3.1 文件。
结论：**GO — 可以进行 LOCAL Git commit；本次未提交。** 这不是部署验收或正式发布许可。

## 1. 审计方法与边界

本轮重新阅读四份历史审计/修复报告及 `M3_1_P1_EXPORT_FIX_REPORT.md`，检查实际源码和 Git diff，重新运行完整测试，另在临时目录编写新的故障注入脚本，并从当前源码重新构建 Windows EXE。没有仅采信此前测试数字或修复摘要。

这是在同一对话及工作区内重新执行的验收检查，保留了此前修复上下文；并非另一位人员或完全隔离的团队审计。独立证据指本轮重新执行和新增的复现场景。没有修改生产代码或已有测试。

审计证据目录：

`C:\Users\25795\AppData\Local\Temp\MRC_Final_Acceptance_634aa02de43541d989c02a4be469c6ae`

- `full-tests.txt`：本轮完整回归输出。
- `independent_audit.py`、`independent-tests.txt`：额外 7 项测试，复用原套件的合成工作簿/Tk 初始化夹具，但重新编写故障触发和断言。
- `independent-metrics.json`：慢速源文件检查时的 Tk 响应测量。
- `baseline.json`、`integrity.json`：本轮前后文件 SHA-256 核对。
- `build.txt`、`smoke/self_test.json`：隔离打包及冻结程序自测。

故障注入只使用合成 Excel 和临时 SQLite。未打开真实公司工作簿、修改同步设置、安装依赖、执行宏、提交、推送或发布；未开始 M3.2/M4。

## 2. 验收结果

| 项目 | 结果 | 本轮证据 |
|---|---|---|
| P0-A：CHECK/source-version consistency | **PASS** | 新增注入在 CHECK 读到库存 100 后、同步前改为 0；只渲染新结果，未发布旧的 verified 100。完整套件中的 BOM 改写、同步重试、持续变化三次后 OUTDATED、过期导出拒绝通过。 |
| P0-B：未记录失败覆盖历史成功 | **PASS** | 新增注入源文件不存在且 `_record_failure` 返回 `recorded=False`；SQLite 仍保留旧成功，UI 显示当前失败，历史数据逐表未变。 |
| P0-C：Cloud Not Verified 常驻 | **PASS** | 完整套件覆盖成功、失败、未知、源不可用、历史数据、未同步、同步中及数据库不可用；960×600、1280×720、1366×728，Tk 100/125/150% 模拟通过。 |
| 未记录失败后重启 | **PASS** | 新增测试记录重启期间每次 `_render_inventory` 状态；没有历史成功状态闪现。保持源不可用，最终为 previous-data/failure。 |
| Refresh-after-CHECK | **PASS** | 现有回归独立重跑通过：Refresh 清除旧结果并重算，未变化 Refresh 不增加快照。 |
| P0-1：数据库状态读取失败 | **PASS** | 新增 SQLite OperationalError 注入及原回归通过：面板/状态栏显示 Status Unknown / Database Read Failed，原有数据保留；可读 Excel 的本地版本计算与数据库失败分开。 |
| 剩余 P1：CHECK 后外部保存、未 Refresh 就导出 | **PASS** | 新增测试分别改 Storage/BOM，分别调用按钮入口 `export()` 和直接 `write_export()`；均拒绝、标 OUTDATED、不生成最终报告。按钮预检失败时不打开保存对话框。 |
| 最终验证失败叠加临时文件清理失败 | **PASS** | 新增生成期间改库存、unlink PermissionError 注入：仍失效化绑定，原始验证错误未被遮蔽，提示残留暂存路径，无最终报告。 |
| P1-1：打包版本保护 | **PASS** | 完整套件实际执行 PowerShell：缺失版本、版本不符、无 AllowDevBuild 的开发版本均拒绝；合法 ValidateOnly 成功，未清理 build/dist。 |
| M2 计算 / Excel-SQLite parity | **PASS（合成数据）** | 原回归、合成 parity、报告表格 payload、重复/无效库存处理全部通过。真实资料的 33 组 parity 本轮未执行。 |
| 事务、回滚、快照和恢复 | **PASS（套件覆盖范围）** | 原测试重跑覆盖写失败全事务回滚、提交边界变化、另一实例发布、版本历史、角色独立同步、相同来源不重复快照。新增竞态后 integrity_check=ok。 |
| 并发及旧 job | **PASS（套件覆盖范围）** | busy 阻止重叠 CHECK/Refresh，队列按 job 丢弃旧响应；旧状态与旧结果回写测试通过，保存对话框期间结果变化拒绝原导出。 |
| Windows standalone | **PASS（本机）** | 本轮从当前源代码在临时目录重新 PyInstaller 构建并运行 EXE；frozen、CHECK、导出、Cloud Not Verified、UNCHANGED Refresh 均通过。 |
| 真实 Drive / 第二台电脑 / 原生高 DPI | **NOT EXECUTED** | 不将 Tk 模拟、本机 EXE 或合成源文件结果当作这些环境的验证。 |

## 3. 实际实现审查

### 导出版本边界

`checker/binding.py:89` 的 `verify_export()` 要求有效的 stock+bom CHECK 绑定，比较完整指纹（路径、文件元数据、ZIP 条目签名）。固定两轮检查，较早失败具有粘性，不能被后续成功覆盖；不读取 SQLite，不用历史缓存替代不可读源文件。

`checker/ui.py:1008` 在保存对话框前检查版本，并捕获 result、binding、job 身份；对话框返回后若结果已改变则拒绝。`checker/ui.py:1058` 的直接写入函数再次进入 guarded writer，不能通过直接调用绕过按钮保护。

`checker/report.py:172` 检查内存工作簿与 CHECK 指纹一致，在输出目录建立独有暂存文件，生成后、发布前再次检查两个源文件。在 Windows 使用不覆盖已有目标的 rename；目标碰撞最多尝试 10 次。原 `safe_target` 防止覆盖源工作簿；已有目标改用编号名称。原始 `save_report()` 仍是无验证的低层格式化 API，但 UI 导出已全部使用 `save_verified_report()`；不能把低层 API 当作当前来源验证入口。

`checker/report.py:212` 起的异常保留及清理处理保留原始 ExportVerificationError，并附加 cleanup_warning；`checker/ui.py:1035` 据此失效化结果、禁用导出并显示错误。OS 拒绝删除时会残留暂存文件，不是成功发布的报告。

报告第 8 行可见 Cloud Not Verified 和本机验证时间；C5/C6 的批注保存文件版本标识、元数据、CHECK 时间和导出预验证时间。记录的时间属于已完成的生成前验证；生成后检查是额外发布门槛，没有伪造未来验证时间。源版本和时间不是永久新鲜或云端新鲜承诺。

### 同步与后台任务

`checker/sync.py` 的事务以 BEGIN IMMEDIATE 串行化写入，异常 ROLLBACK；未变化路径重新核对 current version，导入在事务内检查源，提交后及 sync_all 返回前再次检查。提交后发现变化时保留完整历史版本并返回变化状态，不能假装撤销已提交历史。重试有上限，没有发现新死锁路径；SQLite 每次等待上限 15 秒，极端多进程锁竞争总延迟未压测。

CHECK 本身在 worker 中运行；Tk 更新由主线程队列处理。错误覆盖逻辑在 `checker/queries.py:112` 及 UI `_show_inventory` 中保留，失败信息不被旧 SQLite 成功记录清除。启动先检查记忆来源，不直接展示历史成功。

## 4. 测试数字

完整命令：`.\.venv\Scripts\python.exe -m unittest discover -v`

**205 项：200 通过、5 跳过、0 失败，113.388 秒。** 包括 26 项导出修复回归和之前 P0/P1 测试。5 项跳过均要求 `MRC_TEST_MOUNT_DIR`：挂载文件锁、owner-file/导出、缓存刷新、替换/暂时不可用、读取期间变化。

额外审计脚本：**7 项全部通过，11.173 秒**；其中外部改写测试有 Storage/BOM × UI/direct 的 4 个子场景。这 7 项不计入上面的 205。

额外测试分别验证：外部改写拒绝、最终门槛与清理双故障、100→0 CHECK 竞态、未记录失败重启无成功闪现、SQLite 状态错误与 Excel 计算分离、源文件保护及导出 provenance、慢速导出 Tk 响应。

本轮 EXE 结果：`passed=true`、`frozen=true`、`result_verified=true`、`refresh_unchanged=true`；合成结果 1 SHORTAGE、3 EXCEPTION、1 ENOUGH。异常包括文本库存、缺失编号和重复编号。刷新前后均 2 个 source_versions、1 个 snapshot；合成输入 SHA-256 前后相同。

## 5. P0 / P1 / P2 发现

### P0 / P1

**本轮未发现未解决的 P0/P1。** 原导出 stale-result 阻断项和清理遮蔽错误已复现验证修复。此判断限于已审查代码和已执行场景，不等同于不存在任何缺陷。

### P2 — 已实测：慢速导出阻塞 Tk 主线程

位置：`checker/ui.py:1008`、`:1047`、`:1058`；`checker/report.py:172`。

在成功按钮导出中，对每次 fingerprint 注入 75 ms 延迟。共观察 12 次源检查，总导出 1.078 秒；预先安排 10 ms 的 Tk timer 在函数返回后约 1.078 秒才运行。证明该路径同步阻塞消息处理。真实 Drive placeholder 下载或 I/O 卡顿可能放大等待；本轮没有实际 Drive 时延数据，也没有证明每次导出都会卡顿。

这不绕过版本检查，不产生错误库存结论，因此不作为本地版本保存的阻断项。正式部署前应测真实挂载文件；若可感知阻塞，需要独立的小范围后台导出任务设计。保留 Tk 主线程操作、job/result 身份防护、两次验证、原子不覆盖发布，不能直接复用会清除结果的 `_start()`。本轮未实施重构。

### P2 — 环境与运维限制（既有）

- 真实 Drive 云端新鲜度、placeholder、第二台电脑和原生 DPI 未测；只能确认本机在观察时刻的版本。
- 真实公司 Excel 本轮未读取，不能声称完成真实资料 parity、运行性能或原件前后哈希核对。
- SQLite 默认位于 `%LOCALAPPDATA%\Auraplex\MaterialStockChecker`；没有应用层静态加密/ACL 硬化，自定义数据目录仍需避免同步目录或未验证共享盘。
- 历史/日志保留期尚未实现；12 个月快照、90/180 天日志和缓存 opt-in 均仍属于未开始的 M3.2。
- 没有连续 watcher；CHECK 时间描述过去的本地验证。导出会重检，但最后一次观察后仍可发生外部保存；报告明确保留这一时间边界。
- 进程强制终止/断电或删除被拒绝可能留下暂存文件；未做崩溃耐久性、恶意文件防护或极端多进程压测。

## 6. 原件与发行资产保护

本轮前后比较 **975 个文件，0 个变化**，其中 **951 个原 dist 文件全部未变**；既有 checker/tests 文件未改。Git diff 检查通过。M2 core/reader/service/report_style/presentation 相对 HEAD 无差异；report.py 的新增变化为版本保护及 provenance，表格计算回归通过。

当前 v1.0.0 与历史审计所记哈希一致：

- ZIP：`768759c9961d9027d1a990e678c5581001f151ee2b54ab1c424ab425ed1517d5`
- EXE：`e232f2074f0f6dfe35ec623c96ed913c4ec570a53b098aba45f7f74183930e50`

真实原件没有被本轮工具打开或写入；只读保护由源代码审查、现有回归和合成文件哈希验证支持。项目内唯一新增交付为本报告；测试脚本、构建及证据留在上述临时目录。

## 7. 最终决策

**GO for LOCAL Git commit。** 当前已验证的 P0/P1 阻断项全部关闭；建议提交前明确纳入所需未跟踪的 M3.1 模块/测试并检查暂存差异，避免遗漏依赖或混入无关文件。此审计并未执行 commit。

**不据此批准正式部署或发布。** 在真实环境使用前完成真实资料只读抽样、Drive 挂载行为/慢速导出、目标电脑及原生缩放验收。M3.2/M4 继续保持未开始。报告完成后停止。
