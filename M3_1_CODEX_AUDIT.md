# M3.1 Independent Code & Data Integrity Audit

日期：2026-10-14。审计对象：当前工作区中的 M3.1 源码、测试和构建配置。范围限于只读审查；没有修改生产代码、源 Excel、提交、推送或发布。本报告文件是本次唯一交付。

## 结论

**M3.1 目前不适合提交。** 有 P0：在可复现的失败和竞态下，界面/SQLite 会把旧数据报告成 `Up to Date`。这违反了“同步失败或云端新鲜度未验证时，不得声称缓存库存为当前数据”的要求。当前 M3.1 的 CHECK 仍从成功读取的 Excel 计算，代码没有在 Excel 读取失败后自动改用 SQLite 计算；这降低了当前误用风险，但不能消除数据库状态错误，也不能证明 Google Drive 云端副本新鲜。

## 本次独立验证

| 检查 | 结果 |
| --- | --- |
| 完整现有测试套件 | **149 项：144 通过、5 跳过**；跳过的是需要本机 Google Drive 挂载的条件测试 |
| M3.1 测试 | 39 项均通过；包含事务失败回滚、双角色同步、重复/无效值、启动、只读查询、UI 主线程和合成 parity 检查 |
| M2.1 回归 | 原有 110 项均通过；M2.1 计算、筛选和导出结构的既有断言仍通过 |
| 竞态故障注入 | **两种源文件变化竞态均复现为错误的成功状态**，详见 P0-2 |
| 状态读取故障注入 | **复现面板和状态栏仍显示旧的 `Up to Date`**，详见 P0-1 |
| PyInstaller 独立构建 | 在 `%TEMP%` 以项目现有 Python 3.12.10 / PyInstaller 6.22.3 按 onedir/windowed 构建当前源码，未改动项目 `build/` 或 `dist/` |
| 冻结 EXE 自测 | PASS：`frozen=true`，模块来自 `_internal`，临时 SQLite 数据库建成，合成 BOM 成功计算、导出和 Refresh；刷新没有增加快照。另以 `--smoke-test --data-dir` 启动通过 |
| 真实资料 | 本次未重新打开资料库中的真实工作簿。实现报告所述 33 项真实 Excel/SQLite parity 及哈希核对属于先前报告结果；本次只独立运行合成测试中的 parity 检查 |

回归命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

本次运行记录为 `Ran 149 tests in 29.051s; OK (skipped=5)`。所有故障注入和冻结 EXE 输入均为新建的合成文件，放在 `%TEMP%` 临时目录，不涉及真实资料。`audit_test_run.txt` 保留了本次完整测试输出；独立打包与合成输入目录位于 `%TEMP%\MRC_M31_Audit_759625236e9142d186aaa94379f72e02`。Google Drive 实际挂载、云端下载完成状态及第二台电脑仍未验证。

## P0 — 提交阻断项

### P0-1：freshness 查询失败后，UI 保留并继续显示旧的成功状态

在 [checker/ui.py](checker/ui.py) 的 `_sync_sources` 中，`freshness()` 失败会返回 `(results, None, error)`；`_show_inventory` 仅在 `roles is not None` 时更新 `inventory_roles`。因此 `None` 不会清除或降级上一次内存中的状态。随后 `_render_inventory` 继续绘制旧状态，而 `_poll` 又把 `self.db_status` 追加到状态栏。

我先用合成 Storage/BOM 建立成功状态，然后注入 `InventorySync.freshness()` 的 SQLite 读取异常。观察结果：面板仍为 `Status: Up to Date`；状态栏仍为 `Inventory Database: Up to Date`；另有警告提示“状态读取失败”。即使有警告，主要状态仍给出相反结论，不能满足 fail-closed 要求。

**建议修复**：任何无法读取同步状态或数据库的路径都立即把主状态设为 `Status Unknown / Database Unavailable`，清除成功标记，并禁止把旧值拼入状态栏。只有本次新鲜度检查本身成功，才能显示本次检查结果；旧数据存在时单独标记 `Using Previous Data` 和最后成功时间。

### P0-2：成功同步缺少覆盖整个发布窗口的源文件一致性保证

