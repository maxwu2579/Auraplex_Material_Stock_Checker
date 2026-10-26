"""Business-language summaries of report facts. Presentation only: no Tk, no database, no calculation.

One vocabulary for English, Chinese and Malay, applied to the same facts. A summary shows the answer first; internal
codes, paths, hashes, versions and full logs stay in the details and in the saved JSON. Unknown stays unknown (never 0),
failed or unverified states are always stated, and an alert entry count is never presented as a material count.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
from pathlib import PureWindowsPath

LANGS = ("en", "zh", "ms")
SHOWN_ITEMS = 8   # list items in a summary; the details always hold every loaded item

ALERT = {
    "OUT_OF_STOCK": ("Zero stock", "零库存", "Stok sifar"),
    "LOW_STOCK": ("Below minimum stock", "低于最低库存", "Di bawah stok minimum"),
    "BOM_MATERIAL_NOT_IN_STOCK_MASTER": ("BOM material not found in the stock list", "BOM 材料未在库存表找到",
                                         "Bahan BOM tiada dalam senarai stok"),
    "DATA_ISSUE": ("Data issue alerts", "数据问题提醒", "Amaran isu data"),
    "THRESHOLD_NOT_CONFIGURED": ("Minimum stock not set", "未设置最低库存", "Stok minimum belum ditetapkan"),
}
KEY_ALERTS = ("OUT_OF_STOCK", "LOW_STOCK", "BOM_MATERIAL_NOT_IN_STOCK_MASTER")
DATA_ALERTS = ("DATA_ISSUE", "THRESHOLD_NOT_CONFIGURED")
CHANGE = {
    "QUANTITY_CHANGED": ("quantity changed", "数量变化", "kuantiti berubah"),
    "ADDED": ("newly listed", "新出现", "baru tersenarai"),
    "REMOVED": ("no longer listed", "不再出现", "tidak lagi tersenarai"),
    "VALIDITY_CHANGED": ("blank/text status changed", "空白或文字状态变化", "status kosong/teks berubah"),
    "DUPLICATE_CHANGED": ("duplicate rows changed", "重复记录变化", "baris pendua berubah"),
}
ISSUE = {
    "DUPLICATE_STOCK": ("duplicate stock rows", "库存重复记录", "baris stok pendua"),
    "INVALID_BOM_QTY": ("invalid BOM quantities", "BOM 用量无效", "kuantiti BOM tidak sah"),
    "DUPLICATE_BOM": ("duplicate BOM rows", "BOM 重复记录", "baris BOM pendua"),
    "INVALID_MATERIAL_ID": ("invalid Material IDs", "材料编号无效", "ID bahan tidak sah"),
    "NUMERIC_MATERIAL_ID": ("Material IDs stored as numbers", "材料编号以数字格式保存", "ID bahan disimpan sebagai nombor"),
}
ROLE = {"stock": ("Stock list", "库存表", "Senarai stok"), "bom": ("BOM", "BOM", "BOM"),
        "Storage": ("Stock list", "库存表", "Senarai stok"), "BOM": ("BOM", "BOM", "BOM")}
COVERAGE = {
    # M4F report facts
    "NO_HISTORY": ("no stock history yet", "还没有库存历史", "belum ada sejarah stok"),
    "REMOVED": ("history removed by cleanup", "历史已被清理", "sejarah dibuang oleh pembersihan"),
    "PARTLY_PRUNED": ("history partly removed by cleanup", "部分历史已被清理", "sebahagian sejarah dibuang"),
    "NO_OBSERVATION_IN_WINDOW": ("history starts after this period", "历史记录晚于本期", "sejarah bermula selepas tempoh ini"),
    "STARTED_DURING_WINDOW": ("history starts during this period", "历史在本期中途才开始",
                              "sejarah bermula di tengah tempoh ini"),
    "AVAILABLE_FROM_WINDOW_START": ("history covers the whole period", "历史覆盖整个本期",
                                    "sejarah meliputi seluruh tempoh"),
    # M3.2D daily summary
    "BEFORE_HISTORY": ("history starts after this date", "历史记录晚于这一天", "sejarah bermula selepas tarikh ini"),
    "PARTLY_REMOVED": ("history partly removed by cleanup", "部分历史已被清理", "sebahagian sejarah dibuang"),
    "STARTS_DURING_DAY": ("history starts during this date", "历史在当天中途才开始", "sejarah bermula pada tarikh ini"),
    "COVERED": ("history covers this date", "历史覆盖当天", "sejarah meliputi tarikh ini"),
}
FULL_COVERAGE = ("AVAILABLE_FROM_WINDOW_START", "COVERED")
NO_COVERAGE = ("NO_HISTORY", "REMOVED", "NO_OBSERVATION_IN_WINDOW", "BEFORE_HISTORY")

T = {
    "unknown": ("unknown", "未知", "tidak diketahui"),
    "shown": ("Showing {shown} of {total}; the complete list is in the details.",
              "显示 {shown} 项，共 {total} 项；完整清单见明细。",
              "Memaparkan {shown} daripada {total}; senarai penuh dalam butiran."),
    "capped": ("Loaded {loaded} of {total}: the read limit was reached, so the details are incomplete too.",
               "已载入 {loaded} 项，共 {total} 项：已达读取上限，明细也不完整。",
               "Dimuatkan {loaded} daripada {total}: had bacaan dicapai, jadi butiran juga tidak lengkap."),
    "shown_only": ("Showing {shown}.", "显示 {shown} 项。", "Memaparkan {shown}."),
    "hint_alerts": ("Use the Stock Alerts window filters (type, material, Sheet) for the rest.",
                    "其余提醒可在「库存提醒」窗口按类型、材料或 Sheet 筛选查看。",
                    "Gunakan penapis tetingkap Stock Alerts (jenis, bahan, Sheet) untuk selebihnya."),
    "hint_history": ("Use Inventory History for one material at a time to see its changes.",
                     "可在「库存历史」窗口逐个材料查看其变化。",
                     "Gunakan Inventory History bagi satu bahan pada satu masa untuk melihat perubahannya."),
    "details_title": ("Details and data basis", "明细与数据依据", "Butiran dan asas data"),
    "observed_note": ("Observed change ≠ actual consumption. This is not a purchase or production decision.",
                      "观察变化 ≠ 实际消耗。本报告不是采购或生产决定。",
                      "Perubahan diperhatikan ≠ penggunaan sebenar. Ini bukan keputusan pembelian atau pengeluaran."),
    # ---- AI aggregate report
    "r_title_daily": ("Daily report · {start} → {end} (local time)", "日报 · {start} → {end}（本机时间）",
                      "Laporan harian · {start} → {end} (waktu setempat)"),
    "r_title_weekly": ("Weekly report · {start} → {end} (local time)", "周报 · {start} → {end}（本机时间）",
                       "Laporan mingguan · {start} → {end} (waktu setempat)"),
    "r_status": ("Data status: UNVERIFIED historical records · Cloud Not Verified",
                 "数据状态：未复核的历史记录（UNVERIFIED）· Cloud Not Verified",
                 "Status data: rekod sejarah belum disahkan (UNVERIFIED) · Cloud Not Verified"),
    "r_sync_ok": ("{role} data as of: last synchronised {time}", "{role}数据截至：{time} 同步成功",
                  "Data {role} setakat: disegerakkan {time}"),
    "r_sync_failed": ("{role}: the latest check failed ({time}). Earlier data is shown and may be out of date.",
                      "{role}：最近一次检查失败（{time}），显示的是之前同步的数据，可能已过期。",
                      "{role}: semakan terakhir gagal ({time}). Data terdahulu dipaparkan dan mungkin lapuk."),
    "r_sync_never": ("{role} has never been synchronised: no data.", "{role}尚未同步：没有数据。",
                     "{role} belum pernah disegerakkan: tiada data."),
    "r_sync_unknown": ("{role}: the latest check result is unknown.", "{role}：最近一次检查结果未知。",
                       "{role}: keputusan semakan terakhir tidak diketahui."),
    "sec_stock": ("Key stock points", "库存重点", "Perkara utama stok"),
    "alerts_unknown": ("Alert counts unknown: there is no stored evaluation of the current files. This does not mean "
                       "there are no alerts.",
                       "提醒数量未知：当前文件没有已存的评估。这不代表没有提醒。",
                       "Bilangan amaran tidak diketahui: tiada penilaian tersimpan bagi fail semasa. Ini tidak bermakna "
                       "tiada amaran."),
    "alerts_stored": ("Stored alerts, not re-checked (evaluated {time}).", "已存的提醒，未重新检查（评估于 {time}）。",
                      "Amaran tersimpan, tidak disemak semula (dinilai {time})."),
    "alert_line": ("{label}: {ids} material ID(s) · {alerts} alert entry(ies)", "{label}：{ids} 个材料编号（{alerts} 条提醒）",
                   "{label}: {ids} ID bahan ({alerts} catatan amaran)"),
    "alerts_any": ("Material IDs with at least one alert: {count}. One material can be in several categories; do not "
                   "add the categories up.",
                   "共有 {count} 个材料编号至少有一条提醒。同一材料可属于多个类别，各类别不能相加。",
                   "{count} ID bahan mempunyai sekurang-kurangnya satu amaran. Satu bahan boleh berada dalam beberapa "
                   "kategori; jangan jumlahkan kategori."),
    "sec_data": ("Data to tidy up", "数据待整理", "Data perlu dikemas kini"),
    "q_blank": ("Stock quantity blank: {count} rows (not 0)", "库存数量空白：{count} 行（不是 0）",
                "Kuantiti stok kosong: {count} baris (bukan 0)"),
    "q_text": ("Stock quantity is text or invalid: {count} rows (quantity to be confirmed)",
               "库存数量为文字或无效：{count} 行（数量待确认）",
               "Kuantiti stok berupa teks atau tidak sah: {count} baris (perlu disahkan)"),
    "q_noid": ("Stock rows without a usable Material ID: {count}", "库存表中没有可用编号的行：{count}",
               "Baris stok tanpa ID bahan yang boleh digunakan: {count}"),
    "q_dup": ("Material IDs listed more than once in the stock list: {count} (rows not merged)",
              "库存表中重复出现的编号：{count} 个（各行不合并）",
              "ID bahan tersenarai lebih sekali dalam senarai stok: {count} (baris tidak digabung)"),
    "q_storage_unknown": ("Stock list data-quality counts: unknown", "库存表数据质量计数：未知",
                          "Kiraan kualiti data senarai stok: tidak diketahui"),
    "q_issue": ("{role}: {label} — {count} rows", "{role}：{label} — {count} 行", "{role}: {label} — {count} baris"),
    "q_none": ("No recorded data issues.", "没有记录到数据问题。", "Tiada isu data direkodkan."),
    "sec_changes": ("Observed changes in the same source file (not actual consumption)",
                    "同一数据源内的观察变化（不等于实际消耗）",
                    "Perubahan diperhatikan dalam fail sumber yang sama (bukan penggunaan sebenar)"),
    "hist_none": ("No usable history for this period ({coverage}); no conclusion about changes.",
                  "本期没有可用的历史（{coverage}），无法得出变化结论。",
                  "Tiada sejarah boleh digunakan untuk tempoh ini ({coverage}); tiada kesimpulan tentang perubahan."),
    "hist_partial": ("History only partly covers this period ({coverage}); changes cannot be concluded for the whole "
                     "period.",
                     "历史只覆盖本期的一部分（{coverage}），不能对整个本期下变化结论。",
                     "Sejarah hanya meliputi sebahagian tempoh ini ({coverage}); perubahan tidak boleh disimpulkan "
                     "untuk seluruh tempoh."),
    "changes_line": ("{events} change(s) on {ids} material ID(s): {parts}", "{events} 条变化，涉及 {ids} 个材料编号：{parts}",
                     "{events} perubahan pada {ids} ID bahan: {parts}"),
    "changes_no_snapshot": ("No new stock version was synchronised in this period, so no change was recorded. This "
                            "does not prove there was no movement.",
                            "本期没有同步到新的库存版本，因此没有记录到变化。这不证明没有出入。",
                            "Tiada versi stok baharu disegerakkan dalam tempoh ini, jadi tiada perubahan direkodkan. "
                            "Ini tidak membuktikan tiada pergerakan."),
    "changes_none": ("No differences were recorded between the synchronised versions of the same file. This does not "
                     "prove there was no movement.",
                     "同一文件的已同步版本之间没有记录到差异。这不证明没有出入。",
                     "Tiada perbezaan direkodkan antara versi fail yang sama. Ini tidak membuktikan tiada pergerakan."),
    "cmp_line": ("Compared with the previous period (same-source change counts): {parts}",
                 "与上期相比（同源变化条数）：{parts}",
                 "Berbanding tempoh sebelumnya (kiraan perubahan sumber sama): {parts}"),
    "cmp_incomplete": ("Not comparable with the previous period: history or stock observations are missing.",
                       "无法与上期比较：缺少历史或库存观察记录。",
                       "Tidak boleh dibandingkan dengan tempoh sebelumnya: sejarah atau pemerhatian stok tiada."),
    "switch_line": ("The stock source file was switched {count} time(s) in this period. Differences caused by the "
                    "switch: {parts} ({events} in total). They are listed separately, not counted above, and are not "
                    "receipts, issues, consumption, losses or purchases.",
                    "本期更换了 {count} 次库存数据源。更换造成的记录差异：{parts}（共 {events} 条）。这些差异单独列出，"
                    "不计入上面的变化，不代表入库、出库、消耗、损失或采购。",
                    "Fail sumber stok ditukar {count} kali dalam tempoh ini. Perbezaan akibat pertukaran: {parts} "
                    "(jumlah {events}). Ia disenaraikan berasingan, tidak dikira di atas, dan bukan penerimaan, "
                    "pengeluaran, penggunaan, kerugian atau pembelian."),
    "switch_none": ("none recorded", "未记录到差异", "tiada direkodkan"),
    "baseline_line": ("{count} first import(s) in this period: a starting point for later comparison, not stock "
                      "received.",
                      "本期有 {count} 次首次导入：这是之后比较的起点，不是入库。",
                      "{count} import pertama dalam tempoh ini: titik permulaan untuk perbandingan, bukan stok diterima."),
    "sec_review": ("Needs human review", "需要人工复核", "Perlu semakan manusia"),
    "rv_alerts": ("Alerts are stored results and were not re-checked.", "提醒是已存结果，未重新检查。",
                  "Amaran ialah hasil tersimpan dan tidak disemak semula."),
    "rv_threshold": ("Minimum-stock thresholds and units are not yet confirmed by the business.",
                     "最低库存阈值的含义和单位尚未经业务确认。",
                     "Ambang stok minimum dan unit belum disahkan oleh perniagaan."),
    "rv_sync": ("The latest synchronisation failed: refresh before relying on these figures.",
                "最近一次同步失败：请先刷新再使用这些数字。",
                "Penyegerakan terakhir gagal: segarkan sebelum bergantung pada angka ini."),
    "rv_switch": ("Confirm that the source-file switch was intended before comparing periods.",
                  "比较前请确认更换数据源是否符合预期。",
                  "Sahkan pertukaran fail sumber memang dimaksudkan sebelum membandingkan tempoh."),
    # ---- Daily stock summary
    "d_title": ("Daily stock report {day} ({when}) — {status} · Cloud Not Verified",
                "库存日报 {day}（{when}）— {status} · Cloud Not Verified",
                "Laporan stok harian {day} ({when}) — {status} · Cloud Not Verified"),
    "d_today": ("today", "今天", "hari ini"),
    "d_past": ("past date", "过去日期", "tarikh lalu"),
    "d_verified": ("Generated {generated}. VERIFIED only means: at that time this program had checked both local "
                   "Excel files and re-checked the alerts in this session. It is not business approval of the stock "
                   "and not a cloud check.",
                   "生成于 {generated}。VERIFIED 仅表示：生成时本程序已在本次会话核对两份本机 Excel 并重新检查提醒；"
                   "这不是库存业务批准，也不是云端核实。",
                   "Dijana {generated}. VERIFIED hanya bermaksud: pada masa itu program ini telah menyemak kedua-dua "
                   "fail Excel setempat dan amaran dalam sesi ini. Ini bukan kelulusan perniagaan atas stok dan bukan "
                   "semakan awan."),
    "d_unverified": ("Generated {generated} after your confirmation. Not verified because: {reasons}",
                     "生成于 {generated}（经你确认）。未复核的原因：{reasons}",
                     "Dijana {generated} selepas pengesahan anda. Tidak disahkan kerana: {reasons}"),
    "d_asof": ("{role} data as of: imported {time} from {file}", "{role}数据截至：{time} 导入（文件 {file}）",
               "Data {role} setakat: diimport {time} daripada {file}"),
    "d_asof_none": ("{role}: never synchronised, no data.", "{role}：尚未同步，没有数据。",
                    "{role}: belum disegerakkan, tiada data."),
    "d_stale": ("{role}: the latest check failed ({time}); the data shown is from the last successful sync and may be "
                "out of date.",
                "{role}：最近一次检查失败（{time}）；显示的是上次成功同步的数据，可能已过期。",
                "{role}: semakan terakhir gagal ({time}); data yang dipaparkan daripada penyegerakan berjaya terakhir "
                "dan mungkin lapuk."),
    "d_alerts_hist": ("The alerts below are as of generation time, not the state on {day}.",
                      "以下提醒是生成时的状态，不是 {day} 当天的状态。",
                      "Amaran di bawah adalah pada masa penjanaan, bukan keadaan pada {day}."),
    "d_alerts_unavailable": ("Stock alerts are unavailable; this does not mean there are none. The reason is in the "
                             "details.",
                             "库存提醒不可用；这不代表没有提醒。原因见明细。",
                             "Amaran stok tidak tersedia; ini tidak bermakna tiada amaran. Sebab ada dalam butiran."),
    "d_alerts_stored": ("Stored alerts, not re-checked in this session; they may be out of date.",
                        "已存的提醒，本次会话未重新检查，可能已过期。",
                        "Amaran tersimpan, tidak disemak semula dalam sesi ini; mungkin lapuk."),
    "d_without_id": (" (plus {count} entries without a Material ID)", "（另有 {count} 条没有材料编号）",
                     " (serta {count} catatan tanpa ID bahan)"),
    "d_alerts_none": ("No alerts of these types in this evaluation. This is not a statement that stock is sufficient.",
                      "此次评估没有这些类别的提醒；这不表示库存充足。",
                      "Tiada amaran jenis ini dalam penilaian ini. Ini bukan kenyataan bahawa stok mencukupi."),
    "sec_items": ("Materials to look at first", "主要待处理材料", "Bahan untuk disemak dahulu"),
    "d_item": ("{label} · {id} · {description} · stock {stock}", "{label} · {id} · {description} · 库存 {stock}",
               "{label} · {id} · {description} · stok {stock}"),
    "d_item_min": (" · minimum {threshold}", " · 最低库存 {threshold}", " · minimum {threshold}"),
    "d_item_bom": ("{label} · {id} · {description} · used in {count} product(s); stock unknown, not 0",
                   "{label} · {id} · {description} · 用于 {count} 个产品；库存未知，不是 0",
                   "{label} · {id} · {description} · digunakan dalam {count} produk; stok tidak diketahui, bukan 0"),
    "d_items_none": ("No zero-stock, below-minimum or missing BOM materials in this evaluation.",
                     "此次评估没有零库存、低于最低库存或 BOM 材料缺失的项目。",
                     "Tiada bahan stok sifar, di bawah minimum atau bahan BOM tiada dalam penilaian ini."),
    "d_changes_title": ("Comparable observed changes on {day} (same source file; not actual consumption)",
                        "{day} 可比较的观察变化（同一数据源；不等于实际消耗）",
                        "Perubahan diperhatikan yang boleh dibanding pada {day} (fail sumber sama; bukan penggunaan "
                        "sebenar)"),
    "d_change_item": ("{time} · {id} · {label}: {before} → {after}", "{time} · {id} · {label}：{before} → {after}",
                      "{time} · {id} · {label}: {before} → {after}"),
    "d_difference": (" (observed difference {value})", "（观察差额 {value}）", " (perbezaan diperhatikan {value})"),
    "d_no_change": ("No observed change was recorded on this date. This only means nothing was recorded: stock may "
                    "not have been synchronised, or the file did not change. It does not mean there was no movement.",
                    "当天没有记录到观察变化。这只表示没有记录：可能没有同步，或文件没有变化；不代表仓库没有出入。",
                    "Tiada perubahan diperhatikan direkodkan pada tarikh ini. Ini hanya bermakna tiada rekod: stok "
                    "mungkin tidak disegerakkan atau fail tidak berubah. Ini tidak bermakna tiada pergerakan."),
    "d_same_none": ("No comparable change within one source file on this date.", "当天没有同一数据源内的可比较变化。",
                    "Tiada perubahan boleh dibanding dalam satu fail sumber pada tarikh ini."),
    "d_switch": ("On this date the {role} source file was switched ({transitions}). Differences caused by the "
                 "switch: {parts} ({events} in total). They are listed separately in the details, not counted above, "
                 "and are not receipts, issues, consumption, losses or purchases.",
                 "当天更换了{role}数据源（{transitions}）。更换造成的记录差异：{parts}（共 {events} 条）。"
                 "这些差异在明细中单独列出，不计入上面的变化，不代表入库、出库、消耗、损失或采购。",
                 "Pada tarikh ini fail sumber {role} ditukar ({transitions}). Perbezaan akibat pertukaran: {parts} "
                 "(jumlah {events}). Ia disenaraikan berasingan dalam butiran, tidak dikira di atas, dan bukan "
                 "penerimaan, pengeluaran, penggunaan, kerugian atau pembelian."),
    "d_switch_bom": ("The BOM source file was switched on this date ({transitions}); compare BOM results with care.",
                     "当天更换了 BOM 数据源（{transitions}）；比较 BOM 结果时请注意。",
                     "Fail sumber BOM ditukar pada tarikh ini ({transitions}); berhati-hati membandingkan keputusan BOM."),
    "d_baseline": ("First stock import on this date (baseline): a starting point for later comparison, not stock "
                   "received.",
                   "当天首次导入库存（基线）：这是之后比较的起点，不是入库。",
                   "Import stok pertama pada tarikh ini (garis dasar): titik permulaan untuk perbandingan, bukan stok "
                   "diterima."),
    "sec_limits": ("Data limits", "数据限制", "Had data"),
    "d_coverage": ("History: {coverage}.", "历史：{coverage}。", "Sejarah: {coverage}."),
    "d_sync_fail": ("{role}: {count} failed or unavailable checks on this date.", "{role}：当天有 {count} 次检查失败或不可用。",
                    "{role}: {count} semakan gagal atau tidak tersedia pada tarikh ini."),
    "d_sync_none": ("{role} was not checked on this date.", "{role}当天没有检查记录。",
                    "{role} tidak disemak pada tarikh ini."),
    "d_threshold_missing": ("{count} stock Sheet(s) have no single minimum-stock column; low-stock checks were not "
                            "done there.",
                            "{count} 个库存 Sheet 没有唯一的最低库存列，这些 Sheet 未做低库存判断。",
                            "{count} Sheet stok tiada satu lajur stok minimum; semakan stok rendah tidak dibuat di sana."),
}


def tx(key, lang, **values):
    text = T[key][LANGS.index(lang)]
    return text.format(**values) if values else text


def label(table, code, lang):
    row = table.get(code)
    return row[LANGS.index(lang)] if row else str(code)


def local_time(value, tz=None):
    """A stored UTC stamp ('YYYY-MM-DD HH:MM:SS.mmm'), an ISO time or a datetime as short local time; None stays
    None. The details keep the original UTC text."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                moment = datetime.fromisoformat(str(value))
            except ValueError:
                return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(tz) if tz is not None else moment.astimezone()).strftime("%Y-%m-%d %H:%M")


