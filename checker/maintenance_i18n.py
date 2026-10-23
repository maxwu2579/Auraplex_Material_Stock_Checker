"""Presentation of explicit cache/maintenance consent. Reads only already captured preview objects."""
from . import i18n
from .inventory_db import SCHEMA_VERSION

TEXT = {
    'Local History': ('本地历史维护', 'Penyelenggaraan sejarah setempat'),
    'Database upgrade': ('数据库升级', 'Naik taraf pangkalan data'),
    'Cache unavailable': ('缓存不可用', 'Cache tidak tersedia'),
    'Confirm local history cleanup?': ('确认清理本地历史？', 'Sahkan pembersihan sejarah setempat?'),
    'Upgrade local database?': ('升级本地数据库？', 'Naik taraf pangkalan data setempat?'),
    'Use historical cached data?': ('使用历史缓存数据？', 'Guna data cache sejarah?'),
    'Stock alerts are being evaluated. Please try again in a moment.': ('正在评估库存提醒，请稍后重试。', 'Amaran stok sedang dinilai. Cuba lagi sebentar.'),
    'Recovery backup: {path}': ('恢复备份：{path}', 'Sandaran pemulihan: {path}'),
    'No data deleted.': ('未删除任何数据。', 'Tiada data dipadam.'),
    'Nothing expired. No data deleted.': ('没有过期记录，未删除任何数据。', 'Tiada rekod luput. Tiada data dipadam.'),
    'Create a backup and delete ONLY these expired local records?': ('创建备份，并仅删除上述过期本地记录？', 'Cipta sandaran dan padam HANYA rekod setempat luput di atas?'),
    'Create a backup and upgrade the local database now?': ('现在创建备份并升级本地数据库？', 'Cipta sandaran dan naik taraf pangkalan data setempat sekarang?'),
    'Local database upgraded.\nRecovery backup: {backup}\n\nThe current Excel files will now be read again (thresholds are captured if they were not stored yet); until then alerts are not re-checked.': ('本地数据库已升级。\n恢复备份：{backup}\n\n接下来重新读取当前 Excel 文件（如尚未存储阈值则补录）；完成前提醒仍未复核。', 'Pangkalan data setempat dinaik taraf.\nSandaran pemulihan: {backup}\n\nFail Excel semasa akan dibaca semula (ambang direkodkan jika belum disimpan); sehingga itu amaran belum disemak semula.'),
    'Historical trial calculations only. Not production approval. Use these two cached versions?': ('仅用于历史试算，不是生产批准。使用上述两个缓存版本？', 'Pengiraan percubaan sejarah sahaja. Bukan kelulusan pengeluaran. Guna kedua-dua versi cache ini?'),
    'Cloud Not Verified. Excel files will NOT be checked.': ('Cloud Not Verified。不会核对 Excel 源文件。', 'Cloud Not Verified. Fail Excel TIDAK akan disemak.'),
    'Storage and BOM are independent historical versions; their import times may differ.': ('Storage 和 BOM 是独立的历史版本；导入时间可能不同。', 'Storage dan BOM ialah versi sejarah berasingan; masa import mungkin berbeza.'),
    '{role} · version {version}\n{path}\nSource modified (UTC): {modified}\nImported (UTC): {imported}\nPreviously verified (UTC): {verified}': ('{role} · 版本 {version}\n{path}\n源文件修改时间（UTC）：{modified}\n导入时间（UTC）：{imported}\n此前核对时间（UTC）：{verified}', '{role} · versi {version}\n{path}\nSumber diubah (UTC): {modified}\nDiimport (UTC): {imported}\nPernah disahkan (UTC): {verified}'),
    'Unknown': ('未知', 'Tidak diketahui'),
    'Local database maintenance — preview only': ('本地数据库维护 — 仅预览', 'Penyelenggaraan pangkalan data setempat — pratonton sahaja'),
    'Evaluated UTC: {time}\nInventory: 12 calendar months, before {snapshots} UTC\nRoutine logs: 90 days, before {routine} UTC\nFailure logs: 180 days, before {failure} UTC': ('评估时间 UTC：{time}\n库存历史：12 个日历月，早于 {snapshots} UTC\n常规日志：90 天，早于 {routine} UTC\n失败日志：180 天，早于 {failure} UTC', 'Dinilai UTC: {time}\nInventori: 12 bulan kalendar, sebelum {snapshots} UTC\nLog rutin: 90 hari, sebelum {routine} UTC\nLog kegagalan: 180 hari, sebelum {failure} UTC'),
    'Expired inventory snapshots': ('过期库存快照', 'Petikan inventori luput'),
    'Expired Storage payloads': ('过期库存记录载荷', 'Muatan Storage luput'),
    'Stock rows': ('库存行数', 'Baris stok'), 'Stock sheets': ('库存 Sheet 数', 'Sheet stok'),
    'Quality issues': ('数据质量问题', 'Isu kualiti data'),
    'Observed changes': ('观察变化', 'Perubahan diperhatikan'), 'Expired logs': ('过期日志', 'Log luput'),
    'Latest/current snapshots, trend baseline and required predecessors are protected.': ('保护最新/当前快照、趋势基线及必要前置快照。', 'Petikan terkini/semasa, garis dasar trend dan pendahulu diperlukan dilindungi.'),
    'Latest attempt/success logs remain even when older than their retention limit.': ('各来源最近尝试/成功日志即使超期也会保留。', 'Log percubaan/kejayaan terakhir dikekalkan walaupun melebihi tempoh pengekalan.'),
    'Source-version headers, BOM history and material registry remain.': ('保留来源版本头、BOM 历史和材料登记表。', 'Pengepala versi sumber, sejarah BOM dan daftar bahan dikekalkan.'),
    'A recovery backup will be created in the database folder’s backups subfolder.': ('将在数据库目录的 backups 子目录创建恢复备份。', 'Sandaran pemulihan akan dicipta dalam subfolder backups folder pangkalan data.'),
    'Recovery backups contain the old history and are not automatically deleted.': ('恢复备份包含旧历史，不会自动删除。', 'Sandaran pemulihan mengandungi sejarah lama dan tidak dipadam secara automatik.'),
    'Excel files are not changed. SQLite file size may not shrink; free pages are reused.': ('不修改 Excel。SQLite 文件可能不会缩小；空闲页会复用。', 'Fail Excel tidak diubah. Saiz fail SQLite mungkin tidak mengecil; halaman kosong diguna semula.'),
    'Local database upgrade — preview only': ('本地数据库升级 — 仅预览', 'Naik taraf pangkalan data setempat — pratonton sahaja'),
    'Schema {before} → {after}: {change}.': ('Schema {before} → {after}：{change}。', 'Schema {before} → {after}: {change}.'),
    'adds storage for the MIN QTY / MIIN QTY threshold of each Storage row, and tables for stock-alert evaluations and de-duplicated alerts, kept separately per Storage / BOM file': ('新增每行 MIN QTY / MIIN QTY 阈值存储及提醒评估、去重提醒表，并按 Storage / BOM 来源文件隔离', 'menambah storan ambang MIN QTY / MIIN QTY setiap baris Storage serta jadual penilaian dan amaran tanpa pendua, diasingkan mengikut fail Storage / BOM'),
    'keeps stock alerts separately per Storage / BOM file: existing alerts are attributed to the files they came from, and an alert is never resolved by an evaluation of a different file': ('按 Storage / BOM 文件隔离提醒：既有提醒归属其原文件，其他文件的评估不会将其标为已恢复', 'mengasingkan amaran mengikut fail Storage / BOM: amaran sedia ada dikaitkan kepada sumber asal dan tidak diselesaikan oleh penilaian fail lain'),
    'Source versions': ('来源版本数', 'Versi sumber'), 'Storage rows': ('库存行数', 'Baris Storage'),
    'Inventory snapshots': ('库存快照数', 'Petikan inventori'),
    'Stock alerts to attribute': ('待归属的库存提醒', 'Amaran stok untuk dikaitkan'),
    'Alert evaluations to attribute': ('待归属的提醒评估', 'Penilaian amaran untuk dikaitkan'),
    'Existing inventory rows are kept unchanged and nothing is deleted.': ('保留原有库存行，不修改或删除。', 'Baris inventori sedia ada dikekalkan tanpa perubahan dan tiada yang dipadam.'),
    "Storage versions imported before this upgrade have no thresholds until the current Storage file is read again (Refresh Excel); they are shown as 'threshold not captured', never as blank or 0.": ('升级前导入的库存版本没有阈值，须 Refresh Excel 重新读取当前库存文件；此前标记为“未采集阈值”，不会当作空白或 0。', "Versi Storage diimport sebelum naik taraf tiada ambang sehingga fail semasa dibaca semula (Refresh Excel); dipapar sebagai 'threshold not captured', bukan kosong atau 0."),
    "A verified recovery backup is created first in the database folder's backups subfolder.": ('先在数据库目录的 backups 子目录创建校验过的恢复备份。', 'Sandaran pemulihan disahkan dicipta dahulu dalam subfolder backups folder pangkalan data.'),
    'Recovery backups are not deleted automatically. Older development builds of this program cannot open an upgraded database; keep the backup if you need to go back.': ('恢复备份不会自动删除。旧开发版本无法打开升级后的数据库；如需回退，请保留备份。', 'Sandaran pemulihan tidak dipadam secara automatik. Binaan pembangunan lama tidak boleh membuka pangkalan data dinaik taraf; simpan sandaran untuk kembali ke versi lama.'),
    'Excel files are not changed.': ('不修改 Excel 文件。', 'Fail Excel tidak diubah.'),
}
for template, (zh, ms) in TEXT.items():
    i18n.S['maintenance:' + template] = (template, zh, ms)


