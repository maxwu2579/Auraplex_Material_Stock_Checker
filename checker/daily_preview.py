"""Translated on-screen projection of an immutable DailySummary. No query, save or authorization operations."""
from . import daily, i18n
from .analysis_daily_i18n import message


def render(summary, language):
    if language == 'en':
        return daily.render_text(summary)  # preserve the existing English preview exactly
    d = summary.data()
    v, a, c, lim = d['verification'], d['alerts'], d['changes'], d['limitations']
    g = a['at_generation']
    def t(template, **values):
        return i18n.render(message(template, **values), language)
    def value(raw):
        return t('unknown') if raw is None else str(raw)
    def version(raw):
        if not raw:
            return '—'
        return t('v{id} · {name} · imported {imported} UTC · file modified {modified} UTC · {path}',
                 id=raw['id'], name=raw['file_name'], imported=raw['imported_utc'],
                 modified=raw['source_modified_utc'], path=raw['path'])
    lines = [t('{title} {day} — {status} · Cloud Not Verified', title=message('Daily Stock Summary'), day=d['report_date'], status=d['status']),
             t('Preview labels follow the interface language; saved HTML/JSON retain the original English report format.')]
    if d['status'] != daily.VERIFIED:
        lines.append('UNVERIFIED: ' + '; '.join(v['reasons']))  # original reasons, no guessed translation
    lines += [t('Time zone {zone} · day {start} → {end} (exclusive) · generated {generated} · report ID {id}',
                zone=d['timezone']['label'], start=d['window']['start_local'], end=d['window']['end_local'],
                generated=d['generated']['local'], id=d['report_id']), '', t('1. SOURCES')]
    for role in ('stock', 'bom'):
        source = d['sources'][role]
        run = source['latest_run'] or {}
        lines.append(f"  {source['role']}: {version(source['current'])}")
        session = 'v' + str(source['session_verified']['version_id']) if source['session_verified'] else message('not verified')
        lines.append(t('    latest check {outcome} at {time} UTC · {state} · this session: {session} · checks on this date: {checks}',
                       outcome=run.get('outcome', '—'), time=run.get('finished_utc', '—'), state=source['freshness_state'],
                       session=session, checks=', '.join(f'{k} {n}' for k, n in source['runs_on_day'].items())))
        if d['historical_date']:
            lines.append(t('    in effect at end of {day}: {version}', day=d['report_date'], version=version(source['in_effect_at_day_end'])))
    lines += ['', t('2. STOCK ALERTS'), '  ' + t('Alerts are review cues, not proof that stock is normal or sufficient. Thresholds and units need confirmation. Unavailable does not mean no alerts.')]
    if not a['for_report_date']['available']:
        lines.append(t('  Alerts for {day}: NOT AVAILABLE — {reason}', day=d['report_date'], reason=a['for_report_date']['reason']))
    lines.append(t('  At generation time: {status} — {label}', status=g['status'], label=g['label']))
    limit = daily.PREVIEW_ITEMS
    if g['status'] != daily.UNAVAILABLE:
        for item in g['by_type']:
            extra = t(' · {count} without ID', count=item['entries_without_material_id']) if item['entries_without_material_id'] else ''
            if item['subtypes']:
                extra += ' · ' + ', '.join(f'{k} {n}' for k, n in item['subtypes'].items())
            lines.append(t('    {type}: {alerts} alerts · {ids} distinct Material IDs{extra}', type=item['type'],
                           alerts=value(item['alerts']), ids=value(item['distinct_material_ids']), extra=extra))
        lines.append(t('    Distinct Material IDs with any alert: {count}. Counts overlap across types; do not sum them as materials.', count=value(g['distinct_material_ids_any_type'])))
        if g['total'] == 0:
            lines.append(t('    No alert of these types in this evaluation. This is not a statement that stock is sufficient.'))
        for item in g['items'][:limit]:
            lines.append(t('    - {type}{issue} · {material} · Sheet {sheet} · stock {stock} · threshold {threshold}',
                           type=item['type'], issue=' / ' + item['issue'] if item['issue'] else '', material=item['material_id'] or item.get('code', '—'),
                           sheet=item['sheet'], stock=value(item['stock']), threshold=value(item['threshold'])))
        if len(g['items']) > limit:
            lines.append(t('    … {count} more in the saved report', count=len(g['items']) - limit))
    lines.append(t('  Evaluations recorded on this date: {count}', count=len(a['evaluations_on_date'])))
    lines += ['', t('3. OBSERVED CHANGES ON {day} — Observed Change ≠ Actual Consumption', day=d['report_date']),
              '  ' + t('Changes belong to the snapshot observation date, not file modified time or actual business date.')]
    lines.append('  ' + ' · '.join(t('{type} {changes} ({ids} IDs)', type=k, changes=value(n['changes']), ids=value(n['distinct_material_ids'])) for k, n in c['by_type'].items()))
    lines.append(t('  Total {total} · distinct Material IDs {ids} · Storage snapshots {snapshots} · source switches {switches}',
                   total=value(c['total']), ids=value(c['distinct_material_ids']), snapshots=len(c['snapshots']), switches=len(c['source_switches'])))
    if c['no_record_note']:
        lines.append('  ' + t('No observed change was recorded. This does not prove no warehouse movement; Storage may not have been synchronised or the file may have been unchanged.'))
    for item in c['items'][:limit]:
        diff = item['observed_difference'] if item['observed_difference'] is not None else '— ' + (item['difference_reason'] or '')
        lines.append(t('    - {at} UTC · {sheet} · {material} · {type} · {before} → {after} · difference {difference}', at=item['observed_utc'],
                       sheet=item['sheet'], material=item['material_id'], type=item['change_type'], before=value(item['before']), after=value(item['after']), difference=diff))
    if len(c['items']) > limit:
        lines.append(t('    … {count} more in the saved report', count=len(c['items']) - limit))
    h = lim['history']
    lines += ['', t('4. DATA LIMITATIONS'), t('  History: {coverage} — {note}', coverage=h['coverage'], note=h['note']), '  ' + h['log_note']]
    lines.extend('  ' + n for n in lim['sync_notes'])
    for threshold in lim['thresholds']:
        column = f" ({threshold['column']} '{threshold['header']}')" if threshold['column'] else ''
        lines.append(t('  Threshold, Sheet {sheet}: {state}{column}', sheet=threshold['sheet'], state=threshold['state'], column=column))
    lines.append('  ' + lim['threshold_note'])
    raw = lim['current_storage_raw']
    if raw:
        lines.append(t('  Current Storage v{version}: {rows} rows · blank {blank} (not 0) · invalid {invalid} (not converted) · without usable ID {without_id} · duplicate IDs {duplicates}',
                       version=raw['version_id'], rows=value(raw['rows']), blank=value(raw['blank']), invalid=value(raw['invalid']), without_id=value(raw['without_usable_id']), duplicates=value(raw['duplicate_ids'])))
    for item in lim['not_calculated']:
        lines.append(t('  Not calculated — {field}: {reason}', field=item['field'], reason=item['reason']))
    return '\n'.join(lines)