def file_name(path):
    return PureWindowsPath(path).name if path else None


def _number(value, lang):
    return tx("unknown", lang) if value is None else str(value)


def _parts(counts, lang, *, signed=False, keep_zero=False):
    """'quantity changed 3 · no longer listed 1' in the fixed change-type order."""
    parts = []
    for kind in CHANGE:
        value = counts.get(kind)
        if value is None or (value == 0 and not keep_zero):
            continue
        parts.append(f"{label(CHANGE, kind, lang)} {value:+d}" if signed else f"{label(CHANGE, kind, lang)} {value}")
    return " · ".join(parts)


def _shown(lines, shown, loaded, total, lang, hint=None):
    """'Showing X of Y; the complete list is in the details' only when the details hold all Y. When fewer rows were
    loaded than exist (the bounded read), the loaded and total counts are stated instead, with a narrowing hint."""
    if loaded < total:
        text = (tx("shown_only", lang, shown=shown) + " " if shown < loaded else "")
        lines.append(text + tx("capped", lang, loaded=loaded, total=total) + (" " + tx(hint, lang) if hint else ""))
    elif total > shown:
        lines.append(tx("shown", lang, shown=shown, total=total))


def text(sections) -> str:
    """Plain text: a title line per section, then its lines."""
    out = []
    for title, lines in sections:
        if not lines and title:
            continue
        if out:
            out.append("")
        if title:
            out.append(title)
        out.extend(lines)
    return "\n".join(out)