def message(template, **values):
    return i18n.Message('maintenance:' + template, **values)


def _text(language, template, **values):
    return i18n.render(message(template, **values), language)


def cache_description(snapshot, language):
    if language == 'en':
        return snapshot.describe()
    from .cached import LABEL
    lines = [LABEL, _text(language, 'Cloud Not Verified. Excel files will NOT be checked.'),
             _text(language, 'Storage and BOM are independent historical versions; their import times may differ.')]
    for version in snapshot.versions:
        lines.append(_text(language, '{role} · version {version}\n{path}\nSource modified (UTC): {modified}\nImported (UTC): {imported}\nPreviously verified (UTC): {verified}',
                           role='Storage' if version.role == 'stock' else 'BOM', version=version.id, path=version.path,
                           modified=version.source_modified_at, imported=version.imported_at,
                           verified=version.last_verified_at or message('Unknown')))
    return '\n\n'.join(lines)


def retention_description(plan, language):
    if language == 'en':
        return plan.describe()
    lines = [_text(language, 'Local database maintenance — preview only'), plan.database,
             _text(language, 'Evaluated UTC: {time}\nInventory: 12 calendar months, before {snapshots} UTC\nRoutine logs: 90 days, before {routine} UTC\nFailure logs: 180 days, before {failure} UTC',
                   time=plan.evaluated_at, snapshots=plan.snapshot_cutoff, routine=plan.routine_cutoff, failure=plan.failure_cutoff)]
    lines.extend(f"{_text(language, name) if name in TEXT else name}: {count}" for name, count in plan.counts)
    lines.extend(_text(language, template) for template in (
        'Latest/current snapshots, trend baseline and required predecessors are protected.',
        'Latest attempt/success logs remain even when older than their retention limit.',
        'Source-version headers, BOM history and material registry remain.',
        'A recovery backup will be created in the database folder’s backups subfolder.',
        'Recovery backups contain the old history and are not automatically deleted.',
        'Excel files are not changed. SQLite file size may not shrink; free pages are reused.'))
    return '\n\n'.join(lines)


