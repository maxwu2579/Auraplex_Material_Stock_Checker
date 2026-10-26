"""Deterministic, conservative reply-language routing. Source identifiers are never translated."""
import re
import unicodedata

LANGUAGES = ('en', 'zh', 'ms')
EN = set('please check stock available how much many lookup find show what is are for material inventory low '
         'history change changes need make produce units quantity shortage of the can you tell me current '
         'search compare report yesterday today help balance remaining credit answer in english chinese malay'.split())
MS = set('berapa baki stok semak cari papar tunjuk sila bahan rendah sejarah perubahan untuk ada adakah '
         'boleh saya kuantiti kekurangan hasilkan unit ini itu dengan dan daripada laporan hari tolong '
         'jawab bahasa dalam inggeris cina melayu'.split())
SHARED = {'status', 'material', 'minimum', 'maximum', 'min', 'max', 'data', 'normal', 'total', 'unit', 'units', 'item', 'model', 'excel'}
TECHNICAL = re.compile(r'\b(?:BOM|PCS|SET|KG|SQL|API|MIN\s+QTY|MIIN\s+QTY|LIVE\s+STOCK|Sheet|Token|Tokens)\b', re.I)
IDENTIFIER = re.compile(r'[A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*|\b[A-Z]{2,}(?:[-_/][A-Z]+)+\b|\b[^\s]+\.(?:xlsx|xlsm|csv)\b')
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`|(?<![A-Za-z])\'[^\'\n]*\'(?![A-Za-z])')
EXPLICIT = (
    ('zh', r'(?:answer|reply|respond)\s+in\s+(?:chinese|mandarin)|(?:用|以)中文(?:回答|回复)?|(?:jawab|balas)\s+dalam\s+bahasa\s+cina'),
    ('ms', r'(?:answer|reply|respond)\s+in\s+(?:malay|bahasa\s+melayu)|(?:用|以)(?:马来文|马来语)(?:回答|回复)?|(?:jawab|balas)\s+dalam\s+bahasa\s+melayu'),
    ('en', r'(?:answer|reply|respond)\s+in\s+english|(?:用|以)(?:英文|英语)(?:回答|回复)?|(?:jawab|balas)\s+dalam\s+bahasa\s+inggeris'),
)


def route(question, previous='en', preferred='auto', protected=()):
    """Return (language, uncertain). Shared/unknown Latin words alone do not prove English mixing.

    This bounded lexical heuristic is intentionally not a universal language detector. The host offers
    an explicit language selector. Quoted source text, known Sheet/file labels and model IDs are excluded.
    """
    text = unicodedata.normalize('NFKC', question)
    text = QUOTED.sub(' ', text)
    for value in sorted(set(protected), key=len, reverse=True):
        if value:
            normalized = unicodedata.normalize('NFKC', value)
            pattern = (r'(?<![A-Za-z0-9_])' if normalized[0].isascii() and normalized[0].isalnum() else '')
            pattern += re.escape(normalized)
            pattern += r'(?![A-Za-z0-9_])' if normalized[-1].isascii() and normalized[-1].isalnum() else ''
            text = re.sub(pattern, ' ', text, flags=re.I)
    for language, pattern in EXPLICIT:
        if re.search(pattern, text, re.I):
            return language, False
    if preferred in LANGUAGES:
        return preferred, False
    text = IDENTIFIER.sub(' ', TECHNICAL.sub(' ', text))
    words = set(re.findall(r'[a-z]+', text.lower())) - SHARED
    if words & EN:
        return 'en', False
    if words & MS:
        return 'ms', False
    if re.search(r'[\u3400-\u9fff]', text):
        return 'zh', False
    return previous if previous in LANGUAGES else 'en', True


TEXT = {
    'direct_mode': ('DeepSeek on Send · recorded data only · UNVERIFIED', '发送时调用 DeepSeek · 仅已有数据 · UNVERIFIED', 'DeepSeek semasa Hantar · data direkod sahaja · UNVERIFIED'),
    'load_recorded': ('Load recorded data', '读取已有数据', 'Muat data direkod'),
    'send_disclosure': ('Send uses DeepSeek and limited inventory tool data. UNVERIFIED.',
                        '发送会使用 DeepSeek，并外发受限库存查询数据。UNVERIFIED。',
                        'Hantar menggunakan DeepSeek dan data alat inventori terhad. UNVERIFIED.'),

    'history': ('UNVERIFIED · Historical SQLite observations · Cloud Not Verified',
                'UNVERIFIED · SQLite 历史记录 · Cloud Not Verified',
                'UNVERIFIED · Pemerhatian sejarah SQLite · Cloud Not Verified'),
    'caveat': ('Blank means not recorded; duplicates are not added. Observed change is not actual consumption. Estimates are not production approval.',
               '空白表示没有记录；重复编号不相加。观察到的变化不等于实际消耗；试算不是生产批准。',
               'Kosong bermaksud tiada rekod; ID pendua tidak dijumlahkan. Perubahan diperhatikan bukan penggunaan sebenar. Anggaran bukan kelulusan pengeluaran.'),
    'welcome': ('Save a key in Settings, then type and Send. Send uses DeepSeek and limited inventory tool data. Local tools work offline after Load recorded data. All observations are UNVERIFIED; not production approval.',
                '在设置中保存 Key 后，输入问题直接发送。发送会使用 DeepSeek 并外发受限库存查询数据。本地工具可在读取已有数据后离线使用。所有观察均为 UNVERIFIED，不是生产批准。',
                'Simpan kunci dalam Settings, kemudian taip dan Hantar. Hantar menggunakan DeepSeek dan data alat inventori terhad. Alat tempatan boleh digunakan luar talian selepas memuat data. Semua pemerhatian UNVERIFIED; bukan kelulusan pengeluaran.'),
    'uncertain': ('Language unclear; using the previous/default reply language. You can select a language above.',
                  '语言不明确，沿用上次或默认回复语言；可在上方手动选择。',
                  'Bahasa kurang jelas; bahasa jawapan sebelumnya/lalai digunakan. Anda boleh memilih bahasa di atas.'),
    'cancelled': ('Stopped. Late results will not be displayed.', '已停止；迟到结果不会显示。', 'Dihentikan. Hasil lewat tidak akan dipaparkan.'),
    'invalidated': ('The data/session basis changed. Earlier answers are historical only. Send again to use the newly recorded snapshot; no permission dialog is needed.',
                    '数据或会话依据已变化；之前回答仅作历史参考。重新发送即可读取新的已有快照，无需再次授权。',
                    'Asas data/sesi berubah. Jawapan terdahulu hanya sejarah. Hantar semula untuk menggunakan syot kilat terkini yang direkod; tiada dialog izin diperlukan.'),
    'consent': ('Use these historical SQLite versions? Sources have NOT been checked by this assistant. Blank is not zero; duplicates are separate. No production approval. This permission does not authorize any API transmission.',
                '使用这些 SQLite 历史版本？助手没有核对源 Excel；空白不是零，重复记录保持分开。不是生产批准。此授权不允许向 API 外发资料。',
                'Gunakan versi sejarah SQLite ini? Pembantu BELUM menyemak sumber Excel. Kosong bukan sifar; pendua berasingan. Bukan kelulusan pengeluaran. Izin ini tidak membenarkan penghantaran API.'),
    'authorized': ('Historical data selected for this session only. UNVERIFIED.', '已为本次会话选择历史数据。UNVERIFIED。', 'Data sejarah dipilih untuk sesi ini sahaja. UNVERIFIED.'),
    'denied': ('Permission declined. No query or API request was authorized.', '已拒绝授权；未授权查询或 API 请求。', 'Izin ditolak. Tiada carian atau permintaan API dibenarkan.'),
    'outbound': ('Allow this session to send questions, fixed tool definitions, requested arguments and candidate IDs/Sheets to DeepSeek, and check account balance? Numerical stock evidence stays local. Questions/IDs may be sensitive. Review the exact first request below. Default is No.',
                 '允许本次会话将问题、固定工具、请求参数和候选编号/Sheet 发送至 DeepSeek，并查询账户余额？库存数值证据留在本机；问题和编号也可能敏感。请检查下方首次请求预览。默认拒绝。',
                 'Benarkan sesi ini menghantar soalan, definisi alat tetap, argumen dan calon ID/Sheet kepada DeepSeek serta menyemak baki akaun? Bukti angka stok kekal setempat. Soalan/ID mungkin sensitif. Semak pratonton permintaan pertama di bawah. Lalai ialah Tidak.'),
    'connected': ('AI outbound permission enabled for this session. No request has been sent by granting permission.',
                  '本次会话已允许 AI 外发；授权动作本身没有发送请求。',
                  'Izin penghantaran AI dibenarkan untuk sesi ini. Pemberian izin sendiri tidak menghantar permintaan.'),
    'select': ('Choose one actual candidate in Local tools (or type the full ID). Similar IDs and different Sheets stay separate.',
               '请在「本地工具」页选择一个实际候选（或输入完整编号）；相似编号及不同 Sheet 保持分开。',
               'Pilih satu calon sebenar dalam Local tools (atau taip ID penuh). ID serupa dan Sheet berbeza kekal berasingan.'),
    'no_results': ('No matching recorded rows. Missing stock is unknown, not zero.', '没有匹配记录；缺失库存是未知，不是零。', 'Tiada rekod sepadan. Stok tiada rekod tidak diketahui, bukan sifar.'),
    'omitted': ('Additional rows omitted here; see Evidence (bounded tool output).', '此处省略其余行；可查看 Evidence 中的受限工具结果。', 'Baris tambahan tidak dipaparkan di sini; lihat Evidence (hasil alat terhad).'),
    'observed': ('Observed at', '观察时间', 'Diperhatikan pada'),
    'source': ('Source / Sheet / row', '来源 / Sheet / 行号', 'Sumber / Sheet / baris'),
    'raw': ('Recorded stock', '记录库存', 'Stok direkod'),
    'blank': ('NOT RECORDED — not 0', '未记录 — 不是 0', 'TIADA REKOD — bukan 0'),
    'required': ('Estimated required', '试算需求', 'Keperluan anggaran'),
    'shortage': ('Estimated shortage', '试算缺口', 'Kekurangan anggaran'),
    'assumed': ('M2 row estimate assumes 0; original stock is unknown', 'M2 行级试算假设 0；原库存仍未知', 'Anggaran baris M2 mengandaikan 0; stok asal masih tidak diketahui'),
    'counts': ('Category counts overlap where stated; do not add alert counts as distinct materials.', '提醒分类可能重叠；不可相加当作材料总数。', 'Kategori amaran boleh bertindih; jangan jumlahkan sebagai bahan berbeza.'),
    'error': ('Cannot complete this request', '本次请求无法完成', 'Permintaan ini tidak dapat diselesaikan'),
    'quota_unknown': ('API credit unknown', 'API 额度未知', 'Kredit API tidak diketahui'),
    'due': ('Recheck due', '待重新核对', 'Perlu disemak semula'),
    'usage': ('Last request Token usage (not remaining)', '上次请求 Token 用量（不是剩余）', 'Penggunaan Token permintaan terakhir (bukan baki)'),
    'armed': ('Balance will be rechecked on the next authorized Send. No request sent now.', '下次已授权的 Send 将重新检查余额；现在未发送请求。', 'Baki akan disemak pada Send berizin seterusnya. Tiada permintaan dihantar sekarang.'),
    'saved_key': ('Key saved in your Windows vault. Type a question and Send.', 'Key 已保存至当前用户的 Windows 凭据库；输入问题后直接发送。', 'Kunci disimpan dalam Windows vault anda. Taip soalan dan Hantar.'),
    'deleted_key': ('Key removed from your Windows vault; outbound permission revoked.', '已从当前用户凭据库移除 Key，并撤销外发授权。', 'Kunci dipadam daripada Windows vault anda; izin penghantaran dibatalkan.'),
    'coverage': ('History coverage', '历史覆盖范围', 'Liputan sejarah'),
    'days': ('days', '天', 'hari'),
    'rows': ('rows', '行', 'baris'),
    'changes': ('observed changes', '观察到的变化', 'perubahan diperhatikan'),
    'snapshots': ('snapshots', '快照', 'syot kilat'),
    'full': ('Full window covered', '覆盖整个时间窗', 'Seluruh tempoh diliputi'),
    'reference': ('Before-window reference', '时间窗之前的参考', 'Rujukan sebelum tempoh'),
    'movement': ('Observed movement', '观察到的变动', 'Pergerakan diperhatikan'),
    'net': ('Observed net change', '观察到的净变化', 'Perubahan bersih diperhatikan'),
    'span': ('Observed span in days', '实际观察跨度（天）', 'Rentang pemerhatian dalam hari'),
    'unknown': ('Not calculated / unknown', '未计算 / 未知', 'Tidak dikira / tidak diketahui'),
    'rechecked': ('NOT RE-CHECKED — recorded alerts only', '未重新核对 — 仅历史提醒', 'BELUM DISEMAK SEMULA — amaran direkod sahaja'),
    'imported': ('Imported at', '导入时间', 'Diimport pada'),
    'api_consent': ('API consent', 'API 外发授权', 'Izin API'),
    'recorded_only': ('Recorded sync logs only. This assistant has NOT checked Excel; unrecorded failures and current source/cloud freshness are unknown.',
                      '以下仅为历史同步日志。助手没有核对 Excel；未记入日志的失败、当前文件和云端新鲜度均未知。',
                      'Log penyegerakan direkod sahaja. Pembantu BELUM menyemak Excel; kegagalan tidak direkod dan kesegaran sumber/awan semasa tidak diketahui.'),
    'recorded_sync': ('Recorded sync attempt', '历史同步尝试', 'Cubaan penyegerakan direkod'),
    'report_tab': ('AI reports', 'AI 报告', 'Laporan AI'),
    'report_details_show': ('Show details ▸', '显示明细 ▸', 'Papar butiran ▸'),
    'report_details_hide': ('Hide details ▾', '隐藏明细 ▾', 'Sembunyi butiran ▾'),
    'report_details_title': ('Details and data basis (canonical codes kept)', '明细与数据依据（保留原始代码）',
                             'Butiran dan asas data (kod asal dikekalkan)'),
    'details_button': ('Details', '明细', 'Butiran'),
    # Chat answers: business wording first; Evidence keeps every row, the data basis and the JSON.
    'c_status': ('Data status: {asof} · UNVERIFIED · Cloud Not Verified', '数据状态：{asof} · 未复核（UNVERIFIED）· Cloud Not Verified',
                 'Status data: {asof} · UNVERIFIED · Cloud Not Verified'),
    'c_asof': ('{role} data as of {time}', '{role}数据截至 {time}', 'data {role} setakat {time}'),
    'c_asof_unknown': ('data time unknown', '数据时间未知', 'masa data tidak diketahui'),
    'c_stale': ('{role}: the latest sync failed ({time}); this answer uses earlier data and may be out of date.',
                '{role}：最近一次同步失败（{time}）；本回答使用之前的数据，可能已过期。',
                '{role}: penyegerakan terakhir gagal ({time}); jawapan ini menggunakan data terdahulu dan mungkin lapuk.'),
    'c_stale_unavailable': ('{role}: the source file was unavailable at the latest check ({time}); this answer uses earlier recorded data and may be out of date.',
                            '{role}：最近一次检查时源文件不可用（{time}）；本回答使用之前记录的数据，可能已过期。',
                            '{role}: fail sumber tidak tersedia pada semakan terakhir ({time}); jawapan ini menggunakan data direkod terdahulu dan mungkin lapuk.'),
    'c_never': ('{role}: never synchronised; no data for it.', '{role}：尚未同步，没有相关数据。', '{role}: belum pernah disegerakkan; tiada data.'),
    'c_shown_only': ('Showing {shown}.', '显示 {shown} 项。', 'Memaparkan {shown}.'),
    'c_capped': ('Loaded {loaded} of {total}: the read limit was reached, so Details are incomplete too.',
                 '已载入 {loaded} 项，共 {total} 项：已达读取上限，明细也不完整。',
                 'Dimuatkan {loaded} daripada {total}: had bacaan dicapai, jadi Butiran juga tidak lengkap.'),
    'c_narrow_search': ('Type a longer part of the ID to narrow the search.', '请输入更完整的编号以缩小范围。',
                        'Taip bahagian ID yang lebih panjang untuk mengecilkan carian.'),
    'c_narrow_history': ('Choose a shorter range (30/60 days) to see every row of it.', '可改选较短的天数（30/60 天）以查看该范围的全部记录。',
                         'Pilih julat lebih pendek (30/60 hari) untuk melihat semua barisnya.'),
    'c_narrow_alerts': ('Use the Stock Alerts window filters (type, material, Sheet) for the rest.', '其余提醒可在「库存提醒」窗口按类型、材料或 Sheet 筛选查看。',
                        'Gunakan penapis tetingkap Stock Alerts (jenis, bahan, Sheet) untuk selebihnya.'),
    'c_latest_absent': ('Latest snapshot {time}: this ID was not found in it (not 0).', '最新快照 {time}：未找到该编号（不是 0）。',
                        'Syot terkini {time}: ID ini tiada di dalamnya (bukan 0).'),
    'c_latest_pruned': ('Latest snapshot {time}: its rows were removed by history cleanup; quantity unknown (not 0).',
                        '最新快照 {time}：该时点的记录已被历史清理，数量未知（不是 0）。',
                        'Syot terkini {time}: barisnya dibuang oleh pembersihan sejarah; kuantiti tidak diketahui (bukan 0).'),
    'c_last_qty': ('Last recorded quantity {time}: {qty} (Sheet {sheet!r})', '上次有数量的记录 {time}：{qty}（Sheet {sheet!r}）',
                   'Kuantiti direkod terakhir {time}: {qty} (Sheet {sheet!r})'),
    'c_other_source': (' · from {file}', ' · 来自 {file}', ' · daripada {file}'),
    'c_details': ('Full rows and data basis: Details (Evidence tab).', '完整明细与数据依据：点「明细」（Evidence 页）。',
                  'Baris penuh dan asas data: Butiran (tab Evidence).'),
    'c_details_title': ('DETAILS (every returned row)', '明细（全部返回行）', 'BUTIRAN (semua baris dipulangkan)'),
    'c_basis_title': ('DATA BASIS (sources, versions, hashes, recorded sync)', '数据依据（来源、版本、哈希、同步记录）',
                      'ASAS DATA (sumber, versi, hash, penyegerakan direkod)'),
    'c_json_title': ('TECHNICAL DETAILS (canonical JSON)', '技术详情（原始 JSON）', 'BUTIRAN TEKNIKAL (JSON asal)'),
    'c_shown': ('Showing {shown} of {total}; see Details for the rest.', '显示 {shown} 项，共 {total} 项；其余见明细。',
                'Memaparkan {shown} daripada {total}; selebihnya dalam Butiran.'),
    'c_not_found': ('Material ID {id} was not found in the stock list. This is not zero stock.',
                    '库存表未找到编号 {id}。这不是零库存。',
                    'ID bahan {id} tiada dalam senarai stok. Ini bukan stok sifar.'),
    'c_duplicate': ('{id}: several records ({count}) — quantities are not merged. Check each row:',
                    '{id}：存在多条记录（{count} 条），数量未合并，请逐条核对：',
                    '{id}: beberapa rekod ({count}) — kuantiti tidak digabung. Semak setiap baris:'),
    'c_sheets': ('{id} appears in {count} Sheets; each is shown separately:', '{id} 出现在 {count} 个 Sheet，分别显示：',
                 '{id} terdapat dalam {count} Sheet; setiap satu dipaparkan berasingan:'),
    'c_blank': ('not recorded yet (not 0)', '尚未登记（不是 0）', 'belum direkod (bukan 0)'),
    'c_text_qty': ('quantity to be confirmed (original: {raw})', '数量待确认（原值：{raw}）', 'kuantiti perlu disahkan (asal: {raw})'),
    'c_location': ('Location: Rack {rack} / Level {level}', '位置：Rack {rack} / Level {level}', 'Lokasi: Rack {rack} / Level {level}'),
    'c_source_row': ('Sheet {sheet!r}, row {row}', 'Sheet {sheet!r} 第 {row} 行', 'Sheet {sheet!r}, baris {row}'),
    'c_candidates': ('Found {total} possible materials. Please choose one (nothing has been assumed):',
                     '找到 {total} 个可能的材料，请选择其中一个（未自动认定）：',
                     'Ditemui {total} bahan yang mungkin. Sila pilih satu (tiada andaian dibuat):'),
    'c_products': ('Found {total} possible products. Please choose one:', '找到 {total} 个可能的产品，请选择其中一个：',
                   'Ditemui {total} produk yang mungkin. Sila pilih satu:'),
    'c_one_candidate': ('Found {total} match:', '找到 {total} 个匹配：', 'Ditemui {total} padanan:'),
    'c_bom': ('Product {product}: {count} BOM rows (BOM not verified).', '产品 {product}：BOM 共 {count} 行（BOM 未复核）。',
              'Produk {product}: {count} baris BOM (BOM belum disahkan).'),
    'c_bom_qty': ('qty {qty}', '用量 {qty}', 'kuantiti {qty}'),
    'c_bom_qty_blank': ('qty not recorded', '用量未登记', 'kuantiti tidak direkod'),
    'c_estimate': ('Product {product} × {count} (estimate from recorded stock, UNVERIFIED): short {short} · exceptions {exceptions} · enough {enough}',
                   '产品 {product} × {count}（按记录库存试算，未复核）：缺料 {short} 项 · 异常 {exceptions} 项 · 足够 {enough} 项',
                   'Produk {product} × {count} (anggaran daripada stok direkod, UNVERIFIED): kurang {short} · pengecualian {exceptions} · mencukupi {enough}'),
    'c_short_title': ('Main shortages:', '主要缺料：', 'Kekurangan utama:'),
    'c_no_short': ('No estimated shortage. This does not mean production can start; check the exceptions.',
                   '试算没有缺料。这不代表可以生产；请核对异常项。',
                   'Tiada kekurangan anggaran. Ini tidak bermakna pengeluaran boleh bermula; semak pengecualian.'),
    'c_exc_title': ('Exceptions to check:', '需要核对的异常：', 'Pengecualian untuk disemak:'),
    'c_estimate_note': ('Row-level estimate assuming the same unit and QTY per product unit; not a production or purchase decision.',
                        '行级试算，假设单位一致且 QTY 为单件用量；不是生产或采购决定。',
                        'Anggaran peringkat baris dengan unit sama dan QTY bagi setiap unit produk; bukan keputusan pengeluaran atau pembelian.'),
    'c_history': ('{id}, last {days} days: {changes} observed changes, {rows} records (observed change is not actual consumption).',
                  '{id} 近 {days} 天：观察到 {changes} 次变化、{rows} 条记录（观察变化不等于实际消耗）。',
                  '{id}, {days} hari lepas: {changes} perubahan diperhatikan, {rows} rekod (perubahan diperhatikan bukan penggunaan sebenar).'),
    'c_history_none': ('No stock history yet: no conclusion is possible.', '还没有库存历史，无法下结论。',
                       'Belum ada sejarah stok: tiada kesimpulan boleh dibuat.'),
    'c_history_short': ('History is incomplete: records start {time}, so the full {days} days are not covered; no conclusion about the missing part.',
                        '历史不足：记录从 {time} 开始，未覆盖完整 {days} 天，缺失部分无法下结论。',
                        'Sejarah tidak lengkap: rekod bermula {time}, jadi {days} hari penuh tidak diliputi; tiada kesimpulan bagi bahagian yang tiada.'),
    'c_history_switch': ('The source file was switched {count} time(s) in this range; quantities across a switch are not comparable.',
                         '这段时间更换过 {count} 次数据源；更换前后的数量不可比较。',
                         'Fail sumber ditukar {count} kali dalam julat ini; kuantiti merentasi pertukaran tidak boleh dibanding.'),
    'c_latest': ('Latest record {time}: {qty} (Sheet {sheet!r})', '最近记录 {time}：{qty}（Sheet {sheet!r}）',
                 'Rekod terkini {time}: {qty} (Sheet {sheet!r})'),
    'c_analysis': ('{id} · Sheet {sheet!r}, last {days} days: {movement_label} {movement} · {net_label} {net} · observed over {span} days',
                   '{id} · Sheet {sheet!r} 近 {days} 天：{movement_label} {movement} · {net_label} {net} · 观察跨度 {span} 天',
                   '{id} · Sheet {sheet!r}, {days} hari lepas: {movement_label} {movement} · {net_label} {net} · diperhatikan {span} hari'),
    'c_observed': ('Observed change ≠ actual consumption.', '观察变化 ≠ 实际消耗。', 'Perubahan diperhatikan ≠ penggunaan sebenar.'),
    'c_alerts_upgrade': ("Alerts need the upgraded local database; alert counts are unknown (not 'no alerts').",
                         '需要先升级本机数据库才能显示提醒；提醒数量未知（不代表没有提醒）。',
                         "Amaran memerlukan pangkalan data setempat dinaik taraf; bilangan amaran tidak diketahui (bukan 'tiada amaran')."),
    'c_alerts_not_evaluated': ("Alerts have not been evaluated yet; counts are unknown (not 'no alerts').",
                               '尚未评估提醒；数量未知（不代表没有提醒）。',
                               "Amaran belum dinilai; bilangan tidak diketahui (bukan 'tiada amaran')."),
    'c_alerts': ('Recorded stock alerts (not re-checked; evaluated {time}):', '已记录的库存提醒（未重新检查；评估于 {time}）：',
                 'Amaran stok direkod (tidak disemak semula; dinilai {time}):'),
    'c_alert_count': ('{label}: {count} entries', '{label}：{count} 条', '{label}: {count} catatan'),
    'c_role_state': ('{role}: {state} · last check {checked} · data imported {imported}',
                     '{role}：{state} · 最近检查 {checked} · 数据导入于 {imported}',
                     '{role}: {state} · semakan terakhir {checked} · data diimport {imported}'),
    'report_intro': ('Build a local daily or weekly summary from retained SQLite observations. Counts stay visible here; any AI interpretation is a separate, per-report opt-in.',
                     '从本地 SQLite 历史记录生成日报或周报。具体计数保留在本机；每份 AI 解读都需单独选择授权。',
                     'Bina ringkasan harian atau mingguan daripada pemerhatian SQLite setempat. Kiraan kekal di sini; tafsiran AI memerlukan izin berasingan bagi setiap laporan.'),
    'report_period': ('Period', '周期', 'Tempoh'),
    'report_build': ('Build local preview', '生成本地预览', 'Bina pratonton setempat'),
    'report_send': ('Ask AI to interpret…', '请 AI 解读…', 'Minta AI mentafsir…'),
    'report_no_data': ('Select historical data before building a report.', '生成报告前，请先选择历史数据。', 'Pilih data sejarah sebelum membina laporan.'),
    'report_preview_ready': ('Local aggregate preview is ready. It has not been sent to AI.',
                             '本地汇总预览已生成，尚未发送给 AI。',
                             'Pratonton agregat setempat sedia. Ia belum dihantar kepada AI.'),
    'report_interpretation': ('AI interpretation · UNVERIFIED historical observations · Cloud Not Verified',
                              'AI 解读 · UNVERIFIED 历史观察 · Cloud Not Verified',
                              'Tafsiran AI · pemerhatian sejarah UNVERIFIED · Cloud Not Verified'),
    'report_review_caveat': ('Review this qualitative explanation against the displayed local counts. Observed changes are not confirmed consumption; this is not a current-stock or production decision.',
                             '请结合本机显示的计数人工复核这段定性说明。观察到的变化不等于实际消耗；此内容不是实时库存或生产决策。',
                             'Semak penjelasan kualitatif ini dengan kiraan setempat. Perubahan diperhatikan bukan penggunaan sebenar; ini bukan keputusan stok semasa atau pengeluaran.'),
    'report_disclosure': ('This single report request sends only the aggregate report window, observation counts (split into same-source changes, differences caused by a source-file switch and first imports), alert category counts with their distinct-material counts, recorded sync outcomes/times, history coverage and data-quality category counts shown in the exact request below. It excludes Material IDs, descriptions, individual stock/BOM quantities, Sheet names, local paths, file hashes and database rows. The report is UNVERIFIED historical SQLite data; Cloud Not Verified. This does not send a workbook or the full database. A separate account-balance check may occur under your existing API consent if due. No is the default.',
                          '本次单独的报告请求只会发送下方准确请求中展示的汇总时间窗、观察变化计数（分为同源变化、更换数据源造成的差异和首次导入）、提醒分类计数及其不同材料数、历史同步结果/时间、历史覆盖状态和数据质量分类计数。不发送材料编号、描述、单项库存/BOM 数量、Sheet 名、路径、文件哈希或数据库行。报告是 UNVERIFIED 的 SQLite 历史数据；Cloud Not Verified。不发送工作簿或完整数据库。如已有 API 授权且余额检查到期，可能另行检查 API 账户余额。默认选择“否”。',
                          'Permintaan laporan ini hanya menghantar tempoh agregat, kiraan perubahan (sumber sama, perbezaan akibat pertukaran fail sumber dan import pertama), kiraan kategori amaran dengan bilangan bahan berbeza, hasil/masa penyegerakan direkod, liputan sejarah dan kiraan kategori kualiti data seperti dalam permintaan tepat di bawah. ID bahan, penerangan, kuantiti stok/BOM individu, nama Sheet, laluan setempat, hash fail dan baris pangkalan data dikecualikan. Laporan ialah data sejarah SQLite UNVERIFIED; Cloud Not Verified. Buku kerja dan pangkalan data penuh tidak dihantar. Semakan baki akaun berasingan mungkin berlaku di bawah izin API sedia ada jika sudah tiba masanya. Pilihan lalai ialah Tidak.'),
    'report_confirm_title': ('One-time AI report consent / 单次 AI 报告授权 / Izin laporan AI sekali sahaja',
                             '单次 AI 报告授权',
                             'Izin laporan AI sekali sahaja'),
    'report_declined': ('This report was declined; no report request was sent.',
                        '已拒绝本份报告；没有发送报告请求。',
                        'Laporan ini ditolak; tiada permintaan laporan dihantar.'),
    'daily': ('Daily', '日报', 'Harian'),
    'weekly': ('Weekly', '周报', 'Mingguan'),
    # M4F delivery (save HTML + JSON, .eml draft). Nothing is sent.
    'report_save': ('Save report (HTML + JSON)…', '保存报告（HTML + JSON）…', 'Simpan laporan (HTML + JSON)…'),
    'report_email': ('E-mail draft (.eml)…', '生成邮件草稿（.eml）…', 'Draf e-mel (.eml)…'),
    'report_include_ai': ('Include the AI interpretation', '附入 AI 解读', 'Sertakan tafsiran AI'),
    'report_no_ai': ('No valid AI interpretation for this preview; only local statistics will be saved.',
                     '当前预览没有有效的 AI 解读；只保存本地统计。',
                     'Tiada tafsiran AI sah bagi pratonton ini; hanya statistik setempat akan disimpan.'),
    'report_ai_ready': ('A valid AI interpretation ({language}) is available for this preview. It is saved only if you tick the box, as a separate UNVERIFIED section.',
                        '当前预览有一份有效的 AI 解读（{language}）。只有勾选后才会作为独立的 UNVERIFIED 部分保存。',
                        'Tafsiran AI sah ({language}) tersedia untuk pratonton ini. Ia disimpan hanya jika ditanda, sebagai bahagian UNVERIFIED berasingan.'),
    'report_saving': ('Saving the report in the background…', '正在后台保存报告…', 'Menyimpan laporan di latar belakang…'),
    'report_saved': ('Report saved (UNVERIFIED · Cloud Not Verified): {path}', '报告已保存（UNVERIFIED · Cloud Not Verified）：{path}',
                     'Laporan disimpan (UNVERIFIED · Cloud Not Verified): {path}'),
    'report_save_failed': ('The report was not saved: {error}', '报告未保存：{error}', 'Laporan tidak disimpan: {error}'),
    'report_need_save': ('Save the report for the current preview first. After a new preview, another language or a different AI choice, save again; the draft attaches exactly that saved report.',
                         '请先保存当前预览的报告。重新生成预览、切换语言或改变 AI 解读选择后，需要重新保存；草稿只附上该份已保存的报告。',
                         'Simpan laporan bagi pratonton semasa dahulu. Selepas pratonton baharu, bahasa lain atau pilihan AI berbeza, simpan semula; draf hanya melampirkan laporan yang disimpan itu.'),
    'report_saved_other': ('That report belongs to an earlier preview; it stays on disk but will not be used for the e-mail draft of the current preview.',
                           '该报告属于之前的预览；文件保留在磁盘上，但不会用于当前预览的邮件草稿。',
                           'Laporan itu milik pratonton terdahulu; ia kekal dalam cakera tetapi tidak digunakan untuk draf e-mel pratonton semasa.'),
    'delivery_busy': ('A report file is still being written. Please wait.', '报告文件仍在写入，请稍候。',
                      'Fail laporan masih ditulis. Sila tunggu.'),
    'email_title': ('E-mail draft preview — not sent', '邮件草稿预览 — 不会发送', 'Pratonton draf e-mel — tidak dihantar'),
    'email_notice': ('This creates a local .eml draft only. Nothing is sent, no mail program is opened and no mail account is used. Mail programs may open .eml files differently.',
                     '只生成本地 .eml 草稿。不发送、不打开邮件程序、不使用任何邮箱账户。不同邮件程序打开 .eml 的方式可能不同。',
                     'Ini hanya mencipta draf .eml setempat. Tiada apa dihantar, tiada program e-mel dibuka dan tiada akaun e-mel digunakan. Program e-mel mungkin membuka fail .eml secara berbeza.'),
    'email_to': ('To (optional)', '收件人（可选）', 'Kepada (pilihan)'),
    'email_subject': ('Subject', '标题', 'Subjek'),
    'email_attachments': ('Attachments', '附件', 'Lampiran'),
    'email_save': ('Save .eml draft…', '保存 .eml 草稿…', 'Simpan draf .eml…'),
    'email_cancel': ('Cancel', '取消', 'Batal'),
    'email_saved': ('E-mail draft saved (not sent): {path}', '邮件草稿已保存（未发送）：{path}', 'Draf e-mel disimpan (tidak dihantar): {path}'),
    'email_failed': ('The e-mail draft was not saved: {error}', '邮件草稿未保存：{error}', 'Draf e-mel tidak disimpan: {error}'),
    # M4F local report preview. Placeholders are filled with the unchanged facts; codes stay canonical.
    'rp_title': ('{period} report · UNVERIFIED historical observations · Cloud Not Verified',
                 '{period} · UNVERIFIED 历史观察 · Cloud Not Verified',
                 'Laporan {period} · pemerhatian sejarah UNVERIFIED · Cloud Not Verified'),
    'rp_generated': ('Generated (UTC): {value}', '生成时间（UTC）：{value}', 'Dijana (UTC): {value}'),
    'rp_current': ('Current period', '本期', 'Tempoh semasa'),
    'rp_previous': ('Previous period', '上期', 'Tempoh sebelumnya'),
    'rp_stats': ('Coverage: {coverage} · Snapshots: {snapshots} · Storage sync attempts: {attempts} · Successful Storage checks: {checks} · Observed change events: {events} · Distinct material IDs: {ids}',
                 '历史覆盖：{coverage} · 快照：{snapshots} · Storage 同步尝试：{attempts} · Storage 成功核对：{checks} · 观察到的变化事件：{events} · 涉及不同材料编号：{ids}',
                 'Liputan: {coverage} · Syot: {snapshots} · Cubaan penyegerakan Storage: {attempts} · Semakan Storage berjaya: {checks} · Peristiwa perubahan diperhatikan: {events} · ID bahan berbeza: {ids}'),
    'rp_type': ('  {kind}: {events} events / {ids} distinct IDs', '  {kind}：{events} 次事件 / {ids} 个不同编号',
                '  {kind}: {events} peristiwa / {ids} ID berbeza'),
    'rp_split': ('  Same source: {same} events / {ids} IDs · caused by a source switch: {cross} (not inventory activity) · first imports: {baselines}',
                 '  同源：{same} 次事件 / {ids} 个编号 · 更换数据源造成：{cross}（不是库存活动）· 首次导入：{baselines}',
                 '  Sumber sama: {same} peristiwa / {ids} ID · akibat pertukaran sumber: {cross} (bukan aktiviti inventori) · import pertama: {baselines}'),
    'rp_comparison': ('Weekly comparison: {status}', '周对比：{status}', 'Perbandingan mingguan: {status}'),
    'rp_delta': ('  {kind} event-count delta: {delta}', '  {kind} 事件数差值（同源）：{delta}', '  {kind} beza kiraan peristiwa (sumber sama): {delta}'),
    'rp_unknown': ('unknown', '未知', 'tidak diketahui'),
    'rp_alerts': ('Recorded alerts: {status} · evaluated (UTC): {value}', '已记录提醒：{status} · 评估时间（UTC）：{value}',
                  'Amaran direkod: {status} · dinilai (UTC): {value}'),
    'rp_alerts_unknown': ('  Counts: unknown; no current stored evaluation is available.',
                          '  数量：未知；没有对应当前版本的已存评估。',
                          '  Kiraan: tidak diketahui; tiada penilaian tersimpan bagi versi semasa.'),
    'rp_sync': ('Latest recorded sync attempts:', '最近一次记录的同步尝试：', 'Cubaan penyegerakan terakhir direkod:'),
    'rp_quality': ('Recorded data quality:', '已记录的数据质量：', 'Kualiti data direkod:'),
    'rp_storage_unknown': ('  Latest retained Storage snapshot counts: unknown', '  最新保留的 Storage 快照计数：未知',
                           '  Kiraan syot Storage terkini disimpan: tidak diketahui'),
    'rp_storage': ('  Latest retained Storage snapshot counts (UNVERIFIED):', '  最新保留的 Storage 快照计数（UNVERIFIED）：',
                   '  Kiraan syot Storage terkini disimpan (UNVERIFIED):'),
    'rp_issue': ('  {role} / {name}: {count} issue rows', '  {role} / {name}：{count} 行问题记录',
                 '  {role} / {name}: {count} baris isu'),
    'rp_limits': ('Observed Change ≠ Actual Consumption.\nCounts exist only at recorded synchronisation times, not continuous monitoring; observation frequency can differ between periods.\nA missing snapshot is not proof of no change. Alert counts are stored and not re-checked.\nAlert categories may overlap; quality issue rows are not unique-material totals.\nMissing or pruned history, threshold meaning and units remain unverified.\nThis is not current stock verification, cloud verification or production approval.',
                  '观察到的变化 ≠ 实际消耗。\n计数只来自有记录的同步时刻，不是连续监控；各期观察频率可能不同。\n没有快照不代表没有变化。提醒数量为已存记录，未重新核对。\n提醒类别可能重叠；质量问题行数不等于不同材料数。\n缺失或已清理的历史、阈值含义及单位仍未核实。\n这不是实时库存核对、云端核对或生产批准。',
                  'Perubahan Diperhatikan ≠ Penggunaan Sebenar.\nKiraan hanya wujud pada masa penyegerakan direkod, bukan pemantauan berterusan; kekerapan pemerhatian boleh berbeza antara tempoh.\nTiada syot tidak membuktikan tiada perubahan. Kiraan amaran tersimpan dan tidak disemak semula.\nKategori amaran boleh bertindih; baris isu kualiti bukan jumlah bahan unik.\nSejarah hilang atau dipangkas, maksud ambang dan unit masih belum disahkan.\nIni bukan pengesahan stok semasa, pengesahan awan atau kelulusan pengeluaran.'),
}

# Readable labels for the canonical state codes shown in the report preview (the code itself is always shown too).
REPORT_STATES = {
    'NO_HISTORY': ('no history', '无历史记录', 'tiada sejarah'),
    'REMOVED': ('removed by cleanup', '已被清理', 'dibuang oleh pembersihan'),
    'PARTLY_PRUNED': ('partly removed by cleanup', '部分已被清理', 'sebahagian dibuang oleh pembersihan'),
    'NO_OBSERVATION_IN_WINDOW': ('history starts after this period', '历史记录晚于本期开始', 'sejarah bermula selepas tempoh ini'),
    'STARTED_DURING_WINDOW': ('history starts during this period', '历史记录在本期中途开始', 'sejarah bermula dalam tempoh ini'),
    'AVAILABLE_FROM_WINDOW_START': ('history available from the period start', '自本期开始已有历史记录',
                                    'sejarah tersedia dari awal tempoh'),
    'NOT_APPLICABLE': ('not applicable', '不适用', 'tidak berkenaan'),
    'COMPARABLE': ('both periods have Storage observations; not continuous monitoring',
                   '两期均有 Storage 观察记录；并非连续监控',
                   'kedua-dua tempoh ada pemerhatian Storage; bukan pemantauan berterusan'),
    'INCOMPLETE_HISTORY': ('not comparable: history or Storage observation missing',
                           '不可比较：缺少历史记录或 Storage 观察',
                           'tidak boleh dibandingkan: sejarah atau pemerhatian Storage tiada'),
    'STORED_NOT_RECHECKED': ('stored, not re-checked', '已存记录，未重新核对', 'tersimpan, tidak disemak semula'),
    'UNAVAILABLE': ('unavailable', '不可用', 'tidak tersedia'),
}


def report_state(code, language='en'):
    """'label (CODE)' for a report state; unknown codes are shown as the code only."""
    label = REPORT_STATES.get(code)
    return f"{label[LANGUAGES.index(language)]} ({code})" if label else str(code)

ERRORS = {
    'CONSENT_REQUIRED': ('Select historical data first.', '请先明确授权历史数据。', 'Pilih data sejarah dahulu.'),
    'OUTBOUND_CONSENT_REQUIRED': ('AI is disconnected. Use local tools or grant outbound consent.', 'AI 未连接；可用本地工具，或单独授权外发。', 'AI tidak disambungkan. Gunakan alat tempatan atau beri izin penghantaran.'),
    'SELECTION_REQUIRED': ('Search and select an actual candidate and original Sheet.', '请搜索并选择实际候选和原始 Sheet。', 'Cari dan pilih calon sebenar serta Sheet asal.'),
    'STALE_DATA': ('Data changed; select historical data again.', '数据已变化，请重新授权历史版本。', 'Data berubah; pilih semula data sejarah.'),
    'STALE_REPORT': ('The approved report request changed; review the preview and approve it again.',
                     '已确认的报告请求内容发生变化；请重新检查预览并再次授权。',
                     'Permintaan laporan yang diluluskan berubah; semak pratonton dan beri izin semula.'),
    'NARRATIVE_REJECTED': ('The AI interpretation was not used: it stated counts or a claim this report must not make (stock sufficient/production-ready, cloud verified, actual consumption or a purchase action). The local counts above are unchanged. This check is keyword-based and cannot guarantee every reply is correct.',
                           'AI 解读未被采用：其中包含具体数量，或本报告不允许的说法（库存充足/可生产、云端已验证、实际消耗或采购行动）。上方本地统计保持不变。此检查基于关键词，无法保证每条回复都正确。',
                           'Tafsiran AI tidak digunakan: ia menyatakan kiraan atau dakwaan yang tidak dibenarkan (stok mencukupi/sedia untuk pengeluaran, disahkan di awan, penggunaan sebenar atau tindakan pembelian). Kiraan setempat di atas tidak berubah. Semakan ini berasaskan kata kunci dan tidak menjamin setiap jawapan betul.'),
    'DATABASE_READ_FAILED': ('Database read failed. Old answers are historical only.', '数据库读取失败；旧回答仅保留为历史。', 'Bacaan pangkalan data gagal. Jawapan lama hanya sejarah.'),
    'PROVIDER_AUTH_REQUIRED': ('Save a valid API key in Settings first.', '请先在 Settings 保存有效的 API Key。', 'Simpan kunci API sah dalam Settings dahulu.'),
    'PROVIDER_AUTH_FAILED': ('API authentication failed; check the key.', 'API 身份验证失败，请检查 Key。', 'Pengesahan API gagal; semak kunci.'),
    'PROVIDER_QUOTA_EXHAUSTED': ('API credit is insufficient; local tools still work.', 'API 余额不足；本地工具仍可使用。', 'Kredit API tidak mencukupi; alat tempatan masih boleh digunakan.'),
    'PROVIDER_RATE_LIMITED': ('Provider rate limit reached. No automatic retry.', '达到 Provider 频率限制；未自动重试。', 'Had kadar Provider dicapai. Tiada cubaan semula automatik.'),
    'PROVIDER_UNAVAILABLE': ('AI provider unavailable. Local tools still work.', 'AI 服务不可用；本地工具仍可使用。', 'Provider AI tidak tersedia. Alat tempatan masih boleh digunakan.'),
    'OUTBOUND_DATA_REFUSED': ('Request contains a refused sensitive/path pattern. Edit it or use local tools.', '请求含被拒绝的敏感或路径格式；请修改或使用本地工具。', 'Permintaan mengandungi corak sensitif/laluan yang ditolak. Ubah atau gunakan alat tempatan.'),
    'INVALID_PROVIDER_RESPONSE': ('Incomplete or invalid AI response discarded.', '已丢弃不完整或无效的 AI 回复。', 'Jawapan AI tidak lengkap atau tidak sah dibuang.'),
    'NO_TOOL_EVIDENCE': ('No inventory evidence returned. Use local search and select an exact candidate.', '没有返回库存证据；请用本地搜索并选择准确候选。', 'Tiada bukti inventori dipulangkan. Gunakan carian tempatan dan pilih calon tepat.'),
    'INVALID_ARGUMENTS': ('Check inputs: positive integer quantity, actual Sheets and 30/60/90 days.', '请检查：数量须为正整数、Sheet 须实际存在、天数为 30/60/90。', 'Semak input: kuantiti integer positif, Sheet sebenar dan 30/60/90 hari.'),
    'KEY_FAILED': ('Windows credential operation failed. No plaintext fallback was used.', 'Windows 凭据操作失败；未使用明文回退。', 'Operasi kelayakan Windows gagal. Tiada sandaran teks biasa digunakan.'),
    'DATA_UNAVAILABLE': ('No successful import for the requested source. Sync Excel first; missing data is unknown.', '所需来源没有成功导入记录。请先同步 Excel；缺失数据为未知。', 'Tiada import berjaya bagi sumber diminta. Segerakkan Excel dahulu; data tiada rekod tidak diketahui.'),
    'HOST_BUSY': ('Excel/maintenance work is running. Wait before starting an assistant query.', 'Excel 或维护任务正在运行，请稍后查询。', 'Kerja Excel/penyelenggaraan sedang berjalan. Tunggu sebelum carian pembantu.'),
    'INVALID_QUESTION': ('Enter a question of 1–4000 characters. Preview it before enabling AI.', '请输入 1–4000 字的问题，并在允许 AI 外发前预览。', 'Masukkan soalan 1–4000 aksara. Pratonton sebelum membenarkan AI.'),
}


def tr(key, language='en'):
    return TEXT[key][LANGUAGES.index(language)]


def error_text(code, language):
    if code in ('CANCELLED', 'STALE_SESSION'):
        return tr('cancelled' if code == 'CANCELLED' else 'invalidated', language)
    detail = ERRORS.get(code, ('Request refused or resource limit reached. Narrow the query or retry manually.',
                              '请求被拒绝或达到限制；请缩小范围或手动重试。',
                              'Permintaan ditolak atau had sumber dicapai. Kecilkan carian atau cuba semula secara manual.'))
    return f"{tr('error', language)} · {code}\n{detail[LANGUAGES.index(language)]}"
