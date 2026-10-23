"""M4F delivery: save the AI-reports aggregate summary as HTML + JSON, and write a local .eml draft.

Nothing here sends anything. There is no SMTP, no mail credential, no mail client launch and no scheduling; the
.eml file is only a draft on disk.

Content boundary. A report document holds exactly the validated M4F aggregate facts (narrative.validate_facts: fixed
enums, windows and counts; no Material IDs, descriptions, Sheet names, paths, file hashes or rows) plus, only when the
user chose it, the AI interpretation that was accepted for exactly those facts. The interpretation is a separate
section and never changes a fact. Unknown values stay null / "unknown".

Publication (same contract as the M3.2D daily summary, checker.daily.save):
- the HTML and JSON are rendered from ONE canonical JSON text (same report ID), written and read back inside a
  private staging directory `.mrc-report-….partial`;
- immediately before ONE no-overwrite rename of that directory, while a database read transaction is held (rollback
  journal only, else DeliveryUnsupported), the database basis must still equal the report's basis, and - while the
  caller's session guard is held (SQLite lock first, then the session lock) - the session must still hold exactly the
  authorisation the report was built under; otherwise DeliveryStale and nothing is published;
- every name-race retry checks again; nothing existing is replaced; a staging directory that cannot be removed is
  reported on the exception (`cleanup_warning`, `leftover`).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from . import narrative
from .assistant_language import report_state
from .history import HistoryReadError, read_view

FORMAT = "mrc-ai-report-delivery/1"
LANGS = ("en", "zh", "ms")
SUPPORTED_JOURNAL_MODES = ("delete", "truncate", "persist")
STAGING_PREFIX = ".mrc-report-"
STAGING_SUFFIX = ".partial"
MAX_ADDRESSES = 10
MAX_SUBJECT = 200
CLOUD = "Cloud Not Verified"
OBSERVED = "Observed Change ≠ Actual Consumption"


class DeliveryError(Exception):
    """The report or draft could not be produced; nothing was published."""


class DeliveryStale(DeliveryError):
    """The data or the session changed after the report was built; build the report again."""


class DeliveryUnsupported(DeliveryError):
    """A database or file-system condition this delivery does not support."""


# ---------------------------------------------------------------------- texts (one language per document)
T = {
    "title": ("AI aggregate report", "AI 汇总报告", "Laporan agregat AI"),
    "DAILY": ("Daily", "日报", "Harian"),
    "WEEKLY": ("Weekly", "周报", "Mingguan"),
    "banner": ("UNVERIFIED historical SQLite observations · Cloud Not Verified · not current stock, not production "
               "approval, not a purchase recommendation",
               "UNVERIFIED 的 SQLite 历史观察 · Cloud Not Verified · 不是实时库存、不是生产批准、不是采购建议",
               "Pemerhatian sejarah SQLite UNVERIFIED · Cloud Not Verified · bukan stok semasa, bukan kelulusan "
               "pengeluaran, bukan cadangan pembelian"),
    "observed": ("Observed Change ≠ Actual Consumption: differences between synchronised Storage versions may include "
                 "receipts, corrections and recounts.",
                 "Observed Change ≠ Actual Consumption：同步版本之间的差异可能包含收货、更正和盘点。",
                 "Observed Change ≠ Actual Consumption: perbezaan antara versi Storage boleh termasuk penerimaan, "
                 "pembetulan dan kiraan semula."),
    "info": ("Report information", "报告信息", "Maklumat laporan"),
    "type": ("Report type", "报告类型", "Jenis laporan"),
    "generated": ("Facts generated (UTC)", "汇总生成时间（UTC）", "Fakta dijana (UTC)"),
    "saved": ("Report saved (UTC)", "报告保存时间（UTC）", "Laporan disimpan (UTC)"),
    "report_id": ("Report ID", "报告 ID", "ID laporan"),
    "basis": ("Data basis digest", "数据依据摘要", "Ringkasan asas data"),
    "basis_note": ("Identifies the database state the facts were read from; it is not a file hash and proves no "
                   "cloud freshness.", "标识读取汇总时的数据库状态；不是文件哈希，也不证明云端最新。",
                   "Mengenal pasti keadaan pangkalan data semasa fakta dibaca; bukan hash fail dan tidak membuktikan "
                   "kesegaran awan."),
    "facts_sha": ("Facts SHA-256", "汇总内容 SHA-256", "SHA-256 fakta"),
    "stats": ("Local deterministic statistics", "本地确定性统计", "Statistik setempat deterministik"),
    "current": ("Current period", "本期", "Tempoh semasa"),
    "previous": ("Previous period", "上期", "Tempoh sebelumnya"),
    "window": ("Window", "时间窗口", "Tempoh"),
    "coverage": ("History coverage", "历史覆盖", "Liputan sejarah"),
    "snapshots": ("Storage snapshots", "Storage 快照", "Syot Storage"),
    "attempts": ("Storage sync attempts", "Storage 同步尝试", "Cubaan penyegerakan Storage"),
    "checks": ("Successful Storage checks", "Storage 成功核对", "Semakan Storage berjaya"),
    "events": ("Observed change events", "观察到的变化事件", "Peristiwa perubahan diperhatikan"),
    "ids": ("Distinct material IDs (count only)", "涉及不同材料编号（仅计数）", "ID bahan berbeza (kiraan sahaja)"),
    "switches": ("Source switches", "来源切换", "Pertukaran sumber"),
    "by_type": ("Changes by type", "按类型的变化", "Perubahan mengikut jenis"),
    "events_col": ("Events", "事件数", "Peristiwa"),
    "comparison": ("Weekly comparison", "周对比", "Perbandingan mingguan"),
    "delta": ("Event-count delta", "事件数差值", "Beza kiraan peristiwa"),
    "alerts": ("Recorded alerts", "已记录提醒", "Amaran direkod"),
    "evaluated": ("Evaluated (UTC)", "评估时间（UTC）", "Dinilai (UTC)"),
    "overlap": ("Alert categories may overlap; counts are not a number of materials. Stored, not re-checked.",
                "提醒类别可能重叠，数量不是材料数；为已存记录，未重新核对。",
                "Kategori amaran boleh bertindih; kiraan bukan bilangan bahan. Tersimpan, tidak disemak semula."),
    "sync": ("Latest recorded sync attempts", "最近记录的同步尝试", "Cubaan penyegerakan terakhir direkod"),
    "quality": ("Recorded data quality", "已记录的数据质量", "Kualiti data direkod"),
    "retained": ("Latest retained Storage snapshot", "最新保留的 Storage 快照", "Syot Storage terkini disimpan"),
    "issue_rows": ("Issue rows (not unique materials)", "问题记录行数（不是不同材料数）", "Baris isu (bukan bahan unik)"),
    "limits": ("Limitations", "限制说明", "Had"),
    "ai": ("AI interpretation", "AI 解读", "Tafsiran AI"),
    "ai_note": ("Qualitative AI text, UNVERIFIED. It was accepted for exactly these facts and passed a keyword check "
                "that cannot guarantee correctness. It does not change any statistic above; review it against the "
                "local counts.",
                "定性 AI 文字，UNVERIFIED。它针对的正是这份汇总，并通过了关键词检查，但关键词检查无法保证内容正确。它不修改上方任何统计；请结合本地计数人工复核。",
                "Teks AI kualitatif, UNVERIFIED. Ia diterima bagi fakta ini sahaja dan lulus semakan kata kunci yang "
                "tidak menjamin ketepatan. Ia tidak mengubah sebarang statistik di atas; semak dengan kiraan setempat."),
    "ai_none": ("No AI interpretation is included in this report.", "本报告不包含 AI 解读。",
                "Tiada tafsiran AI dalam laporan ini."),
    "unknown": ("unknown", "未知", "tidak diketahui"),
    "none": ("none recorded", "无记录", "tiada rekod"),
    "footer": ("Generated locally by Material Requirement & Stock Checker (M4F delivery). Excel, stock and Drive "
               "settings were not changed. Nothing was sent.",
               "由物料需求与库存检查器本地生成（M4F 交付）。未修改 Excel、库存或 Drive 设置，未发送任何内容。",
               "Dijana secara setempat oleh Material Requirement & Stock Checker (penghantaran M4F). Excel, stok dan "
               "tetapan Drive tidak diubah. Tiada apa dihantar."),
    # e-mail draft
    "mail_subject": ("[UNVERIFIED] {kind} inventory report {window} · Cloud Not Verified",
                     "[UNVERIFIED] {kind}库存报告 {window} · Cloud Not Verified",
                     "[UNVERIFIED] Laporan inventori {kind} {window} · Cloud Not Verified"),
    "mail_intro": ("This is a DRAFT created locally. Nothing was sent. Please review before sending from your own "
                   "mail program.", "这是本地生成的邮件草稿，尚未发送。请在您自己的邮件程序中核对后再发送。",
                   "Ini DRAF yang dijana secara setempat. Tiada apa dihantar. Sila semak sebelum menghantar daripada "
                   "program e-mel anda."),
    "mail_status": ("Data status: UNVERIFIED historical SQLite observations; Cloud Not Verified. Not current stock, "
                    "not production approval, not a purchase recommendation.",
                    "数据状态：UNVERIFIED 的 SQLite 历史观察；Cloud Not Verified。不是实时库存，不是生产批准，不是采购建议。",
                    "Status data: pemerhatian sejarah SQLite UNVERIFIED; Cloud Not Verified. Bukan stok semasa, bukan "
                    "kelulusan pengeluaran, bukan cadangan pembelian."),
    "mail_ai_in": ("AI interpretation: included in the attached report as a separate, UNVERIFIED section. It does not "
                   "change the statistics.", "AI 解读：作为单独的 UNVERIFIED 部分附在报告中，不修改统计。",
                   "Tafsiran AI: disertakan dalam laporan sebagai bahagian berasingan UNVERIFIED. Ia tidak mengubah "
                   "statistik."),
    "mail_ai_out": ("AI interpretation: not included.", "AI 解读：未包含。", "Tafsiran AI: tidak disertakan."),
    "mail_attach": ("Attachments (the report generated above, nothing else):", "附件（即上述已生成的报告，无其他文件）：",
                    "Lampiran (laporan yang dijana di atas sahaja):"),
    "mail_unknown": ("Values shown as \"unknown\" were not recorded or not available; they are not 0.",
                     "显示为“未知”的数值没有记录或不可用，不等于 0。",
                     "Nilai \"tidak diketahui\" tidak direkod atau tiada; ia bukan 0."),
}
LIMITS = {
    "UNVERIFIED_HISTORICAL_SQLITE": ("Historical SQLite observations, UNVERIFIED.", "SQLite 历史观察，UNVERIFIED。",
                                     "Pemerhatian sejarah SQLite, UNVERIFIED."),
    "CLOUD_NOT_VERIFIED": ("The Google Drive cloud copy is never checked.", "从未核对 Google Drive 云端副本。",
                           "Salinan awan Google Drive tidak pernah disemak."),
    "OBSERVED_CHANGE_NOT_ACTUAL_CONSUMPTION": ("Observed change is not actual consumption.", "观察到的变化不等于实际消耗。",
                                               "Perubahan diperhatikan bukan penggunaan sebenar."),
    "NO_SNAPSHOT_DOES_NOT_PROVE_NO_CHANGE": ("No snapshot does not prove no change.", "没有快照不代表没有变化。",
                                             "Tiada syot tidak membuktikan tiada perubahan."),
    "ALERT_COUNTS_NOT_RECHECKED": ("Alert counts are stored and not re-checked.", "提醒数量为已存记录，未重新核对。",
                                   "Kiraan amaran tersimpan, tidak disemak semula."),
    "ALERT_CATEGORY_COUNTS_MAY_OVERLAP": ("Alert categories may overlap.", "提醒类别可能重叠。",
                                          "Kategori amaran boleh bertindih."),
    "QUALITY_ISSUE_COUNTS_ARE_NOT_UNIQUE_MATERIALS": ("Quality issue rows are not unique materials.",
                                                      "质量问题行数不等于不同材料数。",
                                                      "Baris isu kualiti bukan bahan unik."),
    "MISSING_OR_PRUNED_HISTORY_IS_UNKNOWN": ("Missing or cleaned-up history is unknown, not 0.",
                                             "缺失或已清理的历史为未知，不是 0。",
                                             "Sejarah hilang atau dibersihkan tidak diketahui, bukan 0."),
    "OBSERVED_ONLY_AT_RECORDED_SYNC_TIMES_NOT_CONTINUOUS": ("Observations exist only at recorded sync times, not "
                                                            "continuously.", "只在有记录的同步时刻有观察，不是连续监控。",
                                                            "Pemerhatian hanya pada masa penyegerakan direkod, bukan "
                                                            "berterusan."),
    "THRESHOLDS_AND_UNITS_NOT_BUSINESS_CONFIRMED": ("Threshold meaning and units are not business-confirmed.",
                                                    "阈值含义和单位尚未经业务确认。",
                                                    "Maksud ambang dan unit belum disahkan perniagaan."),
}


def tx(key, lang, **values):
    text = T[key][LANGS.index(lang)]
    return text.format(**values) if values else text


def _limit(code, lang):
    row = LIMITS.get(code)
    return row[LANGS.index(lang)] if row else code


# ---------------------------------------------------------------------- the document (one canonical JSON text)
@dataclass(frozen=True)
class ReportDocument:
    report_id: str
    language: str
    period: str
    basis: str            # the session's data basis the facts were read under
    facts_digest: str
    include_ai: bool
    json_text: str        # every rendering comes from this text

    def data(self) -> dict:
        return json.loads(self.json_text)


def build_document(facts, facts_digest, basis, language, *, narrative_text=None, now=None) -> ReportDocument:
    """Validate and freeze one report. Raises DeliveryError for invalid facts, a digest that is not these facts, a
    basis that is not a digest, or an AI text the host guard does not accept."""
    try:
        facts = narrative.validate_facts(facts)
    except ValueError as exc:
        raise DeliveryError(f"The report facts are not valid: {exc}") from None
    if narrative.digest(facts) != facts_digest:
        raise DeliveryError("The report facts do not match their digest; build the report again.")
    if type(basis) is not str or not re.fullmatch(r"[0-9a-f]{64}", basis):
        raise DeliveryError("The report has no valid data basis; build the report again.")
    if language not in LANGS:
        raise DeliveryError("Choose English, Chinese or Malay.")
    ai = None
    if narrative_text is not None:
        if type(narrative_text) is not str or not narrative_text.strip() or len(narrative_text) > 4000 or \
                narrative.reply_problems(narrative_text):
            raise DeliveryError("The AI interpretation cannot be included (empty, too long, or rejected by the host "
                                "check).")
        ai = {"text": narrative_text, "language": language, "host_check": "PASSED_KEYWORD_GUARD",
              "notice": "Qualitative, UNVERIFIED; does not change the statistics; keyword check is not a guarantee."}
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report_id = uuid.uuid4().hex
    data = {
        "format": FORMAT, "report_id": report_id, "language": language, "period": facts["period"],
        "saved_utc": moment.strftime("%Y-%m-%d %H:%M:%S"), "verification": "UNVERIFIED", "cloud": CLOUD,
        "statement": OBSERVED, "data_basis_digest": basis, "facts_sha256": facts_digest, "facts": facts,
        "ai_interpretation": ai,
    }
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False)
    return ReportDocument(report_id, language, facts["period"], basis, facts_digest, ai is not None, text)


def file_stem(document: ReportDocument) -> str:
    stamp = document.data()["saved_utc"].replace("-", "").replace(":", "").replace(" ", "_")
    return f"UNVERIFIED_AI_Report_{document.period}_{document.language.upper()}_{stamp}UTC"


def _e(value) -> str:
    return html.escape("—" if value is None else str(value), quote=True)


def _rows(pairs) -> str:
    return "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in pairs)


def _num(value, lang):
    return tx("unknown", lang) if value is None else value


def render_html(document: ReportDocument) -> str:
    d = document.data()
    lang, f = d["language"], d["facts"]
    kind = tx(f["period"], lang)
    title = f"{tx('title', lang)} · {kind} · UNVERIFIED"
    parts = [f"<h1>{_e(title)}</h1>", f'<div class="banner">{_e(tx("banner", lang))}</div>',
             f'<p class="note">{_e(tx("observed", lang))}</p>',
             f"<h2>{_e(tx('info', lang))}</h2><table>" + _rows([
                 (tx("type", lang), f"{kind} ({f['period']})"), (tx("generated", lang), f["generated_utc"]),
                 (tx("saved", lang), d["saved_utc"]), (tx("report_id", lang), d["report_id"]),
                 (tx("basis", lang), d["data_basis_digest"]), (tx("facts_sha", lang), d["facts_sha256"]),
                 ("Status", f"UNVERIFIED · {CLOUD}")]) + f"</table><p class=\"note\">{_e(tx('basis_note', lang))}</p>",
             f"<h2>{_e(tx('stats', lang))}</h2>"]
    for key, period in (("current", f["current_period"]), ("previous", f["previous_period"])):
        if period is None:
            continue
        parts.append(f"<h3>{_e(tx(key, lang))}</h3><table>" + _rows([
            (tx("window", lang), f"{period['window']['start_local']} → {period['window']['end_local']}"),
            (tx("coverage", lang), report_state(period["coverage"], lang)),
            (tx("snapshots", lang), period["snapshots"]), (tx("attempts", lang), period["stock_sync_attempts"]),
            (tx("checks", lang), period["successful_stock_checks"]), (tx("events", lang), period["observed_change_events"]),
            (tx("ids", lang), period["distinct_material_ids"]), (tx("switches", lang), period["source_switches"])]) +
            "</table>" + f"<table><tr><th>{_e(tx('by_type', lang))}</th><th>{_e(tx('events_col', lang))}</th>"
            f"<th>{_e(tx('ids', lang))}</th></tr>" + "".join(
                f"<tr><td>{_e(k)}</td><td>{_e(v['events'])}</td><td>{_e(v['distinct_material_ids'])}</td></tr>"
                for k, v in period["changes_by_type"].items()) + "</table>")
    comparison = f["comparison"]
    parts.append(f"<h3>{_e(tx('comparison', lang))}</h3><p>{_e(report_state(comparison['status'], lang))}</p>")
    if comparison["change_event_delta_by_type"] is not None:
        parts.append("<table>" + _rows([(f"{k} · {tx('delta', lang)}", _num(v, lang) if v is None else f"{v:+d}")
                                        for k, v in comparison["change_event_delta_by_type"].items()]) + "</table>")
    alerts = f["recorded_alerts"]
    parts.append(f"<h3>{_e(tx('alerts', lang))}</h3><p>{_e(report_state(alerts['status'], lang))} · "
                 f"{_e(tx('evaluated', lang))}: {_e(alerts['evaluated_utc'] or tx('unknown', lang))}</p>")
    parts.append("<table>" + (_rows(alerts["counts_by_type"].items()) if alerts["counts_by_type"] is not None else
                              _rows([(tx("alerts", lang), tx("unknown", lang))])) + "</table>"
                 f"<p class=\"note\">{_e(tx('overlap', lang))}</p>")
    parts.append(f"<h3>{_e(tx('sync', lang))}</h3><table>" + _rows([
        (role, f"{row['outcome']} · {row['finished_utc'] or tx('unknown', lang)}")
        for role, row in f["latest_sync_attempts"].items()]) + "</table>")
    quality = f["data_quality"]
    retained = quality["latest_retained_storage"]
    parts.append(f"<h3>{_e(tx('quality', lang))}</h3><table>" + (
        _rows([(f"{tx('retained', lang)} · {k}", v) for k, v in retained.items()]) if retained is not None else
        _rows([(tx("retained", lang), tx("unknown", lang))])) + _rows([
            (f"{role} / {name} · {tx('issue_rows', lang)}", _num(count, lang))
            for role, counts in quality["recorded_issue_rows"].items() for name, count in counts.items()]) + "</table>")
    parts.append(f"<h2>{_e(tx('limits', lang))}</h2><ul>" + "".join(
        f"<li>{_e(_limit(code, lang))} <small>({_e(code)})</small></li>" for code in f["limitations"]) + "</ul>")
    ai = d["ai_interpretation"]
    if ai is None:
        parts.append(f"<h2>{_e(tx('ai', lang))}</h2><p class=\"note\">{_e(tx('ai_none', lang))}</p>")
    else:
        parts.append(f'<section class="ai"><h2>{_e(tx("ai", lang))} · UNVERIFIED</h2><p class="note">'
                     f'{_e(tx("ai_note", lang))}</p><blockquote>{_e(ai["text"])}</blockquote></section>')
    digest = hashlib.sha256(document.json_text.encode("utf-8")).hexdigest()
    parts.append(f"<footer>{_e(tx('report_id', lang))} {_e(d['report_id'])} · {_e(FORMAT)} · data SHA-256 "
                 f"{_e(digest)} · UNVERIFIED · {CLOUD} · {_e(tx('footer', lang))}</footer>")
    css = ("body{font-family:'Segoe UI','Microsoft YaHei',Arial,sans-serif;margin:24px;color:#1f2937;font-size:13px}"
           "h1{font-size:20px}h2{font-size:16px;border-bottom:1px solid #d1d5db;margin-top:22px}h3{font-size:14px}"
           ".banner{background:#fde8e6;border:2px solid #b42318;color:#8a1c12;padding:8px 12px;font-weight:bold}"
           ".note{color:#4b5563}table{border-collapse:collapse;margin:6px 0}th,td{border:1px solid #d1d5db;"
           "padding:3px 8px;text-align:left;vertical-align:top}th{background:#f3f4f6;font-weight:600}"
           ".ai{border:2px dashed #9a6200;background:#fffaf0;padding:4px 14px;margin-top:20px}"
           "blockquote{white-space:pre-wrap;margin:8px 0}footer{margin-top:24px;font-size:11px;color:#6b7280}"
           "@media print{.banner{border-width:1px}}")
    html_lang = {"en": "en", "zh": "zh-CN", "ms": "ms"}[lang]
    return (f'<!DOCTYPE html>\n<html lang="{html_lang}"><head><meta charset="utf-8">'
            f'<meta name="report-id" content="{_e(d["report_id"])}"><meta name="data-sha256" content="{digest}">'
            f"<title>{_e(title)}</title><style>{css}</style></head><body>\n" + "\n".join(parts) + "\n</body></html>\n")


# ---------------------------------------------------------------------- guarded pair publication
def _checkpoint(stage: str) -> None:
    """No-op test hook: 'staged', 'before_publish' (database read lock and session guard held), 'retry'."""


def _write_verified(path: Path, payload: bytes) -> None:
    with open(path, "xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != payload:
        raise DeliveryError(f"The staged file could not be verified: {path}")


def _publish(staging: Path, target: Path) -> None:
    os.rename(staging, target)  # the commit point; Windows refuses any existing destination


@contextmanager
def _publication_basis(database, basis_of):
    try:
        with read_view(database) as conn:
            mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if mode not in SUPPORTED_JOURNAL_MODES:
                raise DeliveryUnsupported(
                    f"Saving reports needs a rollback-journal database (DELETE, TRUNCATE or PERSIST); this database uses "
                    f"{mode.upper()}. Nothing was saved and the database was not changed.")
            yield basis_of(conn)
    except HistoryReadError as exc:
        raise DeliveryError(f"The local database could not be read; nothing was saved: {exc}") from exc


@dataclass(frozen=True)
class SavedReport:
    folder: Path
    html: Path
    json: Path
    report_id: str
    language: str
    period: str
    include_ai: bool
    sha256: tuple        # ((name, sha256), ...) of exactly the two published files


STALE = ("The data or this assistant session changed after the report was built (Refresh, sync, cleanup, Stop, "
         "Disconnect or new permission). Build the report again; nothing was saved.")


def save_report(document: ReportDocument, folder, database, *, basis_of, guard) -> SavedReport:
    """basis_of(conn) -> current basis inside the caller's read transaction; guard() -> context manager yielding
    whether the session still holds the report's authorisation (held during the rename)."""
    folder = Path(folder)
    if not folder.is_dir():
        raise DeliveryError(f"The folder does not exist: {folder}")
    with guard() as current:
        if not current:
            raise DeliveryStale(STALE)
    stem = file_stem(document)
    payloads = ((".json", document.json_text.encode("utf-8")), (".html", render_html(document).encode("utf-8")))
    staging = folder / f"{STAGING_PREFIX}{document.report_id[:12]}-{uuid.uuid4().hex[:8]}{STAGING_SUFFIX}"
    failure = None
    try:
        staging.mkdir()
        for suffix, payload in payloads:
            _write_verified(staging / (stem + suffix), payload)
        _checkpoint("staged")
        for n in range(1, 100):
            target = folder / (stem if n == 1 else f"{stem} ({n})")
            if os.path.lexists(target):
                continue
            published = collided = False
            error = None
            with _publication_basis(database, basis_of) as basis:
                if basis != document.basis:
                    raise DeliveryStale(STALE)
                with guard() as current:
                    if not current:
                        raise DeliveryStale(STALE)
                    _checkpoint("before_publish")
                    try:
                        _publish(staging, target)
                        published = True
                    except FileExistsError:
                        collided = True
                    except OSError as exc:
                        error = exc
            if error is not None:
                raise error
            if published:
                hashes = tuple((stem + suffix, hashlib.sha256(payload).hexdigest()) for suffix, payload in payloads)
                return SavedReport(target, target / (stem + ".html"), target / (stem + ".json"), document.report_id,
                                   document.language, document.period, document.include_ai, hashes)
            if collided:
                _checkpoint("retry")
        raise DeliveryError("No free report name was found; nothing was saved.")
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if staging.exists():
            try:
                shutil.rmtree(staging)
            except OSError as cleanup:
                warning = (f"Incomplete staging directory could not be removed: {staging} ({cleanup}). It is not a "
                           "report; delete it manually.")
                if failure is not None:
                    failure.cleanup_warning = warning
                    failure.leftover = staging
                    failure.add_note(warning)


