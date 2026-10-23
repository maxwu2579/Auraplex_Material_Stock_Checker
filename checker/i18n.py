"""Interface language for the main window (B1). One shared resource and one state object; no scattered conditionals.

Three separate languages exist in the program and are never merged:
- interface language (this module): labels, buttons, headings, state glosses and dialog titles of the main window;
- assistant reply language (checker.assistant_language.route): per question, mixed-language rules unchanged;
- report output language (checker.report_delivery): fixed when a report is submitted.

Never translated: Material IDs, source file names, original Sheet names, units, status/result codes (SHORTAGE,
EXCEPTION, ENOUGH, UNVERIFIED, alert type codes) and "Cloud Not Verified". English strings equal the earlier
interface text, so English behaviour is unchanged.
"""
from __future__ import annotations

LANGUAGES = ("en", "zh", "ms")
SHORT_NAMES = {"zh": "中文", "en": "EN", "ms": "BM"}

S = {
    # shell
    "app_title": ("Material Requirement & Stock Checker", "物料需求与库存检查器", "Pemeriksa Keperluan Bahan & Stok"),
    "brand_sub": ("Local · Cloud Not Verified", "本地 · Cloud Not Verified", "Setempat · Cloud Not Verified"),
    "nav_home": ("Stock overview & alerts", "库存概览与提醒", "Gambaran stok & amaran"),
    "nav_check": ("Product shortage check", "产品缺料检查", "Semakan kekurangan produk"),
    "nav_materials": ("Materials & history", "材料与历史", "Bahan & sejarah"),
    "nav_alerts": ("Alerts", "提醒", "Amaran"),
    "nav_daily": ("Daily summary", "日报", "Ringkasan harian"),
    "nav_ai": ("AI reports", "AI 报告", "Laporan AI"),
    "nav_settings": ("Settings", "设置", "Tetapan"),
    "collapse": ("Collapse navigation", "收起导航", "Kuncup navigasi"),
    "expand": ("Expand navigation", "展开导航", "Kembangkan navigasi"),
    "language": ("Interface language", "界面语言", "Bahasa antara muka"),
    "lang_note": ("Interface language only. Assistant replies keep their own language rules; a report keeps the "
                  "language it was saved in.",
                  "只切换界面语言。助手回答沿用其语言规则；报告保持保存时的语言。",
                  "Bahasa antara muka sahaja. Jawapan pembantu mengikut peraturan bahasanya; laporan kekal dalam "
                  "bahasa semasa disimpan."),
    "refresh": ("Refresh Excel", "刷新 Excel", "Muat semula Excel"),
    "reload": ("Reload Files", "重新读取文件", "Baca semula fail"),
    "db_title": ("Inventory Database", "库存数据库", "Pangkalan data inventori"),
    "status_prefix": ("Status", "状态", "Status"),
    "last_verified": ("Last Verified", "最后核对", "Pengesahan terakhir"),
    "previously_verified": ("Previously Verified", "此前核对（历史）", "Pernah disahkan (sejarah)"),
    "last_checked": ("Last Checked", "最后检查", "Semakan terakhir"),
    "db_unavailable_times": ("Excel checks still work; nothing is stored locally. Click for details.",
                             "Excel 检查仍可使用；不在本地保存任何数据。点击查看详情。",
                             "Semakan Excel masih berfungsi; tiada apa disimpan setempat. Klik untuk butiran."),
    "click_details": ("Click for details.", "点击查看详情。", "Klik untuk butiran."),
    "verification_required": ("Verification Required", "需人工核对", "Perlu pengesahan"),
    # check page (static)
    "storage_file": ("Storage File", "Storage 库存文件", "Fail Storage"),
    "bom_file": ("BOM File", "BOM 文件", "Fail BOM"),
    "browse": ("Browse…", "选择…", "Pilih…"),
    "change": ("Change…", "更换…", "Tukar…"),
    "choose_workbook": ("Choose an Excel workbook", "请选择 Excel 工作簿", "Pilih buku kerja Excel"),
    "product_id": ("Product ID", "产品编号", "ID produk"),
    "quantity": ("Quantity", "生产数量", "Kuantiti"),
    "check_button": ("CHECK MATERIALS", "CHECK 试算", "CHECK BAHAN"),
    "export_button": ("EXPORT EXCEL", "导出 Excel", "EKSPORT EXCEL"),
    "storage_sheet": ("Storage Sheet", "Storage Sheet", "Sheet Storage"),
    "use_cache": ("Use Cached Data…", "使用缓存数据…", "Guna data cache…"),
    "results_title": ("Material Results", "材料结果", "Keputusan bahan"),
    "filter_all": ("All", "全部", "Semua"),
    "filter_shortage": ("Shortage", "缺料", "Kekurangan"),
    "filter_exception": ("Exceptions", "异常", "Pengecualian"),
    "filter_enough": ("Enough", "足够", "Mencukupi"),
    "col_code": ("Material ID", "材料编号", "ID bahan"),
    "col_description": ("Description", "描述", "Penerangan"),
    "col_required": ("Required", "试算需求", "Diperlukan"),
    "col_stock": ("Stock", "库存", "Stok"),
    "col_shortage": ("Shortage", "试算缺口", "Kekurangan"),
    "col_result": ("Result", "结果代码", "Kod keputusan"),
    "col_status": ("Data Status", "数据状态", "Status data"),
    "col_rack": ("Rack", "Rack", "Rak"),
    "col_level": ("Level", "Level", "Aras"),
    "detail_title": ("Selected Material · Source & Data", "所选材料 · 来源与数据", "Bahan dipilih · Sumber & data"),
    "close_details": ("Close details", "关闭详情", "Tutup butiran"),
    "open_folder": ("Open Folder", "打开文件夹", "Buka folder"),
    "dismiss": ("Dismiss", "关闭", "Tutup"),
    "notice": ("Results are calculated from the selected BOM and current saved Storage data.",
               "结果按所选 BOM 和当前已保存的 Storage 数据试算。",
               "Keputusan dikira daripada BOM dipilih dan data Storage yang disimpan."),
    "trial_note": ("Trial calculation for the selected file versions: not production approval, no automatic purchasing.",
                   "按所选文件版本的试算：不代表可以生产，不会自动采购。",
                   "Pengiraan percubaan bagi versi fail dipilih: bukan kelulusan pengeluaran, tiada pembelian automatik."),
    # home
    "quick_check": ("Product shortage check", "产品缺料检查", "Semakan kekurangan produk"),
    "quick_hint": ("Pick an existing Product ID from the list, enter a whole quantity, then CHECK. Partial text "
                   "cannot be checked.",
                   "从列表中选择实际存在的产品编号，输入正整数数量后 CHECK。只输入部分文字不能试算。",
                   "Pilih ID produk yang wujud daripada senarai, masukkan kuantiti nombor bulat, kemudian CHECK. Teks "
                   "separa tidak boleh disemak."),
    "no_product_yet": ("No product and quantity checked yet: product shortage cannot be judged.",
                       "尚未选择产品和数量进行试算：无法判断产品是否缺料。",
                       "Belum ada produk dan kuantiti disemak: kekurangan produk tidak dapat dinilai."),
    "last_check": ("Last trial check", "最近一次试算", "Semakan percubaan terakhir"),
    "last_none": ("No trial check in this session yet.", "本次会话尚无试算。", "Belum ada semakan percubaan dalam sesi ini."),
    "checked_at": ("Checked at", "试算时间", "Disemak pada"),
    "basis": ("Basis", "数据依据", "Asas"),
    "state_bound": ("bound to the local file versions confirmed at {time} (Cloud Not Verified).",
                    "与 {time} 确认的本地文件版本绑定（Cloud Not Verified）。",
                    "terikat pada versi fail setempat yang disahkan pada {time} (Cloud Not Verified)."),
    "state_cached": ("Historical cached data · UNVERIFIED.", "历史缓存数据 · UNVERIFIED。", "Data cache sejarah · UNVERIFIED."),
    "state_outdated": ("OUTDATED / RECHECK REQUIRED: a source changed after this check.",
                       "OUTDATED / RECHECK REQUIRED：检查后源文件已变化。",
                       "OUTDATED / RECHECK REQUIRED: sumber berubah selepas semakan ini."),
    "state_recheck": ("No longer shown as current (inputs, files or data changed, or a refresh/failure happened). "
                      "CHECK again.",
                      "已不再作为当前结果（输入、文件或数据已变化，或发生刷新/失败）。请重新 CHECK。",
                      "Tidak lagi dipapar sebagai semasa (input, fail atau data berubah, atau berlaku muat semula/"
                      "kegagalan). CHECK semula."),
    "open_result": ("Open result", "打开结果", "Buka keputusan"),
    "check_again": ("Check again", "重新检查", "Semak semula"),
    "alerts_title": ("Stock alerts (from synchronised data)", "库存提醒（来自已同步数据）", "Amaran stok (daripada data diselaraskan)"),
    "open_alerts": ("Open Stock Alerts…", "打开库存提醒…", "Buka amaran stok…"),
    "clear_filter": ("Show all", "显示全部", "Papar semua"),
    "tile_zero": ("Zero stock", "零库存", "Stok sifar"),
    "tile_low": ("Below minimum", "低于最低库存", "Bawah minimum"),
    "tile_blank": ("Stock not recorded (blank)", "库存未登记（空白）", "Stok tidak direkod (kosong)"),
    "tile_invalid": ("Quantity to confirm (text)", "数量待确认（文本）", "Kuantiti perlu disahkan (teks)"),
    "tile_dup": ("Duplicate ID", "重复编号", "ID pendua"),
    "tile_missing": ("BOM material not in stock list", "BOM 材料未在库存找到", "Bahan BOM tiada dalam senarai stok"),
    "tile_threshold": ("Threshold not configured", "阈值未配置", "Ambang tidak dikonfigurasi"),
    "tile_other": ("Other data issues", "其他数据问题", "Isu data lain"),
    "alerts_unknown": ("unknown", "未知", "tidak diketahui"),
    "alerts_loading": ("Loading stored alerts…", "正在读取已存提醒…", "Membaca amaran tersimpan…"),
    "alerts_no_db": ("Alerts are unavailable: no readable local database. Excel CHECK still works.",
                     "提醒不可用：没有可读取的本地数据库。Excel CHECK 仍可使用。",
                     "Amaran tidak tersedia: tiada pangkalan data setempat yang boleh dibaca. CHECK Excel masih berfungsi."),
    "alerts_upgrade": ("Alerts need the one-time local database upgrade (Settings or Stock Alerts window). Counts are "
                       "unknown, not 0.",
                       "提醒需要先完成一次本地数据库升级（设置或库存提醒窗口）。计数未知，不是 0。",
                       "Amaran perlukan naik taraf pangkalan data sekali (Tetapan atau tetingkap Amaran). Kiraan tidak "
                       "diketahui, bukan 0."),
    "alerts_read_failed": ("Alerts could not be read: counts are unknown, not 0. Nothing was deleted.",
                           "无法读取提醒：计数未知，不是 0。没有删除任何数据。",
                           "Amaran tidak dapat dibaca: kiraan tidak diketahui, bukan 0. Tiada apa dipadam."),
    "alerts_not_evaluated": ("The current files have no verified alert evaluation yet: counts are unknown, not 0.",
                             "当前文件尚未有经核对的提醒评估：计数未知，不是 0。",
                             "Fail semasa belum ada penilaian amaran disahkan: kiraan tidak diketahui, bukan 0."),
    "alerts_overlap": ("{n} alerts across {m} materials. One material can be in several categories, so category counts "
                       "do not add up to materials.",
                       "共 {n} 条提醒，涉及 {m} 种材料。同一材料可属于多个类别，类别数相加不等于材料数。",
                       "{n} amaran merangkumi {m} bahan. Satu bahan boleh dalam beberapa kategori, jadi jumlah kategori "
                       "bukan bilangan bahan."),
    "alerts_overlap_partial": ("{n} alerts; only {k} loaded here, so the number of distinct materials is not shown. "
                               "Open Stock Alerts for all rows.",
                               "共 {n} 条提醒；此处只读取了 {k} 条，因此不显示不同材料数。完整列表请打开库存提醒窗口。",
                               "{n} amaran; hanya {k} dimuatkan di sini, jadi bilangan bahan berbeza tidak dipapar. Buka "
                               "Amaran Stok untuk semua baris."),
    "alerts_none": ("No active alerts of these types in the last verified evaluation. This does not mean stock is "
                    "sufficient.",
                    "上次经核对的评估中没有这些类型的有效提醒。这不代表库存充足。",
                    "Tiada amaran aktif jenis ini dalam penilaian disahkan terakhir. Ini tidak bermaksud stok mencukupi."),
    "alerts_rechecked": ("Re-checked in this session.", "本次会话已重新核对。", "Disemak semula dalam sesi ini."),
    "alerts_stored": ("Stored results, not re-checked in this session.", "已存结果，本次会话尚未重新核对。",
                      "Keputusan tersimpan, belum disemak semula dalam sesi ini."),
    "alerts_threshold_note": ("Thresholds and units pending business confirmation.", "阈值和单位待业务确认。",
                              "Ambang dan unit menunggu pengesahan perniagaan."),
    "col_type": ("Type", "类型代码", "Kod jenis"),
    "col_issue": ("Issue", "问题", "Isu"),
    "col_sheet": ("Storage Sheet", "Storage Sheet", "Sheet Storage"),
    "col_rows": ("Row(s)", "行", "Baris"),
    "col_threshold": ("Threshold (raw)", "阈值（原值）", "Ambang (asal)"),
    "col_note": ("Note", "说明", "Nota"),
    "col_raw_stock": ("LIVE STOCK (raw)", "LIVE STOCK（原值）", "LIVE STOCK (asal)"),
    "col_subtype": ("Subtype", "子类型代码", "Kod subjenis"),
    "col_alert_status": ("Alert status", "提醒状态", "Status amaran"),
    "source_modified": ("Source File Modified", "源文件修改时间", "Fail sumber diubah"),
    "card_loaded": ("Loaded · Saved {saved} · Loaded {loaded}", "已加载 · 保存于 {saved} · 读取于 {loaded}",
                    "Dimuatkan · Disimpan {saved} · Dibaca {loaded}"),
    "card_loading": ("Loading…", "读取中…", "Membaca…"),
    "card_failed": ("Load failed · Click for details", "读取失败 · 点击查看详情", "Gagal dibaca · Klik untuk butiran"),
    "card_not_loaded": ("Not loaded", "未加载", "Belum dimuatkan"),
    "card_locked": ("File may currently be open in Excel", "文件可能正在 Excel 中打开", "Fail mungkin sedang dibuka dalam Excel"),
    "title_input": ("Input needs correction", "输入待修正", "Input perlu dibetulkan"),
    "title_failed": ("Read / check failed", "读取/检查失败", "Baca / semakan gagal"),
    "title_no_export": ("Nothing to export", "没有可导出的结果", "Tiada untuk dieksport"),
    "title_changed": ("Result changed", "结果已变化", "Keputusan berubah"),
    "title_export_failed": ("Export failed", "导出失败", "Eksport gagal"),
    "title_no_files": ("No files selected", "未选择文件", "Tiada fail dipilih"),
    "title_choose_stock": ("Choose the Storage Excel", "选择库存 Excel", "Pilih Excel Storage"),
    "title_choose_bom": ("Choose the BOM Excel", "选择 BOM Excel", "Pilih Excel BOM"),
    "title_export": ("Export as a new Excel report", "导出为新的 Excel 报告", "Eksport sebagai laporan Excel baharu"),
    "sources": ("Data sources", "数据来源", "Sumber data"),
    "not_selected": ("Not selected", "未选择", "Belum dipilih"),
    # state glosses (the canonical state text is kept in English in details and tests)
    "banner_ok": ("Local File Checked only means the database matched these local file versions at the time shown; "
                  "the files can change afterwards.",
                  "“本地文件已核对”只表示在所示时间数据库与这些本地文件版本一致；之后文件可能已变化。",
                  "“Fail setempat disemak” hanya bermaksud pangkalan data sepadan dengan versi fail setempat pada masa "
                  "dipapar; fail mungkin berubah selepas itu."),
    "banner_previous": ("Previous data is shown, not current data. Refresh Excel when the files are available.",
                        "显示的是旧数据，不是当前数据。文件可用后请刷新 Excel。",
                        "Data lama dipapar, bukan data semasa. Muat semula Excel apabila fail tersedia."),
    "banner_unknown": ("The database status could not be read: nothing is shown as current.",
                       "无法读取数据库状态：不会把任何内容显示为当前。",
                       "Status pangkalan data tidak dapat dibaca: tiada apa dipapar sebagai semasa."),
    "banner_failed": ("A synchronisation failed or a source changed: nothing from it is shown as current. Fix the file, "
                      "then Refresh Excel.",
                      "同步失败或源文件已变化：不会把它显示为当前数据。修正文件后请刷新 Excel。",
                      "Penyegerakan gagal atau sumber berubah: tiada apa daripadanya dipapar sebagai semasa. Betulkan "
                      "fail, kemudian Muat semula Excel."),
    "banner_no_db": ("No local database: Excel CHECK works; alerts, history and reports are unavailable.",
                     "没有本地数据库：Excel CHECK 可用；提醒、历史和报告不可用。",
                     "Tiada pangkalan data setempat: CHECK Excel berfungsi; amaran, sejarah dan laporan tidak tersedia."),
    "banner_cache": ("Historical cached data was explicitly authorised for this session: results and exports are "
                     "UNVERIFIED.",
                     "本次会话已明确授权使用历史缓存数据：结果和导出均为 UNVERIFIED。",
                     "Data cache sejarah dibenarkan secara jelas untuk sesi ini: keputusan dan eksport UNVERIFIED."),
    "banner_not_synced": ("No file has been checked yet. Choose the Storage and BOM files.",
                          "尚未检查任何文件。请选择 Storage 和 BOM 文件。",
                          "Belum ada fail disemak. Pilih fail Storage dan BOM."),
    "banner_checking": ("Checking the Excel files…", "正在检查 Excel 文件…", "Menyemak fail Excel…"),
    # launcher pages
    "materials_intro": ("Read-only historical observations of synchronised Storage versions. Observed Change ≠ Actual "
                        "Consumption.",
                        "已同步 Storage 版本的只读历史观察。Observed Change ≠ Actual Consumption。",
                        "Pemerhatian sejarah baca sahaja bagi versi Storage diselaraskan. Observed Change ≠ Actual "
                        "Consumption."),
    "open_history": ("Inventory History…", "库存历史…", "Sejarah inventori…"),
    "open_analytics": ("Analytics…", "库存分析…", "Analitik…"),
    "alerts_intro": ("Stored alerts of the current files, with every row and its raw values.",
                     "当前文件的已存提醒，包含每一行及其原始值。",
                     "Amaran tersimpan bagi fail semasa, dengan setiap baris dan nilai asalnya."),
    "daily_intro": ("Generate, preview and save a read-only daily stock summary (HTML + JSON).",
                    "生成、预览并保存只读的每日库存汇总（HTML + JSON）。",
                    "Jana, pratonton dan simpan ringkasan stok harian baca sahaja (HTML + JSON)."),
    "open_daily": ("Daily Summary…", "每日汇总…", "Ringkasan harian…"),
    "ai_intro": ("AI reports live in the assistant: local aggregate preview first; anything sent needs separate "
                 "consent. Reports can be saved as HTML + JSON and as a local e-mail draft (never sent).",
                 "AI 报告在助手中：先生成本地汇总预览；任何外发都需单独授权。报告可保存为 HTML + JSON，也可生成本地邮件草稿（不会发送）。",
                 "Laporan AI dalam pembantu: pratonton agregat setempat dahulu; apa-apa yang dihantar perlukan izin "
                 "berasingan. Laporan boleh disimpan sebagai HTML + JSON dan draf e-mel setempat (tidak dihantar)."),
    "open_ai": ("Open assistant · AI reports", "打开助手 · AI 报告", "Buka pembantu · Laporan AI"),
    "settings_files": ("Source files", "源文件", "Fail sumber"),
    "settings_maintenance": ("Local data maintenance", "本地数据维护", "Penyelenggaraan data setempat"),
    "local_history": ("Local History…", "历史清理…", "Sejarah setempat…"),
    "db_upgrade": ("Upgrade database…", "升级数据库…", "Naik taraf pangkalan data…"),
    "cache_intro": ("Historical cached calculations need explicit consent each session and are always UNVERIFIED.",
                    "历史缓存试算每次会话都需明确授权，结果始终为 UNVERIFIED。",
                    "Pengiraan cache sejarah perlukan izin jelas setiap sesi dan sentiasa UNVERIFIED."),
    "needs_db": ("A readable local database is required.", "需要可读取的本地数据库。",
                 "Pangkalan data setempat yang boleh dibaca diperlukan."),
    "not_covered": ("Opens in its own window (English interface in this version).",
                    "在独立窗口中打开（本版本该窗口仍为英文界面）。",
                    "Dibuka dalam tetingkap sendiri (antara muka Inggeris dalam versi ini)."),
}