在 [checker/sync.py](checker/sync.py) 的 `sync_role`：

- **未变化分支（约 138–140 行）**：读取一次 `fingerprint`，与当前版本签名相同后直接调用 `_record_unchanged`。记录成功前没有再次确认文件仍是同一版本。
- **导入分支（约 250–255 行）**：在事务中做最后一次 `fingerprint`，随后再插入成功 `sync_runs` 并提交。最后指纹与 COMMIT 之间仍有窗口。

我用临时合成 Storage 在这两个窗口分别改写数量，观察到：

| 注入位置 | 同步返回 | SQLite 当前数量 | 源文件数量 | Freshness |
| --- | --- | ---: | ---: | --- |
| 初次 fingerprint 之后、UNCHANGED 记录之前 | `UNCHANGED` | 10 | 99 | `Up to Date` |
| 导入分支最终 fingerprint 之后、COMMIT 之前 | `IMPORTED` | 11 | 99 | `Up to Date` |

现有测试覆盖了解析期间变化和最终 fingerprint 检查当场发现变化；没有覆盖 fingerprint 返回后、成功记录/COMMIT 前的竞态。后者因此能绕过现有回滚路径。

**建议修复**：未变化分支也必须对成功记录前后的源指纹做一致性验证；导入分支必须把变化确认纳入事务提交判定，并在确认失败时整笔回滚。由于 Excel / Drive 文件无法由本程序可靠加锁，即使增加重检也不能证明此后文件永不变化；状态与文案应表达“在某时刻匹配到本机文件”，不能承诺持续 `Up to Date`。文件变化竞态或验证错误必须让状态退回未知/失败并要求刷新。

### P0-3：Drive 云端新鲜度未知时，主界面仍显示无条件 `Up to Date`

实现已明确承认无法知道 Google Drive 是否已下载新云端版本：[checker/ui.py](checker/ui.py) 的 `LOCAL_COPY_NOTE` 说明此限制，但该说明只出现在悬停提示/点击详情中。常驻主状态由 [checker/queries.py](checker/queries.py) 最近一次 `IMPORTED` / `UNCHANGED` 结果生成 `Up to Date`。因此用户只看主界面时会看到成功状态，而程序从未验证云端新鲜度。

当前没有缓存数据库回退计算，这一点通过 `check()` 必须取得 `stock_book` 和 `bom_book` 的流程确认；但 M3.1 已把 SQLite 作为历史镜像公开展示，且 M3.2 计划从中提供数据。按本任务的 P0 门槛，悬停中的限定语不足以抵消常驻成功标签。

**建议修复**：常驻状态应写明“本机文件最近于某时刻与 SQLite 匹配；Google Drive 云端状态未知”，将“本机副本匹配”与“云端已同步”分开。云端未验证时不显示无条件 `Up to Date`。任何未来基于缓存的计算必须显式 opt-in、醒目标 `UNVERIFIED`，且同步失败时默认阻止计算。

## P1 — 提交前应处理

### P1-1：便携包脚本默认版本落后于当前应用版本

[app.py](app.py) 声明 `VERSION = 1.1.0.dev0`，但 [build_portable.ps1](build_portable.ps1) 默认 `$Version = '1.0.0'`。直接按默认参数执行将产生标为 v1.0.0 的新便携 ZIP，容易把 M3.1 冒充旧版。当前独立 EXE 构建证明冻结运行兼容性，不证明现有发行脚本的版本选择正确。

**建议**：发布前要求显式传入版本，并在脚本中验证与应用版本一致；M3.1 仍标记为开发版，不应生成正式发行包。该脚本会清理项目 `build/` 和 `dist/`，本次没有运行它。

## P2 — 维护 / 部署风险

### P2-1：SQLite 历史与运行记录没有保留期

当前每个 Storage 新版本都会保留快照，每次同步检查都会新增 `sync_runs`；没有清理策略。这符合本次不实现 M3.2 的边界，但长期会增长。按后续提议实现 12 个月库存快照、90 天常规运行记录、180 天失败记录时，必须保留最新成功快照和趋势基线；清理不能破坏外键、来源版本和历史查询。

### P2-2：本地数据没有应用层静态加密或 ACL 检查