# ---------------------------------------------------------------------- e-mail draft (.eml, never sent)
_ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f  \u0085]")


def clean_addresses(text) -> list[str]:
    """Comma/semicolon separated plain addresses only. Any control character (CR/LF included) is refused."""
    text = "" if text is None else str(text)
    if _CONTROL.search(text):
        raise DeliveryError("Addresses may not contain line breaks or control characters.")
    items = [a.strip() for a in re.split(r"[,;]", text) if a.strip()]
    if len(items) > MAX_ADDRESSES:
        raise DeliveryError(f"At most {MAX_ADDRESSES} addresses.")
    for item in items:
        if not _ADDRESS.fullmatch(item) or len(item) > 254:
            raise DeliveryError(f"Not a plain e-mail address: {item!r}")
    return items


def clean_subject(text) -> str:
    text = "" if text is None else str(text)
    if _CONTROL.search(text):
        raise DeliveryError("The subject may not contain line breaks or control characters.")
    text = text.strip()
    if not text or len(text) > MAX_SUBJECT:
        raise DeliveryError(f"The subject must have 1 to {MAX_SUBJECT} characters.")
    return text


def _verified_attachments(saved: SavedReport) -> list[tuple[str, bytes]]:
    """Exactly the two published files, re-read and compared with the hashes recorded when they were published."""
    files = []
    expected = dict(saved.sha256)
    for path in (saved.html, saved.json):
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise DeliveryError(f"The saved report cannot be read: {path} ({exc}). Save the report again.") from None
        if hashlib.sha256(payload).hexdigest() != expected.get(path.name):
            raise DeliveryStale(f"The saved report file changed after it was saved: {path}. Save the report again.")
        files.append((path.name, payload))
    return files