def html_sections(sections) -> str:
    """The same sections as escaped HTML for saved reports: bullet lines become list items."""
    out = []
    for title, lines in sections:
        if not lines and title:
            continue
        if title:
            out.append(f"<h3>{html.escape(title)}</h3>")
        bullets = []
        for line in lines + [None]:
            if line is not None and line.startswith("• "):
                bullets.append(f"<li>{html.escape(line[2:])}</li>")
                continue
            if bullets:
                out.append("<ul>" + "".join(bullets) + "</ul>")
                bullets = []
            if line is not None:
                out.append(f"<p>{html.escape(line)}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------- M4F aggregate report
def report_sections(facts, lang) -> list:
    """Summary of validated narrative facts (format 2). Every number comes from the facts unchanged."""
    current, alerts = facts["current_period"], facts["recorded_alerts"]
    window = current["window"]
    title = tx("r_title_daily" if facts["period"] == "DAILY" else "r_title_weekly", lang,
               start=_short_iso(window["start_local"]), end=_short_iso(window["end_local"]))
    status = [title, tx("r_status", lang)]
    failed_sync = False
    for role in ("stock", "bom"):
        sync = facts["latest_sync_attempts"][role]
        name, time = label(ROLE, role, lang), local_time(sync["finished_utc"]) or tx("unknown", lang)
        if sync["outcome"] in ("IMPORTED", "UNCHANGED"):
            if role == "stock":
                status.append(tx("r_sync_ok", lang, role=name, time=time))
        elif sync["outcome"] in ("FAILED", "UNAVAILABLE"):
            failed_sync = True
            status.append(tx("r_sync_failed", lang, role=name, time=time))
        elif sync["outcome"] == "NOT_SYNCED":
            status.append(tx("r_sync_never", lang, role=name))
        else:
            status.append(tx("r_sync_unknown", lang, role=name))
    stock, data = [], []
    counts, distinct = alerts["counts_by_type"], alerts["distinct_material_ids_by_type"]
    if counts is None:
        stock.append(tx("alerts_unknown", lang))
    else:
        stock.append(tx("alerts_stored", lang, time=local_time(alerts["evaluated_utc"])))
        for kind in KEY_ALERTS:
            stock.append("• " + tx("alert_line", lang, label=label(ALERT, kind, lang), ids=distinct[kind],
                                   alerts=counts[kind]))
        stock.append(tx("alerts_any", lang, count=alerts["distinct_material_ids_any_type"]))
        for kind in DATA_ALERTS:
            data.append("• " + tx("alert_line", lang, label=label(ALERT, kind, lang), ids=distinct[kind],
                                  alerts=counts[kind]))
    quality = facts["data_quality"]
    retained = quality["latest_retained_storage"]
    if retained is None:
        data.append("• " + tx("q_storage_unknown", lang))
    else:
        for key, name in (("blank_quantity_rows", "q_blank"), ("invalid_quantity_rows", "q_text"),
                          ("rows_without_usable_id", "q_noid"), ("duplicate_material_ids", "q_dup")):
            if retained[key]:
                data.append("• " + tx(name, lang, count=retained[key]))
    for role, issues in quality["recorded_issue_rows"].items():
        for issue, count in issues.items():
            if count is None or count:
                data.append("• " + tx("q_issue", lang, role=label(ROLE, role, lang), label=label(ISSUE, issue, lang),
                                      count=_number(count, lang)))
    if not data:
        data.append(tx("q_none", lang))
    changes = _report_changes(facts, current, lang)
    review = []
    if counts is not None:
        review.append("• " + tx("rv_alerts", lang))
        review.append("• " + tx("rv_threshold", lang))
    if failed_sync:
        review.append("• " + tx("rv_sync", lang))
    if current["source_switches"] or current["cross_source"]["events"]:
        review.append("• " + tx("rv_switch", lang))
    review.append(tx("observed_note", lang))
    return [(None, status), (tx("sec_stock", lang), stock), (tx("sec_data", lang), data),
            (tx("sec_changes", lang), changes), (tx("sec_review", lang), review)]


def _report_changes(facts, current, lang):
    lines = []
    coverage = current["coverage"]
    same = current["same_source"]
    if coverage in NO_COVERAGE:
        lines.append(tx("hist_none", lang, coverage=label(COVERAGE, coverage, lang)))
    else:
        if coverage not in FULL_COVERAGE:
            lines.append(tx("hist_partial", lang, coverage=label(COVERAGE, coverage, lang)))
        if same["events"]:
            lines.append(tx("changes_line", lang, events=same["events"], ids=same["distinct_material_ids"],
                            parts=_parts({k: v["events"] for k, v in same["changes_by_type"].items()}, lang)))
        elif coverage in FULL_COVERAGE:
            lines.append(tx("changes_no_snapshot" if current["snapshots"] == 0 else "changes_none", lang))
    comparison = facts["comparison"]
    if comparison["status"] == "COMPARABLE":
        lines.append(tx("cmp_line", lang, parts=_parts(comparison["change_event_delta_by_type"], lang, signed=True,
                                                         keep_zero=True)))
    elif comparison["status"] == "INCOMPLETE_HISTORY":
        lines.append(tx("cmp_incomplete", lang))
    cross = current["cross_source"]
    if current["source_switches"] or cross["events"]:
        parts = _parts({k: v["events"] for k, v in cross["changes_by_type"].items()}, lang) or tx("switch_none", lang)
        lines.append(tx("switch_line", lang, count=current["source_switches"], parts=parts, events=cross["events"]))
    if current["baseline_snapshots"]:
        lines.append(tx("baseline_line", lang, count=current["baseline_snapshots"]))
    return lines


def _short_iso(value):
    return value[:16].replace("T", " ") if value else "—"


# ---------------------------------------------------------------------- M3.2D daily stock summary
def daily_sections(d, lang, limit=SHOWN_ITEMS) -> list:
    """Summary of one immutable daily summary (summary.data()); counts are taken from it, never re-derived."""
    v, a, c, lim = d["verification"], d["alerts"], d["changes"], d["limitations"]
    generated = _short_iso(d["generated"]["local"])
    status = [tx("d_title", lang, day=d["report_date"], when=tx("d_past" if d["historical_date"] else "d_today", lang),
                 status=v["status"])]
    status.append(tx("d_verified", lang, generated=generated) if v["verified"] else
                  tx("d_unverified", lang, generated=generated, reasons="; ".join(v["reasons"])))
    for role in ("stock", "bom"):
        s = d["sources"][role]
        name = label(ROLE, role, lang)
        if s["current"] is None:
            status.append(tx("d_asof_none", lang, role=name))
            continue
        status.append(tx("d_asof", lang, role=name, time=local_time(s["current"]["imported_utc"]),
                         file=s["current"]["file_name"]))
        run = s["latest_run"]
        if run is not None and run["outcome"] not in ("IMPORTED", "UNCHANGED"):
            status.append(tx("d_stale", lang, role=name, time=local_time(run["finished_utc"])))
    g = a["at_generation"]
    stock, items = [], []
    if d["historical_date"]:
        stock.append(tx("d_alerts_hist", lang, day=d["report_date"]))
    if g["status"] == "UNAVAILABLE":
        stock.append(tx("d_alerts_unavailable", lang))
    else:
        if g["status"] != "CURRENT":
            stock.append(tx("d_alerts_stored", lang))
        by_type = {t["type"]: t for t in g["by_type"]}
        for kind in KEY_ALERTS + DATA_ALERTS:
            t = by_type[kind]
            line = tx("alert_line", lang, label=label(ALERT, kind, lang), ids=t["distinct_material_ids"],
                      alerts=t["alerts"])
            if t["entries_without_material_id"]:
                line += tx("d_without_id", lang, count=t["entries_without_material_id"])
            stock.append("• " + line)
        stock.append(tx("alerts_any", lang, count=g["distinct_material_ids_any_type"]))
        if g["total"] == 0:
            stock.append(tx("d_alerts_none", lang))
        items = _daily_items(g, by_type, lang, limit)
    raw = lim["current_storage_raw"]
    if raw:
        for key, name in (("blank", "q_blank"), ("invalid", "q_text"), ("without_usable_id", "q_noid"),
                          ("duplicate_ids", "q_dup")):
            if raw[key]:
                stock.append("• " + tx(name, lang, count=raw[key]))
    changes = _daily_changes(d, c, lim, lang, limit)
    limits = []
    coverage = lim["history"]["coverage"]
    if coverage not in FULL_COVERAGE:
        limits.append("• " + tx("d_coverage", lang, coverage=label(COVERAGE, coverage, lang)))
    for role in ("stock", "bom"):
        s = d["sources"][role]
        name = label(ROLE, role, lang)
        if not any(s["runs_on_day"].values()):
            limits.append("• " + tx("d_sync_none", lang, role=name))
        elif s["failures_on_day_total"]:
            limits.append("• " + tx("d_sync_fail", lang, role=name, count=s["failures_on_day_total"]))
    missing = sum(1 for t in lim["thresholds"] if t["state"] != "FOUND")
    if missing:
        limits.append("• " + tx("d_threshold_missing", lang, count=missing))
    limits.append("• " + tx("rv_threshold", lang))
    limits.append(tx("observed_note", lang))
    title_changes = tx("d_changes_title", lang, day=d["report_date"])
    return [(None, status), (tx("sec_stock", lang), stock), (tx("sec_items", lang), items),
            (title_changes, changes), (tx("sec_limits", lang), limits)]


def _daily_items(g, by_type, lang, limit):
    wanted = [i for kind in KEY_ALERTS for i in g["items"] if i["type"] == kind]
    total = sum(by_type[kind]["alerts"] for kind in KEY_ALERTS)
    if not total:
        return [tx("d_items_none", lang)]
    lines = []
    for item in wanted[:limit]:
        name = label(ALERT, item["type"], lang)
        identity = item["material_id"] or item.get("code") or "—"
        description = item["description"] or "—"
        if item["type"] == "BOM_MATERIAL_NOT_IN_STOCK_MASTER":
            lines.append("• " + tx("d_item_bom", lang, label=name, id=identity, description=description,
                                   count=len(item.get("products") or ())))
            continue
        line = tx("d_item", lang, label=name, id=identity, description=description, stock=item["stock"])
        if item["type"] == "LOW_STOCK" and item["threshold"] not in (None, "—"):
            line += tx("d_item_min", lang, threshold=item["threshold"].split(" [", 1)[0])
        lines.append("• " + line)
    _shown(lines, min(limit, len(wanted)), len(wanted), total, lang, "hint_alerts")
    return lines


def _daily_changes(d, c, lim, lang, limit):
    lines = []
    same, cross = c["same_source"], c["cross_source"]
    coverage = lim["history"]["coverage"]
    if same["total"]:
        counts = {k: v["changes"] for k, v in same["by_type"].items()}
        lines.append(tx("changes_line", lang, events=same["total"], ids=same["distinct_material_ids"],
                        parts=_parts(counts, lang)))
        listed = [i for i in c["items"] if not i["source_switched"]]
        listed.sort(key=lambda i: i["change_type"] != "QUANTITY_CHANGED")  # stable: quantity changes first
        for item in listed[:limit]:
            line = tx("d_change_item", lang, time=local_time(item["observed_utc"]), id=item["material_id"],
                      label=label(CHANGE, item["change_type"], lang), before=item["before"], after=item["after"])
            if item["observed_difference"] is not None:
                line += tx("d_difference", lang, value=item["observed_difference"])
            lines.append("• " + line)
        _shown(lines, min(limit, len(listed)), len(listed), same["total"], lang, "hint_history")
    elif c["total"] == 0:
        if coverage in FULL_COVERAGE:
            lines.append(tx("d_no_change", lang))
        else:
            lines.append(tx("hist_none" if coverage in NO_COVERAGE else "hist_partial", lang,
                            coverage=label(COVERAGE, coverage, lang)))
    else:
        lines.append(tx("d_same_none", lang))
    transitions = lambda role: ", ".join(f"{file_name(s['previous_path']) or '—'} → {file_name(s['path']) or '—'}"
                                         for s in c["source_switches"] if s["role"] == role) or "—"
    if cross["total"] or any(s["role"] == "Storage" for s in c["source_switches"]):
        # Only Storage snapshots record changes, so every cross-source difference belongs to a Storage switch.
        parts = _parts({k: v["changes"] for k, v in cross["by_type"].items()}, lang) or tx("switch_none", lang)
        lines.append(tx("d_switch", lang, role=label(ROLE, "stock", lang), transitions=transitions("Storage"),
                        parts=parts, events=cross["total"]))
    if any(s["role"] == "BOM" for s in c["source_switches"]):
        lines.append(tx("d_switch_bom", lang, transitions=transitions("BOM")))
    if any(s["baseline"] for s in c["snapshots"]):
        lines.append(tx("d_baseline", lang))
    return lines