# Canonical state text (checker.sync constants) -> gloss. English returns the canonical text unchanged.
STATES = {
    "Local File Checked": ("本地文件已核对", "Fail setempat disemak"),
    "Sync Failed": ("同步失败", "Penyegerakan gagal"),
    "Using Previous Data": ("使用旧数据", "Guna data lama"),
    "Source File Unavailable": ("源文件不可用", "Fail sumber tiada"),
    "Not Synced": ("未同步", "Belum diselaraskan"),
    "Source Changed — Refresh Needed": ("源文件已变化，需要刷新", "Sumber berubah — perlu muat semula"),
    "Status Unknown — Database Read Failed": ("状态未知：数据库读取失败", "Status tidak diketahui — bacaan pangkalan data gagal"),
    "Database Unavailable": ("数据库不可用", "Pangkalan data tidak tersedia"),
    "Checking": ("检查中", "Menyemak"),
    "Syncing": ("同步中", "Menyelaras"),
}


class LanguageState:
    """The interface language and its listeners (UI thread only)."""

    def __init__(self, language="en"):
        self.language = language if language in LANGUAGES else "en"
        self._listeners = []

    def subscribe(self, callback):
        self._listeners.append(callback)

    def set(self, language):
        if language not in LANGUAGES or language == self.language:
            return False
        self.language = language
        for callback in list(self._listeners):
            callback(language)
        return True