def default_subject(saved: SavedReport) -> str:
    data = json.loads(_verified_attachments(saved)[1][1].decode("utf-8"))
    window = data["facts"]["current_period"]["window"]
    return tx("mail_subject", saved.language, kind=tx(saved.period, saved.language),
              window=f"{window['start_local'][:10]}→{window['end_local'][:10]}")


def mail_body(saved: SavedReport) -> str:
    attachments = _verified_attachments(saved)
    data = json.loads(attachments[1][1].decode("utf-8"))
    lang, f = saved.language, data["facts"]
    unknown = tx("unknown", lang)
    lines = [tx("mail_intro", lang), "", tx("mail_status", lang), tx("observed", lang), tx("mail_unknown", lang), "",
             f"{tx('type', lang)}: {tx(f['period'], lang)} ({f['period']}) · {tx('report_id', lang)}: {data['report_id']}",
             f"{tx('generated', lang)}: {f['generated_utc']} · {tx('saved', lang)}: {data['saved_utc']}"]
    for key, period in (("current", f["current_period"]), ("previous", f["previous_period"])):
        if period is None:
            continue
        lines += ["", f"{tx(key, lang)}: {period['window']['start_local']} → {period['window']['end_local']}",
                  f"  {tx('coverage', lang)}: {report_state(period['coverage'], lang)}",
                  f"  {tx('events', lang)}: {period['observed_change_events']} · {tx('snapshots', lang)}: "
                  f"{period['snapshots']} · {tx('checks', lang)}: {period['successful_stock_checks']}"]
    comparison = f["comparison"]
    lines += ["", f"{tx('comparison', lang)}: {report_state(comparison['status'], lang)}"]
    if comparison["change_event_delta_by_type"] is not None:
        lines += [f"  {k}: {unknown if v is None else f'{v:+d}'}" for k, v in comparison["change_event_delta_by_type"].items()]
    alerts = f["recorded_alerts"]
    lines += ["", f"{tx('alerts', lang)}: {report_state(alerts['status'], lang)}"]
    lines += ([f"  {k}: {v}" for k, v in alerts["counts_by_type"].items()] if alerts["counts_by_type"] is not None
              else [f"  {unknown}"]) + [f"  {tx('overlap', lang)}"]
    quality = f["data_quality"]["recorded_issue_rows"]
    lines += ["", f"{tx('quality', lang)} · {tx('issue_rows', lang)}:"]
    lines += [f"  {role} / {name}: {unknown if count is None else count}" for role, counts in quality.items()
              for name, count in counts.items()]
    lines += ["", f"{tx('limits', lang)}:"] + [f"  - {_limit(code, lang)}" for code in f["limitations"]]
    lines += ["", tx("mail_ai_in", lang) if data["ai_interpretation"] is not None else tx("mail_ai_out", lang)]
    if data["ai_interpretation"] is not None:
        lines += [f"  {tx('ai_note', lang)}"]
    lines += ["", tx("mail_attach", lang)] + [f"  - {name} ({len(payload)} bytes)" for name, payload in attachments]
    return "\n".join(lines) + "\n"