def upgrade_description(plan, language):
    if language == 'en':
        return plan.describe()
    change = ('adds storage for the MIN QTY / MIIN QTY threshold of each Storage row, and tables for stock-alert evaluations and de-duplicated alerts, kept separately per Storage / BOM file' if plan.from_version == 1 else
              'keeps stock alerts separately per Storage / BOM file: existing alerts are attributed to the files they came from, and an alert is never resolved by an evaluation of a different file')
    lines = [_text(language, 'Local database upgrade — preview only'), plan.database,
             _text(language, 'Schema {before} → {after}: {change}.', before=plan.from_version, after=SCHEMA_VERSION, change=message(change))]
    lines.extend(f"{_text(language, name) if name in TEXT else name}: {count}" for name, count in plan.counts)
    lines.append(_text(language, 'Existing inventory rows are kept unchanged and nothing is deleted.'))
    if plan.from_version == 1:
        lines.append(_text(language, "Storage versions imported before this upgrade have no thresholds until the current Storage file is read again (Refresh Excel); they are shown as 'threshold not captured', never as blank or 0."))
    lines.extend(_text(language, template) for template in (
        "A verified recovery backup is created first in the database folder's backups subfolder.",
        'Recovery backups are not deleted automatically. Older development builds of this program cannot open an upgraded database; keep the backup if you need to go back.',
        'Excel files are not changed.'))
    return '\n\n'.join(lines)
