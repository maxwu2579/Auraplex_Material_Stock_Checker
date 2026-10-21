# M3.1 最终独立 P0/P1 复审

日期：2026-10-14。审查对象为当前工作树中的 M3.1 源码和上一份 [M3_1_CODEX_AUDIT.md](C:/Users/25795/OneDrive/Desktop/Projects/ChatGPT/工作/MaterialRequirementChecker-M0/M3_1_CODEX_AUDIT.md)。我对照了原始四项发现、当前实现和测试，并用临时合成 Excel 注入竞态。没有修改生产代码或工作簿，没有提交、推送、发布，也没有开始 M3.2/M4。

## 结论

**NO-GO：目前不建议提交本地 Git commit。** P0-1 的原始状态读取失败场景与 P1-1 已验证修复。P0-2 的同步层修复大体有效，但我复现了 CHECK 结果与同步后文件版本不一致。另复现了同步失败日志写入失败时，界面沿用旧成功状态的 P0 缺陷。P0-3 的成功状态会说明云端未知，但错误状态没有在常驻界面显示这一限制，仍未满足要求。

| 原始发现 | 结果 | 依据 |
| --- | --- | --- |
| P0-1 状态读取失败 | **PASS** | 注入 SQLite freshness 查询错误后，面板和状态栏均降为 `Status Unknown — Database Read Failed`，旧成功时间被清除，已发布数据未改变。 |
| P0-2 源文件竞态 | **FAIL** | 同步层的多数竞态能降级、重试或保留完整历史版本；但 CHECK 先计算、同步后重试导入新文件时，UI 仍显示旧文件计算结果，同时显示本机文件已验证。 |
| P0-3 云端新鲜度 | **FAIL** | 成功状态常驻显示 `Cloud Not Verified`；`Using Previous Data`、`Source File Unavailable`、`Status Unknown` 等状态的常驻标签没有该限定语，只有详情/tooltip 有。 |
| P1-1 打包版本 | **PASS** | 缺失/错误版本及无授权的开发版均被拒绝；开发版加 `-AllowDevBuild -ValidateOnly` 通过，合成 `build`/`dist` 标记文件未变。原 v1.0.0 ZIP/EXE 哈希也未变。 |

## P0-1 — PASS：状态读取异常立即失效化

我先用合成 Storage/BOM 建立成功状态，再让 `InventorySync.freshness()` 抛出 `sqlite3.OperationalError`。结果：面板显示 `Status: Status Unknown — Database Read Failed`；状态栏也包含相同未知状态；`Last Verified` 和 `Last Checked` 均为空，不再出现先前 `Local File Checked` / `Up to Date` 标签。同步状态详情说明数据库记录仍保留。

我逐项比较了 `source_versions`、`current_sources`、库存/BOM 明细、快照、变更、质量问题和材料索引；这些表在故障前后完全相同，且 `PRAGMA integrity_check` 返回 `ok`。CHECK 结果在该路径中仍可见，但刷新操作先重新读取/计算 Excel；状态栏明确把计算状态和 `Database Read Failed` 并列。因此这次 SQLite 状态读取错误没有把旧数据库时间显示成当前验证。相关失效化逻辑见 `checker/ui.py` 的 `_show_inventory` / `_render_inventory`（约 328–350、416–423 行），回归断言在 `tests/test_m31.py` 约 789–809 行。

## 附加 P0 — 失败记录写不入 SQLite 时，旧成功状态仍会显示

我先建立成功状态，再用 `os.replace` 将合成 Storage 暂时移走，并注入 `_record_failure()` 返回 `recorded=False`（模拟失败记录因数据库写入问题无法保存）。随后 freshness 查询仍可读取旧的成功 `sync_runs`。观察到：本次同步结果为 `UNAVAILABLE, recorded=False`，状态栏显示读取失败，但面板仍为 `Status: Local File Checked — Cloud Not Verified`，Storage 行仍为 `Local File Checked`，并显示上次成功验证时间。弹窗说明“本次失败未能写入数据库记录”，但常驻成功状态没有被清除。

这与 P0-1 中直接注入 freshness 查询异常是不同故障路径：原始查询异常已正确降级；此处查询成功，却读到旧成功记录。由于 `checker/sync.py` 在无法记录失败时会返回 `recorded=False`，而 `checker/ui.py` 的 `_show_inventory()` 仍以 freshness 查询结果作为面板状态，旧 `IMPORTED/UNCHANGED` 会重新变成“本机文件已检查”。同步失败未能记入数据库时，当前 UI 必须根据本次 `SyncResult` 失效化状态，不能把旧记录当成本次验证。这违反最高优先级的新鲜度要求，是单独的提交阻断项。