def build_eml(saved: SavedReport, *, to="", subject=None, now=None) -> bytes:
    """The complete draft as bytes. Only the two files of `saved` are attached (verified against their hashes)."""
    addresses = clean_addresses(to)
    subject = clean_subject(subject if subject is not None else default_subject(saved))
    attachments = _verified_attachments(saved)
    message = EmailMessage(policy=policy.SMTP)
    if addresses:
        message["To"] = ", ".join(addresses)
    message["Subject"] = subject
    message["Date"] = format_datetime(now or datetime.now(timezone.utc))
    message["X-Unsent"] = "1"  # opened as an unsent draft by clients that support it; never sent by this program
    message.set_content(mail_body(saved), subtype="plain", charset="utf-8")
    for name, payload in attachments:
        if name.endswith(".html"):
            message.add_attachment(payload, maintype="text", subtype="html", filename=name)
        else:
            message.add_attachment(payload, maintype="application", subtype="json", filename=name)
    # set last: set_content()/add_attachment() rebuild the Content-* headers
    message["Content-Language"] = {"en": "en", "zh": "zh-CN", "ms": "ms"}[saved.language]
    return message.as_bytes()


def eml_name(saved: SavedReport) -> str:
    return saved.html.stem + "_DRAFT.eml"


def save_eml(payload: bytes, path) -> Path:
    """Write a NEW .eml file: staged in the same folder, read back, then a no-overwrite rename. An existing file is
    never replaced (a numbered name is used)."""
    path = Path(path)
    if path.suffix.lower() != ".eml":
        raise DeliveryError("Save the draft as a .eml file.")
    if not path.parent.is_dir():
        raise DeliveryError(f"The folder does not exist: {path.parent}")
    staging = path.parent / f"{STAGING_PREFIX}{uuid.uuid4().hex[:12]}.eml{STAGING_SUFFIX}"
    failure = None
    try:
        _write_verified(staging, payload)
        for n in range(1, 100):
            target = path if n == 1 else path.with_name(f"{path.stem} ({n}){path.suffix}")
            if os.path.lexists(target):
                continue
            try:
                if os.name == "nt":
                    os.rename(staging, target)
                else:
                    os.link(staging, target)
                return target
            except FileExistsError:
                continue
        raise DeliveryError("No free file name was found; nothing was saved.")
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if staging.exists():
            try:
                staging.unlink()
            except OSError as cleanup:
                warning = f"Staging file could not be removed: {staging} ({cleanup}). It is not a draft; delete it."
                if failure is not None:
                    failure.cleanup_warning = warning
                    failure.leftover = staging
                    failure.add_note(warning)