默认位置 [checker/appdata.py](checker/appdata.py) 是 `%LOCALAPPDATA%\Auraplex\MaterialStockChecker`，优于项目目录、临时解包目录和 Drive 同步目录；SQLite 查询接口使用只读 URI，现有测试也验证只读连接不能写入。不过数据库和 `settings.json` 未加密，程序没有检查/收紧目录 ACL。自定义 `--data-dir` 也可将文件放到其他位置。

**建议**：部署说明明确其中保存了库存/BOM 原始字段、文件路径和历史；由 Windows 用户配置文件 ACL / 设备加密保护，并明确禁止把 `--data-dir` 指向 Google Drive、OneDrive 或网络共享，除非另外验证 SQLite 锁和权限行为。

## 其他焦点结论

| 范围 | 独立审查结论 |
| --- | --- |
| Excel → SQLite 同步 | Storage / BOM 按角色独立版本和发布；签名命中走无解析的 UNCHANGED；变化才解析和写入。正常路径清晰，但 P0-2 表明不能保证检查与发布间源文件未变化。签名为 ZIP 成员 CRC/大小派生值，是缓存失效指标，不是密码学数据验证。 |
| 原子事务 / 回滚 | `BEGIN IMMEDIATE` 包含版本行、原始记录、质量问题、快照、当前指针和同步成功记录；异常时显式 ROLLBACK。完整套件的写入故障注入通过。失败日志单独写入；日志写入失败会由 `recorded=false` 反映。 |
| 重复 Material ID / 无效库存 | 重复行逐条保存并标记，不求和；数值型编号不转成文本匹配键。数量原始类型和值保留，空白/文本/公式错误/负库存不会成为可信数量。合成 parity 检查通过。 |
| Storage / BOM 独立同步 | current pointer、版本和状态均按 role；单一角色失败不阻止另一角色导入。BOM 变化不产生库存快照。相关单元测试通过。 |
| 首次启动 / 后续启动 | 首次运行需要用户选文件，成功读取后才记路径；再次启动异步读取记忆路径，未变化时不重复解析或生成快照。失败文件不被记为已成功加载。 |
| Drive 不可用 / 旧缓存 | 来源不可用会在同步记录中标为 `UNAVAILABLE`，旧数据库版本仍保留并标 `Using Previous Data`；Excel 读取失败时当前 CHECK 不会自动从数据库回退。**状态读取异常保留旧 Up to Date 的 P0-1 是例外缺陷。** |
| 快照历史 / 无重复快照 | 每个成功导入的 Storage `source_version_id` 至多一个 snapshot（唯一约束）；UNCHANGED 不建新版本/快照。差异以 `(Sheet, normalized text key)` 比较；净变动只在前后均为单条有效数量时计算，重复、缺失和有效性变化作为中断，不称为消耗。 |
| M2.1 计算与报告回归 | 所有既有 110 项测试通过，M2 核心和导出数据断言仍在。M3.1 的合成 parity 测试通过；真实 33 组合未在本次用资料库原件重跑。 |
| UI 尺寸 / 后台线程 | 套件覆盖 960×600、1280×720、1366×728 与 100/125/150% Tk scaling，并断言操作可见、表格高度大于 60 px；状态更新经队列回到 Tk 主线程。自动几何检查通过；实际高 DPI 设备、真实 Drive 状态和人工交互未复核。 |
| PyInstaller standalone | 本次用当前源码在临时目录构建并运行合成自测，数据库与双工作簿流程可运行；`_sqlite3.pyd` / `sqlite3.dll` 均被打包。发行脚本的版本问题见 P1-1。 |

## Commit 判定

**NO-GO：修复并复审所有 P0 后再提交。** 最小复审门槛：失败读取 freshness 时状态必须降级；覆盖 UNCHANGED 和导入提交边界的源改写注入测试必须证明不会返回/显示成功；常驻状态必须清楚限定为本机文件上次匹配时间并明确云端未知。此结论不要求在本次范围内修复；用户明确要求只审计，不改生产代码。

本次开始前工作区已有 M3.1 源码、UI、README 和测试变更。审计只增加本报告；未 commit / push / release，未实现 M3.2 或 M4。
