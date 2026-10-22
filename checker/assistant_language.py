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
    'history': ('UNVERIFIED · Historical SQLite observations · Cloud Not Verified',
                'UNVERIFIED · SQLite 历史记录 · Cloud Not Verified',
                'UNVERIFIED · Pemerhatian sejarah SQLite · Cloud Not Verified'),
    'caveat': ('Blank means not recorded; duplicates are not added. Observed change is not actual consumption. Estimates are not production approval.',
               '空白表示没有记录；重复编号不相加。观察到的变化不等于实际消耗；试算不是生产批准。',
               'Kosong bermaksud tiada rekod; ID pendua tidak dijumlahkan. Perubahan diperhatikan bukan penggunaan sebenar. Anggaran bukan kelulusan pengeluaran.'),
    'welcome': ('Choose local tools for offline queries. AI interpretation requires a key and separate outbound consent. Each answer shows a historical observation, never current-stock approval.',
                '离线查询可用本地工具。AI 理解问题需要 API Key 及单独的外发授权。回答仅展示历史观察，不是实时库存或生产批准。',
                'Gunakan alat tempatan untuk carian luar talian. Tafsiran AI memerlukan kunci dan persetujuan penghantaran berasingan. Jawapan ialah pemerhatian sejarah, bukan pengesahan stok semasa.'),
    'uncertain': ('Language unclear; using the previous/default reply language. You can select a language above.',
                  '语言不明确，沿用上次或默认回复语言；可在上方手动选择。',
                  'Bahasa kurang jelas; bahasa jawapan sebelumnya/lalai digunakan. Anda boleh memilih bahasa di atas.'),
    'cancelled': ('Stopped. Late results will not be displayed.', '已停止；迟到结果不会显示。', 'Dihentikan. Hasil lewat tidak akan dipaparkan.'),
    'invalidated': ('Session invalidated. Earlier answers are historical only. Select historical data again before a new query.',
                    '本次会话已失效。之前回答仅保留为历史；新查询前请重新选择历史数据。',
                    'Sesi dibatalkan. Jawapan terdahulu hanya sejarah. Pilih semula data sejarah sebelum carian baharu.'),
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
    'select': ('Select one actual candidate below. Similar IDs and different Sheets remain separate.',
               '请在下方选择一个实际候选；相似编号及不同 Sheet 保持分开。',
               'Pilih satu calon sebenar di bawah. ID serupa dan Sheet berbeza kekal berasingan.'),
    'no_results': ('No matching recorded rows. Missing stock is unknown, not zero.', '没有匹配记录；缺失库存是未知，不是零。', 'Tiada rekod sepadan. Stok tiada rekod tidak diketahui, bukan sifar.'),
    'omitted': ('Additional rows omitted here; see Evidence (bounded tool output).', '此处省略其余行；可查看 Evidence 中的受限工具结果。', 'Baris tambahan tidak dipaparkan di sini; lihat Evidence (hasil alat terhad).'),
    'observed': ('Observed at', '观察时间', 'Diperhatikan pada'),
    'source': ('Source / Sheet / row', '来源 / Sheet / 行号', 'Sumber / Sheet / baris'),
    'raw': ('Raw recorded stock', '原始库存记录', 'Stok direkod asal'),
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
    'saved_key': ('Key saved in your Windows vault. Enable outbound consent separately.', 'Key 已保存至当前用户的 Windows 凭据库；外发仍须单独授权。', 'Kunci disimpan dalam Windows vault anda. Aktifkan izin penghantaran secara berasingan.'),
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
}

ERRORS = {
    'CONSENT_REQUIRED': ('Select historical data first.', '请先明确授权历史数据。', 'Pilih data sejarah dahulu.'),
    'OUTBOUND_CONSENT_REQUIRED': ('AI is disconnected. Use local tools or grant outbound consent.', 'AI 未连接；可用本地工具，或单独授权外发。', 'AI tidak disambungkan. Gunakan alat tempatan atau beri izin penghantaran.'),
    'SELECTION_REQUIRED': ('Search and select an actual candidate and original Sheet.', '请搜索并选择实际候选和原始 Sheet。', 'Cari dan pilih calon sebenar serta Sheet asal.'),
    'STALE_DATA': ('Data changed; select historical data again.', '数据已变化，请重新授权历史版本。', 'Data berubah; pilih semula data sejarah.'),
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
