"""Stock Alerts interface resources; raw source values and stored narratives remain verbatim."""
from . import i18n
from .history_i18n import TEXT as COMMON

TEXT = {key: value for key, value in COMMON.items() if key in (
    'Storage Sheet', 'Material ID', 'Description', 'Source File', 'Close', 'Show more',
    'Observed Changes', 'Change', 'Sheet', 'Note', 'Observed at (local)', 'Before (local)',
    'Before stock', 'After stock', 'Observed difference', 'Observed Change ≠ Actual Consumption')}
TEXT.update({
    'Stock Alerts — synchronised data': ('库存提醒 — 已同步数据', 'Amaran stok — Data disegerakkan'),
    'STOCK ALERTS · From synchronised Excel data · Cloud Not Verified · Thresholds and units pending business confirmation': ('STOCK ALERTS · 来自已同步 Excel 数据 · Cloud Not Verified · 阈值及单位待业务确认', 'STOCK ALERTS · Daripada data Excel disegerakkan · Cloud Not Verified · Ambang dan unit menunggu pengesahan perniagaan'),
    'OUT_OF_STOCK ≠ order shortage · LOW_STOCK is a trial · Not in stock master = unknown, not 0 · Blank ≠ 0 · Observed Change ≠ Actual Consumption': ('OUT_OF_STOCK ≠ 订单缺料 · LOW_STOCK 为试算 · 未在库存总表找到 = 未知，不是 0 · 空白 ≠ 0 · 观察变化 ≠ 实际消耗', 'OUT_OF_STOCK ≠ kekurangan pesanan · LOW_STOCK ialah percubaan · Tiada dalam induk stok = tidak diketahui, bukan 0 · Kosong ≠ 0 · Perubahan diperhatikan ≠ Penggunaan sebenar'),
    'Material ID contains': ('编号包含', 'ID bahan mengandungi'),
    'Re-evaluate': ('重新评估', 'Nilai semula'),
    'Upgrade database…': ('升级数据库…', 'Naik taraf pangkalan data…'),
    'Type': ('类别', 'Jenis'), 'Issue': ('问题', 'Isu'),
    'Show resolved': ('显示已恢复项', 'Papar yang diselesaikan'),
    'Show other source files': ('显示其他来源文件', 'Papar fail sumber lain'),
    'All types': ('所有类别', 'Semua jenis'), 'All Sheets': ('所有 Sheet', 'Semua Sheet'),
    'All changes': ('所有变化', 'Semua perubahan'),
    'Row(s)': ('行号', 'Baris'), 'LIVE STOCK (raw)': ('LIVE STOCK（原值）', 'LIVE STOCK (asal)'),
    'Threshold (raw)': ('阈值（原值）', 'Ambang (asal)'),
    'Shortfall (trial)': ('低于阈值差额（试算）', 'Kekurangan ambang (percubaan)'),
    'First seen': ('首次发现', 'Mula dilihat'), 'Last seen': ('最近发现', 'Terakhir dilihat'),
    'Status': ('状态', 'Status'), 'Alerts': ('提醒', 'Amaran'),
    '{days} days': ('{days} 天', '{days} hari'),
    'Select a row to see its source file, rows, Rack/Level, raw values and versions.': ('选择一行查看来源文件、行号、Rack/Level、原值和版本。', 'Pilih baris untuk melihat fail sumber, baris, Rack/Level, nilai asal dan versi.'),
    'Loading stock alerts… · Cloud Not Verified': ('正在读取库存提醒… · Cloud Not Verified', 'Memuatkan amaran stok… · Cloud Not Verified'),
    'Evaluation requested · Cloud Not Verified': ('已请求评估 · Cloud Not Verified', 'Penilaian diminta · Cloud Not Verified'),
    'Re-checked in this session: the alerts of the current files come from a verified evaluation of the files this program has just checked.': ('本次会话已复核：当前文件的提醒来自本程序刚核对过的文件的已核对评估。', 'Disemak semula dalam sesi ini: amaran fail semasa datang daripada penilaian disahkan bagi fail yang baru disemak oleh program ini.'),
    'DATABASE READ FAILED · ': ('DATABASE READ FAILED · 数据库读取失败 · ', 'DATABASE READ FAILED · Bacaan pangkalan data gagal · '),
    '{prefix}NOT RE-CHECKED IN THIS SESSION — {reason}. The alerts below are stored results of earlier evaluations and may be out of date; nothing is marked recovered until a verified evaluation.': ('{prefix}NOT RE-CHECKED IN THIS SESSION — 本次会话未复核，原因：{reason}。下方为此前评估的存储结果，可能已过期；完成已核对评估前不会将提醒标记为已恢复。', '{prefix}NOT RE-CHECKED IN THIS SESSION — sebab: {reason}. Amaran di bawah ialah hasil penilaian terdahulu yang disimpan dan mungkin lapuk; tiada yang ditandakan selesai sehingga penilaian disahkan.'),
    'unknown': ('未知', 'tidak diketahui'),
    'STOCK ALERTS COULD NOT BE READ — nothing is shown. Earlier alerts were cleared from this window, not from the database.\n{error}': ('STOCK ALERTS COULD NOT BE READ — 无法读取库存提醒，未显示任何内容。旧提醒仅从本窗口清除，数据库记录保留。\n{error}', 'STOCK ALERTS COULD NOT BE READ — tiada apa dipaparkan. Amaran terdahulu dikosongkan daripada tetingkap ini, bukan pangkalan data.\n{error}'),
    'Read failed · no alerts shown · Cloud Not Verified': ('读取失败 · 未显示提醒 · Cloud Not Verified', 'Bacaan gagal · tiada amaran dipaparkan · Cloud Not Verified'),
    'Stock alerts need a one-time upgrade of the local database (schema {schema} → {required}). Nothing changes until you confirm the preview; a verified backup is made first. All other functions work without it.': ('库存提醒需要一次本地数据库升级（schema {schema} → {required}）。确认预览前不会修改；先创建校验过的备份。不升级也可使用其他功能。', 'Amaran stok memerlukan satu naik taraf pangkalan data setempat (schema {schema} → {required}). Tiada perubahan sehingga anda mengesahkan pratonton; sandaran disahkan dibuat dahulu. Fungsi lain boleh digunakan tanpanya.'),
    'Upgrade required · Cloud Not Verified': ('需要升级 · Cloud Not Verified', 'Naik taraf diperlukan · Cloud Not Verified'),
    '{count} active alerts for the current files{other} · from synchronised data · Cloud Not Verified': ('当前文件有 {count} 条活动提醒{other} · 来自已同步数据 · Cloud Not Verified', '{count} amaran aktif bagi fail semasa{other} · daripada data disegerakkan · Cloud Not Verified'),
    ' · {count} of other source files': (' · 其他来源文件另有 {count} 条', ' · {count} daripada fail sumber lain'),
    'Observed changes could not be read; none shown: {error}': ('无法读取观察变化；未显示任何项：{error}', 'Perubahan diperhatikan tidak dapat dibaca; tiada dipaparkan: {error}'),
    'Original evaluation details (unchanged):': ('原始评估详情（保留原文）：', 'Butiran penilaian asal (tidak diubah):'),
    'Showing {shown} of {filtered} (filtered from {loaded} loaded{limit})': ('已显示筛选后 {filtered} 条中的 {shown} 条（从已载入的 {loaded} 条筛选{limit}）', 'Memaparkan {shown} daripada {filtered} (ditapis daripada {loaded} dimuatkan{limit})'),
    '; {total} in total — narrow the filters': ('；共 {total} 条，请缩小筛选范围', '; {total} keseluruhan — kecilkan penapis'),
    ' · {days} days from {start} · current Storage file only': (' · 从 {start} 起 {days} 天 · 仅当前库存文件', ' · {days} hari dari {start} · fail Storage semasa sahaja'),
    'Rules: OUT_OF_STOCK = recorded 0, not a proven order shortage. LOW_STOCK is a trial (LIVE STOCK < threshold of the same row; equal is not low; the shortfall is not a production requirement). Not in stock master = stock unknown, not 0. Blank ≠ 0. Threshold 0 is kept as 0 and not interpreted. Duplicate IDs are never added. Values are never converted. Observed Change ≠ Actual Consumption. M2 CHECK rules are unchanged.': ('规则：OUT_OF_STOCK = 已登记为 0，不代表已证实订单缺料。LOW_STOCK 为试算（同一行 LIVE STOCK < 阈值；等于阈值不算低；差额不是生产需求）。未在库存总表找到 = 库存未知，不是 0。空白 ≠ 0。阈值 0 保留为 0，不作解释。重复编号不相加，不转换原值。观察变化 ≠ 实际消耗。M2 CHECK 规则保持不变。', 'Peraturan: OUT_OF_STOCK = 0 direkodkan, bukan kekurangan pesanan yang terbukti. LOW_STOCK ialah percubaan (LIVE STOCK < ambang baris sama; sama bukan rendah; kekurangan bukan keperluan pengeluaran). Tiada dalam induk stok = stok tidak diketahui, bukan 0. Kosong ≠ 0. Ambang 0 dikekalkan tanpa tafsiran. ID pendua tidak dijumlahkan. Nilai tidak ditukar. Perubahan diperhatikan ≠ Penggunaan sebenar. Peraturan M2 CHECK tidak berubah.'),
})
for template, (zh, ms) in TEXT.items():
    i18n.S['alerts:' + template] = (template, zh, ms)


def message(template, **values):
    return i18n.Message('alerts:' + template, **values)