def tr(key, language="en", **values):
    text = S[key][LANGUAGES.index(language)]
    return text.format(**values) if values else text


def state_text(state, language="en"):
    """A display state such as 'Sync Failed · Using Previous Data' in the interface language."""
    if language == "en" or not state:
        return state
    index = LANGUAGES.index(language) - 1
    return " · ".join(STATES[part][index] if part in STATES else part for part in str(state).split(" · "))


# ---------------------------------------------------------------------- messages (dialogs and the status bar)
# English is exactly the earlier text. Chinese keeps the earlier Chinese wording where there was one. Values passed
# in are shown as given: error details from exceptions, file names, paths, codes (OUTDATED, UNVERIFIED, cached label,
# Cloud Not Verified) and numbers are never translated.
M = {
    # status bar: jobs
    "st_ready": ("Ready · Choose Storage and BOM files.", "就绪 · 请选择 Storage 和 BOM 文件。",
                 "Sedia · Pilih fail Storage dan BOM."),
    "st_loading": ("Loading files…", "正在读取文件…", "Membaca fail…"),
    "st_checking_materials": ("Checking materials…", "正在检查材料…", "Menyemak bahan…"),
    "st_checking_sources": ("Checking Excel sources…", "正在检查 Excel 源文件…", "Menyemak sumber Excel…"),
    "st_refreshing": ("Refreshing Excel…", "正在刷新 Excel…", "Memuat semula Excel…"),
    "st_cleanup_preview": ("Preparing local cleanup preview…", "正在准备本地清理预览…",
                           "Menyediakan pratonton pembersihan setempat…"),
    "st_cleanup": ("Backing up and cleaning local history…", "正在备份并清理本地历史…",
                   "Membuat sandaran dan membersihkan sejarah setempat…"),
    "st_upgrade_preview": ("Preparing database upgrade preview…", "正在准备数据库升级预览…",
                           "Menyediakan pratonton naik taraf pangkalan data…"),
    "st_upgrade": ("Backing up and upgrading local database…", "正在备份并升级本地数据库…",
                   "Membuat sandaran dan menaik taraf pangkalan data setempat…"),
    # status bar: outcomes
    "st_checked": ("Checked {count} materials in {seconds}s · Local Sources Verified",
                   "已检查 {count} 种材料，用时 {seconds} 秒 · Local Sources Verified",
                   "{count} bahan disemak dalam {seconds}s · Local Sources Verified"),
    "st_loaded": ("Loaded {materials} storage rows · {products} products",
                  "已读取 {materials} 行库存 · {products} 个产品", "{materials} baris stok · {products} produk dibaca"),
    "st_outdated_during_check": ("{outdated} · the source changed while being checked ({attempts} attempts); export "
                                 "disabled. Click CHECK again.",
                                 "{outdated} · 检查期间源文件发生变化（尝试 {attempts} 次）；已禁止导出。请重新 CHECK。",
                                 "{outdated} · sumber berubah semasa disemak ({attempts} percubaan); eksport dilumpuhkan. "
                                 "Klik CHECK semula."),
    "st_cache_mode": ("{label} · Cloud Not Verified · Historical data only",
                      "{label} · Cloud Not Verified · 仅历史数据", "{label} · Cloud Not Verified · Data sejarah sahaja"),
    "st_maintenance": ("{message} · {cloud}", "{message} · {cloud}", "{message} · {cloud}"),
    "st_cleanup_done": ("Local history cleanup completed", "本地历史清理已完成", "Pembersihan sejarah setempat selesai"),
    "st_nothing_expired": ("Nothing expired", "没有过期记录", "Tiada yang tamat tempoh"),
    "st_cleanup_preview_only": ("Cleanup preview only; no data deleted", "仅预览清理；未删除任何数据",
                                "Pratonton pembersihan sahaja; tiada data dipadam"),
    "st_upgraded": ("Local database upgraded", "本地数据库已升级", "Pangkalan data setempat dinaik taraf"),
    "st_upgrade_preview_only": ("Database upgrade preview only; nothing changed", "仅预览数据库升级；未作任何更改",
                                "Pratonton naik taraf sahaja; tiada perubahan"),
    "st_maintenance_failed": ("Local history maintenance refused/failed · {cloud}", "本地历史维护被拒绝/失败 · {cloud}",
                              "Penyelenggaraan sejarah setempat ditolak/gagal · {cloud}"),
    "st_upgrade_failed": ("Database upgrade refused/failed; nothing changed · {cloud}",
                          "数据库升级被拒绝/失败；未作任何更改 · {cloud}",
                          "Naik taraf pangkalan data ditolak/gagal; tiada perubahan · {cloud}"),
    "st_failed_reload": ("Read / check failed · Reload Files to retry.{db}", "读取/检查失败 · 请点击 Reload Files 重试。{db}",
                         "Baca / semakan gagal · Klik Reload Files untuk cuba semula.{db}"),
    "st_failed_card": ("Read / check failed · Click the file card for details.{db}",
                       "读取/检查失败 · 点击文件卡片查看详情。{db}",
                       "Baca / semakan gagal · Klik kad fail untuk butiran.{db}"),
    "st_db_suffix": (" · Inventory Database: {state} — {cloud}", " · 库存数据库：{state} — {cloud}",
                     " · Pangkalan data inventori: {state} — {cloud}"),
    "st_export_outdated": ("{outdated} · {detail} · {cloud}", "{outdated} · {detail} · {cloud}",
                           "{outdated} · {detail} · {cloud}"),
    "st_cache_export_failed": ("{outdated} · {label} · {cloud}", "{outdated} · {label} · {cloud}",
                               "{outdated} · {label} · {cloud}"),
    "st_exported": ("Report exported successfully.", "报告已成功导出。", "Laporan berjaya dieksport."),
    "st_cache_exported": ("{label} report exported · Cloud Not Verified", "{label} 报告已导出 · Cloud Not Verified",
                          "Laporan {label} dieksport · Cloud Not Verified"),
    "st_remember_failed": ("Could not remember the selected file for next start: {error}",
                           "无法记住所选文件供下次启动使用：{error}",
                           "Fail dipilih tidak dapat diingat untuk permulaan seterusnya: {error}"),
    # dialogs: file reading
    "role_stock": ("Storage Excel", "Storage / 库存 Excel", "Excel Storage"),
    "role_bom": ("BOM Excel", "BOM Excel", "Excel BOM"),
    "err_role_failed": ("{role} could not be read: {error}\nFix the file (save and close it in Excel if needed), then "
                        "click Reload Files. The other file is not affected.",
                        "{role}：{error}\n修正后点击 Reload Files 重试；另一文件不受影响。",
                        "{role} tidak dapat dibaca: {error}\nBetulkan fail (simpan dan tutup dalam Excel jika perlu), "
                        "kemudian klik Reload Files. Fail yang satu lagi tidak terjejas."),
    "err_sheet_gone": ("After the source file was updated, the selected Sheet no longer exists or no longer has the "
                       "expected headers. Click Reload Files and select it again.",
                       "源文件更新后，所选 Sheet 不再存在/不符合表头。请 Reload Files 并重新选择。",
                       "Selepas fail sumber dikemas kini, Sheet dipilih tiada lagi atau tajuknya tidak sepadan. Klik "
                       "Reload Files dan pilih semula."),
    "err_unexpected": ("{error}\n\nWhat was loaded cannot be trusted, so both files were cleared. Fix the problem, then "
                       "choose the files again or click Reload Files.",
                       "{error}\n\n已加载的内容无法确认，两份文件均已清除。修正后重新选择文件或点击 Reload Files。",
                       "{error}\n\nApa yang dibaca tidak boleh dipercayai, jadi kedua-dua fail dikosongkan. Betulkan "
                       "masalah, kemudian pilih fail semula atau klik Reload Files."),
    "err_no_files": ("Choose the files with Browse first.", "请先 Browse 选择文件。", "Pilih fail dengan Browse dahulu."),
    # dialogs: database copy after a read or check
    "sync_role": ("Inventory Database · {role}: {state}\n{error}\n{kept}", "Inventory Database · {role}: {state}\n{error}\n{kept}",
                  "Pangkalan data inventori · {role}: {state}\n{error}\n{kept}"),
    "sync_kept_unknown": ("The database sync status could not be read: earlier synchronised data and its time cannot be "
                          "confirmed. Data already in the database is not deleted.",
                          "无法读取数据库同步状态：不能确认此前同步的数据及其时间。数据库中已有的数据不会被删除。",
                          "Status penyegerakan pangkalan data tidak dapat dibaca: data terdahulu dan masanya tidak dapat "
                          "disahkan. Data sedia ada dalam pangkalan data tidak dipadam."),
    "sync_kept_previous": ("The database keeps the previously synchronised data (Previously Verified {time}, historical), "
                           "but it is not verified now and is not shown as newly synchronised.",
                           "数据库保留此前同步的数据（Previously Verified {time}，历史时间），但当前未验证，未显示为新同步。",
                           "Pangkalan data menyimpan data yang diselaraskan sebelum ini (Previously Verified {time}, "
                           "sejarah), tetapi kini tidak disahkan dan tidak dipapar sebagai baru diselaraskan."),
    "sync_kept_none": ("The database has no earlier data for this file.", "数据库中没有该文件此前的数据。",
                       "Pangkalan data tiada data terdahulu bagi fail ini."),
    "sync_unrecorded": ("(This failure could not be written to the database record.)", "（本次失败未能写入数据库记录。）",
                        "(Kegagalan ini tidak dapat ditulis ke rekod pangkalan data.)"),
    "sync_status_failed": ("Inventory Database status could not be read: {error}\nThe status is shown as {state}; the "
                           "status shown before was cleared and does not mean the database matches the source files.",
                           "Inventory Database 状态读取失败：{error}\n状态显示为 {state}；此前显示的状态已清除，不能视为数据库与源文件一致。",
                           "Status pangkalan data inventori tidak dapat dibaca: {error}\nStatus dipapar sebagai {state}; "
                           "status sebelum ini dikosongkan dan tidak bermaksud pangkalan data sepadan dengan fail sumber."),
    "sync_retry": ("Fix the problem, then click Refresh Excel to retry.", "修正后点击 Refresh Excel 重试。",
                   "Betulkan masalah, kemudian klik Refresh Excel untuk cuba semula."),
    # dialogs: input
    "err_quantity": ("The production quantity must be a positive whole number (1, 2, 3 …).\nDetail: {detail}\nEnter a "
                     "whole number, then CHECK again.",
                     "{detail}\n请输入正整数后重新 CHECK。",
                     "Kuantiti pengeluaran mesti nombor bulat positif (1, 2, 3 …).\nButiran: {detail}\nMasukkan nombor "
                     "bulat, kemudian CHECK semula."),
    "err_files_first": ("Load both the Storage and BOM files successfully first. A file that failed can be retried "
                        "with Reload Files after fixing it.",
                        "请先成功读取库存与 BOM 文件。未加载的文件可在修正后点击 Reload Files 重试。",
                        "Baca fail Storage dan BOM dengan berjaya dahulu. Fail yang gagal boleh dicuba semula dengan "
                        "Reload Files selepas dibetulkan."),
    "err_product": ("“{text}” is not a selected Product ID. {matches}A partial, invented or ambiguous name cannot be "
                    "checked.",
                    "“{text}” 不是一个已选定的 Product ID。{matches}部分名称、虚构名称或歧义名称不能检查。",
                    "“{text}” bukan ID produk yang dipilih. {matches}Nama separa, rekaan atau samar tidak boleh disemak."),
    "err_product_matches": ("{count} matches: choose one from the list. ", "有 {count} 个匹配项，请从下拉列表中选择一个。",
                            "{count} padanan: pilih satu daripada senarai. "),
    "err_product_none": ("No Product ID in the BOM matches; choose an existing product from the list. ",
                         "BOM 中没有匹配的 Product ID；请从下拉列表选择实际存在的产品。",
                         "Tiada ID produk dalam BOM yang sepadan; pilih produk yang wujud daripada senarai. "),
    "err_sheet": ("Choose the actual Storage Sheet; several Storage Sheets are never merged automatically.",
                  "请选择实际库存 Sheet；多个库存 Sheet 不会自动合并。",
                  "Pilih Sheet Storage yang sebenar; beberapa Sheet Storage tidak pernah digabungkan secara automatik."),
    "err_cache_expired": ("The cache authorisation has expired. Click Use Cached Data to confirm the versions again.",
                          "缓存授权已失效。请点击 Use Cached Data 重新确认版本。",
                          "Kebenaran cache telah tamat. Klik Use Cached Data untuk mengesahkan versi semula."),
    "needs_db_body": ("A readable local database is required.", "需要可读取的本地数据库。",
                      "Pangkalan data setempat yang boleh dibaca diperlukan."),
    # dialogs: export
    "err_no_result": ("Run CHECK first. After an input or file change, an old result is never exported.",
                      "请先 CHECK。输入或文件变化后旧结果不会被导出。",
                      "Jalankan CHECK dahulu. Selepas input atau fail berubah, keputusan lama tidak pernah dieksport."),
    "err_result_changed": ("The CHECK result changed while you chose the export location. Start the export again.",
                           "选择导出位置期间 CHECK 结果已变化，请重新发起导出。",
                           "Keputusan CHECK berubah semasa anda memilih lokasi eksport. Mulakan eksport semula."),
    "err_cache_outdated": ("The historical cached result cannot be re-checked. Select the cache again and CHECK, or "
                           "Refresh Excel to read the source files again.\n{detail}",
                           "历史缓存结果无法复核。请重新选择缓存并 CHECK，或 Refresh Excel 重新读取源文件。\n{detail}",
                           "Keputusan cache sejarah tidak dapat disemak semula. Pilih cache semula dan CHECK, atau "
                           "Refresh Excel untuk membaca fail sumber semula.\n{detail}"),
    "err_outdated": ("This result cannot be confirmed to belong to the current local Storage / BOM file versions (a "
                     "source changed or could not be re-checked), so it cannot be exported as a valid report. CHECK "
                     "again.{detail}",
                     "此结果不能确认属于当前的本机 Storage / BOM 文件版本（源文件已变化或无法复核），不能导出为有效报告。请重新 CHECK。{detail}",
                     "Keputusan ini tidak dapat disahkan milik versi fail Storage / BOM setempat semasa (sumber "
                     "berubah atau tidak dapat disemak semula), jadi tidak boleh dieksport sebagai laporan sah. CHECK "
                     "semula.{detail}"),
    "err_write": ("Could not write {path}\n{detail}\nChoose another folder, or close a file of that name if it is open, "
                  "then export again.",
                  "无法写入 {path}\n{detail}\n请选择其他文件夹，或关闭已打开的同名文件后重新导出。",
                  "Tidak dapat menulis {path}\n{detail}\nPilih folder lain, atau tutup fail bernama sama jika terbuka, "
                  "kemudian eksport semula."),
    "err_export": ("{detail}\nNothing was exported. CHECK again, then export again.",
                   "{detail}\n未导出任何内容。请重新 CHECK 后再导出。",
                   "{detail}\nTiada apa dieksport. CHECK semula, kemudian eksport semula."),
    "title_open_folder": ("Open Folder failed", "无法打开文件夹", "Gagal membuka folder"),
    "pref_failed": ("The interface language could not be saved for the next start ({error}). It applies to this "
                    "session only.",
                    "界面语言无法保存供下次启动使用（{error}）。仅本次会话有效。",
                    "Bahasa antara muka tidak dapat disimpan untuk permulaan seterusnya ({error}). Ia hanya untuk sesi "
                    "ini."),
    "pref_unreadable": ("The saved interface-language file could not be read; English is used. Choosing a language "
                        "saves a new file.",
                        "已保存的界面语言文件无法读取，已使用英文。重新选择语言会保存新文件。",
                        "Fail bahasa antara muka yang disimpan tidak dapat dibaca; bahasa Inggeris digunakan. Memilih "
                        "bahasa menyimpan fail baharu."),
}
S.update(M)


class Message:
    """A message kept as its key and raw values, rendered in whichever interface language is current.

    Values may be str (shown as given: details, names, paths, codes), numbers, State, Join or other Messages."""

    def __init__(self, key, **values):
        if key not in S:
            raise KeyError(key)
        self.key, self.values = key, values

    def __eq__(self, other):
        return isinstance(other, Message) and (self.key, self.values) == (other.key, other.values)

    def __repr__(self):
        return f"Message({self.key!r}, {self.values!r})"


class State:
    """A sync state constant; glossed in zh/ms by state_text, unchanged in English."""

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, State) and self.value == other.value


class Join:
    def __init__(self, parts, separator="\n\n"):
        self.parts, self.separator = tuple(parts), separator

    def __eq__(self, other):
        return isinstance(other, Join) and (self.parts, self.separator) == (other.parts, other.separator)


def render(item, language="en"):
    if isinstance(item, Message):
        return tr(item.key, language, **{name: render(value, language) for name, value in item.values.items()})
    if isinstance(item, State):
        return state_text(item.value, language)
    if isinstance(item, Join):
        return item.separator.join(text for text in (render(part, language) for part in item.parts) if text)
    return "" if item is None else str(item)
