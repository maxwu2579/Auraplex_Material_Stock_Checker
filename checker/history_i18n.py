"""History-window interface resources. Raw workbook values and query notes are never translated by substitution."""
from . import i18n

# English templates are stable keys; parameters always remain original data.
TEXT = {
    "Inventory History — Historical Observations": ("库存历史 — 历史观察", "Sejarah inventori — Pemerhatian sejarah"),
    "HISTORICAL OBSERVATIONS · Not current stock · Cloud Not Verified": ("HISTORICAL OBSERVATIONS · 历史观察，非当前库存 · Cloud Not Verified", "HISTORICAL OBSERVATIONS · Pemerhatian sejarah, bukan stok semasa · Cloud Not Verified"),
    "Observed Change ≠ Actual Consumption · Blank stock ≠ 0 · Duplicate IDs never added · Invalid quantities never converted · Sheets / source files never merged · No comparable difference across a source switch": ("观察变化 ≠ 实际消耗 · 空白库存 ≠ 0 · 重复编号不相加 · 无效数量不转换 · Sheet / 来源文件不合并 · 来源切换前后不可比较", "Perubahan diperhatikan ≠ Penggunaan sebenar · Stok kosong ≠ 0 · ID pendua tidak dijumlahkan · Kuantiti tidak sah tidak ditukar · Sheet / fail sumber tidak digabungkan · Tidak boleh dibandingkan merentas pertukaran sumber"),
    "Material ID": ("材料编号", "ID bahan"),
    "Search": ("搜索", "Cari"),
    "Storage Sheet": ("库存 Sheet", "Sheet Storage"),
    "Range": ("范围", "Julat"),
    "{days} days": ("{days} 天", "{days} hari"),
    "Query": ("查询", "Tanya"),
    "Close": ("关闭", "Tutup"),
    "Show more": ("显示更多", "Papar lagi"),
    "All Sheets (shown separately)": ("所有 Sheet（分别显示）", "Semua Sheet (dipapar berasingan)"),
    "Type part of a Material ID, then select one exact ID.": ("输入部分材料编号，再选择一个实际编号。", "Taip sebahagian ID bahan, kemudian pilih satu ID tepat."),
    "Selected: {material}": ("已选：{material}", "Dipilih: {material}"),
    "Searching…": ("搜索中…", "Sedang mencari…"),
    "Search failed; no candidates shown: {error}": ("搜索失败；未显示候选：{error}", "Carian gagal; tiada calon dipaparkan: {error}"),
    "(not in the current Storage version)": ("（不在当前库存版本中）", "(tiada dalam versi Storage semasa)"),
    "No Material ID in Storage history contains this text. Similar IDs are never merged.": ("库存历史没有包含此文字的编号。相似编号不会合并。", "Tiada ID dalam sejarah Storage mengandungi teks ini. ID serupa tidak digabungkan."),
    "{count} matching IDs{limit}. Select one exact ID; similar IDs stay separate.": ("{count} 个匹配编号{limit}。请选择一个实际编号；相似编号保持分开。", "{count} ID sepadan{limit}. Pilih satu ID tepat; ID serupa kekal berasingan."),
    " (first {count} shown; type more)": ("（显示前 {count} 个，请输入更多文字）", " (hanya {count} pertama; taip lagi)"),
    "Select a row to see its source file, Sheet, row and version.": ("选择一行查看来源文件、Sheet、行号和版本。", "Pilih baris untuk melihat fail sumber, Sheet, baris dan versi."),
    "Select a Material ID · {banner}": ("请选择材料编号 · {banner}", "Pilih ID bahan · {banner}"),
    "Select a Material ID from the list first · {banner}": ("请先从列表选择材料编号 · {banner}", "Pilih ID bahan daripada senarai dahulu · {banner}"),
    "Storage Sheets could not be read: {error} · {banner}": ("无法读取库存 Sheet：{error} · {banner}", "Sheet Storage tidak dapat dibaca: {error} · {banner}"),
    "Querying…": ("查询中…", "Sedang menanya…"),
    "Querying {material} · {days} days · {banner}": ("正在查询 {material} · {days} 天 · {banner}", "Menanya {material} · {days} hari · {banner}"),
    "QUERY FAILED — no history is shown. Earlier results were cleared.\n{error}": ("QUERY FAILED — 查询失败，未显示历史，之前结果已清除。\n{error}", "QUERY FAILED — tiada sejarah dipaparkan. Keputusan terdahulu telah dikosongkan.\n{error}"),
    "Query failed · no results shown · {banner}": ("查询失败 · 未显示结果 · {banner}", "Pertanyaan gagal · tiada keputusan dipaparkan · {banner}"),
    "Records": ("记录", "Rekod"),
    "Observed Changes": ("观察到的变化", "Perubahan diperhatikan"),
    "{title} ({count})": ("{title}（{count}）", "{title} ({count})"),
    "Snapshot (local time)": ("快照（本地时间）", "Petikan (waktu setempat)"),
    "Description": ("描述", "Penerangan"),
    "Stock (raw)": ("库存（原值）", "Stok (asal)"),
    "Data Status": ("数据状态", "Status data"),
    "Rack": ("货架", "Rak"), "Level": ("层位", "Aras"),
    "Sheet": ("Sheet", "Sheet"), "Row": ("行号", "Baris"),
    "Source File": ("来源文件", "Fail sumber"), "Version": ("版本", "Versi"),
    "Observed at (local)": ("观察时间（本地）", "Diperhatikan (setempat)"),
    "Change": ("变化类型", "Perubahan"),
    "Before (local)": ("此前时间（本地）", "Sebelum (setempat)"),
    "Before stock": ("此前库存", "Stok sebelum"), "After stock": ("之后库存", "Stok selepas"),
    "Observed difference": ("观察差额", "Perbezaan diperhatikan"), "Note": ("原始说明", "Nota asal"),
    "all Sheets, each shown separately": ("所有 Sheet，分别显示", "semua Sheet, dipapar berasingan"),
    "{banner} for {material} · {scope} · last {days} days ({start} → {end} local time). {count} Storage snapshot(s) in the window. {covered}": ("{banner} · {material} · {scope} · 最近 {days} 天（{start} → {end}，本地时间）。范围内有 {count} 份库存快照。{covered}", "{banner} untuk {material} · {scope} · {days} hari lalu ({start} → {end} waktu setempat). {count} petikan Storage dalam julat. {covered}"),
    "Full window covered by history.": ("历史覆盖整个查询范围。", "Sejarah meliputi seluruh julat."),
    "Window NOT fully covered by history.": ("历史未覆盖整个查询范围。", "Sejarah TIDAK meliputi seluruh julat."),
    "No history for this Material ID in this range. Nothing is assumed; missing is not 0.": ("此编号在范围内没有历史。不推测缺失值；缺失不等于 0。", "Tiada sejarah ID ini dalam julat. Tiada andaian; kehilangan bukan 0."),
    "Only the first {rows} of {total_rows} records and {changes} of {total_changes} changes were loaded. Choose a Sheet or a shorter range.": ("仅载入 {total_rows} 条记录中的前 {rows} 条，以及 {total_changes} 条变化中的前 {changes} 条。请选择 Sheet 或缩短范围。", "Hanya {rows} daripada {total_rows} rekod dan {changes} daripada {total_changes} perubahan dimuatkan. Pilih Sheet atau julat lebih pendek."),
    "Original query notes (unchanged):": ("原始查询说明（保留原文）：", "Nota pertanyaan asal (tidak diubah):"),
    "Observed Change ≠ Actual Consumption": ("观察变化 ≠ 实际消耗", "Perubahan diperhatikan ≠ Penggunaan sebenar"),
    "HISTORICAL OBSERVATIONS loaded {time} · Not current stock · Cloud Not Verified": ("HISTORICAL OBSERVATIONS · 历史载入于 {time} · 非当前库存 · Cloud Not Verified", "HISTORICAL OBSERVATIONS dimuatkan {time} · Bukan stok semasa · Cloud Not Verified"),
    "Showing {shown} of {loaded} loaded{limit}": ("已显示已载入 {loaded} 条中的 {shown} 条{limit}", "Memaparkan {shown} daripada {loaded} dimuatkan{limit}"),
    " ({total} in total; the rest were not loaded — narrow the query)": ("（共 {total} 条；其余未载入，请缩小范围）", " ({total} keseluruhan; selebihnya tidak dimuatkan — kecilkan julat)"),
}

for template, (zh, ms) in TEXT.items():
    i18n.S['history:' + template] = (template, zh, ms)


def message(template, **values):
    return i18n.Message('history:' + template, **values)