## P0-2 — FAIL：同步竞态降级有效，但 CHECK 结果未绑定最终文件版本

`checker/sync.py` 现在在 `UNCHANGED` 写记录的事务内再次指纹检查，在导入事务提交前再次检查，提交后还调用 `_confirm`；`sync_all` 在把结果交给 UI 前再确认一次。合成故障注入和完整套件验证了这些同步层行为：

- 首次比较后、`UNCHANGED` 记录前改写源文件：不会保留本机匹配成功状态；允许重试时第二次导入新版本。
- 最终指纹检查后、导入提交前改写源文件：数据库只提交完整的已解析版本；提交后的确认记录 `SourceChanged`，不会把它显示为当前已验证。该版本作为历史保留，未发现部分写入；数据库写入异常测试也确认整笔 SQLite 事务回滚。
- 提交后立即改写源文件：我额外注入了这一时序。一次尝试返回 `SourceChanged`，刚提交的版本仍作为历史保存，快照及来源哈希相符；没有报告本机匹配成功。`PRAGMA integrity_check` 通过。
- Storage 在 BOM 同步过程中变化、另一实例先发布不同来源版本、临时文件不可用/损坏：结果进入失败/变更状态并保留已有数据；连续变化最多尝试 3 次。
- 连续快速点击 Refresh：额外 UI 注入中，三个忙碌期间请求被忽略，只运行一个 job。旧 job 事件不能覆盖新状态的回归测试通过。

**提交阻断的复现：CHECK 与同步顺序形成版本竞态。** UI 的 `_start` 先运行 `check()` 的 Excel 读取和计算，再在同一 worker 中运行 `_sync_sources`（`checker/ui.py` 约 625–652 行）。我在初次比较后改写合成库存：CHECK 已按库存 A=100 算出 1 条 `ENOUGH`、1 条 `SHORTAGE`，之后同步重试并把库存 A=0 导入 SQLite。最终界面仍保留 `app.stock_book` 中 A=100 的结果，却显示 `Local File Checked — Cloud Not Verified`；没有警告。源文件与 SQLite 当前值均为 0，且数据库状态确实已验证。这让旧文件计算结果看起来像是对同步后新版本的检查。

这个问题不在当前同步竞态测试中：`SourceRaceTests`（约 315 行起）直接验证 `InventorySync`，没有验证当重试读取了不同文件版本时，UI 是否丢弃或重算先前的 CHECK 结果。提交前应让计算结果携带所用 Storage/BOM 指纹，并与最终确认版本比较；不一致或同步未验证时应清除/醒目标记旧结果，或针对最终读取版本重新计算。有限的本机指纹检查只能证明某个本机文件版本在某个检查时刻匹配，不能保证文件之后不变，也不能证明 Google Drive 云端已同步。

## P0-3 — FAIL：错误状态中的云端限制只在详情中

成功状态常驻标签由 `checker/queries.py` 的 `status_text()` 限定为 `Local File Checked — Cloud Not Verified`。但 `status_text()` 只给 `LOCAL_VERIFIED` 加云端限定；`NOT_SYNCED`、`USING_PREVIOUS`、`SOURCE_UNAVAILABLE`、`SOURCE_CHANGED`、`SYNC_FAILED` 和 `STATUS_UNKNOWN` 均不带该文案。云端说明 `LOCAL_COPY_NOTE` 位于 `checker/ui.py` 的 `_inventory_details()` 中，需点击或看 tooltip 才能读到。

我在 960×600、Tk scaling 150% 的合成“源文件暂时不可用”状态中复核到：常驻面板为 `Status: Using Previous Data`，状态栏为 `Read / check failed`；Storage 行可显示 `Source File Unavailable · Using Previous Data`，时间行显示此前的 `Verified` 时间，但可见状态没有 `Cloud Not Verified`。详情文本才说明 Google Drive 云端副本未被检查。状态未知路径虽然不再显示旧时间，也没有常驻云端限制。由此，用户在错误或首次未同步状态下无法从常驻界面辨别“云端新鲜度未知”。这不再是成功标签误称已同步，但仍直接不符合本阶段规定的常驻可见性与状态区分要求。

现有自动布局测试验证了 960×600、1280×720、1366×728 与 Tk 100/125/150% scaling 模拟下，成功状态、时间和操作按钮可见（`tests/test_m31.py` 约 870 行起）。这些是 Tk 几何模拟，不是三种真实显示器/DPI 的人工验证。需将云端未知说明放到各状态都可见的常驻区域，并在相同尺寸矩阵重新检查。

## P1-1 — PASS：版本校验和 ValidateOnly 保护

`build_portable.ps1` 的 `-Version` 默认空值；脚本先要求显式版本、拒绝与 `app.py` 不一致的版本，并要求开发版本使用 `-AllowDevBuild`（约 12–27 行）。`-ValidateOnly` 在清理 `build` / `dist` 之前返回。完整套件中的 PowerShell 版本用例通过；我还在临时副本中放置现有 `build`/`dist` sentinel 文件，运行 `-Version 1.1.0.dev0 -AllowDevBuild -ValidateOnly`，退出码为 0，两个文件 SHA-256 均未变化。

我没有在项目目录运行实际构建脚本。项目 `dist` 中已有 v1.0.0 发行文件；在本次独立临时 PyInstaller 构建前后，发行 ZIP 与 EXE 的 SHA-256 相同：ZIP `768759c9961d9027d1a990e678c5581001f151ee2b54ab1c424ab425ed1517d5`；EXE `e232f2074f0f6dfe35ec623c96ed913c4ec570a53b098aba45f7f74183930e50`。

## 回归与完整性验证

- 完整命令：`.\.venv\Scripts\python.exe -m unittest discover -v`。结果：**162 tests，157 passed，5 skipped，0 failed**；5 项跳过是 Google Drive 挂载依赖测试。
- M2.1 的 `checker/core.py`、`checker/reader.py`、`checker/service.py` 和报告引擎没有工作树差异。原有测试仍在完整套件中通过。M3.1 合成 Excel/SQLite parity 用例对 18 个产品/库存表/数量组合完成比较并通过；此前报告所称 33 组真实工作簿 parity 本次未重跑。
- 合成重复 Material ID、无效/空库存、独立 Storage/BOM 同步、快照历史、相同库存不建新快照、数据库写入失败回滚、启动/重启、只读源工作簿及 UI 主线程测试均通过。合成冻结 EXE 的 onedir/windowed 构建和 `--self-test` 通过（`frozen=true`、导出成功、未变化 Refresh 未增加快照）；输入工作簿 SHA-256 前后相同。构建和输入均位于 `%TEMP%`，没有写入项目 `build`/`dist`。
- 对比结果来自本机文件的 CRC/大小等指纹；未变化时不会完整读取图片内容，变化导入时会解析工作簿并另行计算 SHA-256。UI 工作由后台线程执行、Tk 更新经主线程队列处理；连续变化重试有上限。SQLite 的 busy timeout 为 15 秒，未发现锁顺序死锁；未做多进程高负载锁竞争压测，因此极端锁竞争下等待时间仍未验证。

## 新发现与剩余限制

- **P0：** CHECK 结果可能属于较旧的本机文件版本，而 UI 已显示 SQLite 与新文件版本匹配。见 P0-2 复现。这是当前 NO-GO 的直接原因。
- **P0：** 源不可用且失败记录无法写入时，状态查询会读回旧成功记录；我复现到面板仍显示 `Local File Checked` 和旧时间。错误弹窗不足以抵消常驻成功状态。这也是当前 NO-GO 的直接原因。
- **P0：** 非成功状态没有在常驻 UI 显示 `Cloud Not Verified`。见 P0-3。
- **P2（既有风险，未在本阶段处理）：** 数据库包含库存/BOM 字段、历史及路径，默认存于 `%LOCALAPPDATA%\Auraplex\MaterialStockChecker`；代码未提供静态加密或 ACL 收紧/验证，用户也可用 `--data-dir` 指向其他位置。快照及运行记录当前没有保留期。用户提出的 12 个月快照、90 天常规日志、180 天失败日志是 M3.2 方案，本次没有实现或验证。
- 本次没有真实 Google Drive 挂载，也没有重新读取真实库存/BOM 工作簿；5 个 Drive 测试跳过。因而无法证明云端下载完成、跨设备同步，亦未重跑先前所报的 33 组真实资料 parity。真实高 DPI 屏幕和真实 Drive 文件替换时序未执行。

## 最终判定

**NO-GO for local Git commit。** 原始 P0-1 场景与 P1-1 已解决；重新审查前还须确保：CHECK 结果与最终确认的 Storage/BOM 版本保持一致；当同步失败且失败记录写入失败时，面板绝不沿用旧成功状态；所有常驻错误/未同步状态明确显示云端新鲜度未知。本报告完成后停止；没有进入 M3.2/M4。
