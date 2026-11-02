#!/usr/bin/env python3
"""Compile/verify wording-only Canva edits offline; never call or save Canva."""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def decode(value):
    if isinstance(value, dict) and all(isinstance(value.get(k), list) for k in ('pages', 'richtexts', 'fills')):
        return value
    if isinstance(value, dict) and isinstance(value.get('content'), list):
        candidates = []
        for c in value['content']:
            if c.get('type') == 'text':
                try:
                    candidates.append(decode(json.loads(c['text'])))
                except (ValueError, KeyError, TypeError):
                    pass
        if len(candidates) == 1:
            return candidates[0]
    raise ValueError('Expected one complete Canva snapshot with pages, richtexts and fills; inspect a changed tool schema instead of guessing.')


def snapshot(value):
    d = decode(value)
    pages = {p['page_id']: p for p in d['pages']}
    indices = [p['page_number'] for p in d['pages']]
    if len(pages) != len(d['pages']) or len(set(indices)) != len(indices):
        raise ValueError('Duplicate observed page ID/index.')
    elements = d['richtexts'] + d['fills']
    ids = [e['element_id'] for e in elements]
    if len(set(ids)) != len(ids) or any(e['page_index'] not in indices for e in elements):
        raise ValueError('Duplicate element IDs or unknown page membership.')
    for r in d['richtexts']:
        # Canva also returns shape records (including empty arrows) in richtexts.
        # Preserve them byte-for-byte; only TEXT records are editable text targets.
        if r.get('containerElement', {}).get('type') != 'TEXT':
            continue
        if not r.get('regions') or not all(isinstance(z.get('text'), str) for z in r['regions']):
            raise ValueError('Text regions are missing; use a complete current native readback.')
    return {'pages': copy.deepcopy(d['pages']), 'richtexts': copy.deepcopy(d['richtexts']), 'fills': copy.deepcopy(d['fills'])}


def text(record):
    return ''.join(z['text'] for z in record['regions'])


def preservation_signature(value):
    """Compare copied returned content/geometry, ignoring only generated IDs."""
    state = snapshot(value)
    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items() if k not in ('element_id', 'page_id')}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        if isinstance(obj, float):
            return round(obj, 6)
        return obj
    return {k: sorted((clean(r) for r in rows), key=lambda r: json.dumps(r, sort_keys=True)) for k, rows in state.items()}


def check_backup(baseline, evidence):
    if not evidence:
        raise ValueError('Whole-design mode requires backup metadata and both complete readbacks.')
    source = evidence.get('sourceDesign', {})
    backup = evidence.get('backupDesign', {})
    if not source.get('id') or not backup.get('id') or source['id'] == backup['id']:
        raise ValueError('Backup must be a different observed Canva design.')
    if preservation_signature(baseline) != preservation_signature(evidence['sourceReadback']):
        raise ValueError('Backup source does not match the pre-edit baseline.')
    if preservation_signature(baseline) != preservation_signature(evidence['backupReadback']):
        raise ValueError('Backup content/geometry does not preserve the source.')
    count = len(snapshot(baseline)['pages'])
    if source.get('page_count') != count or backup.get('page_count') != count:
        raise ValueError('Backup metadata page counts disagree with readbacks.')
    return {'mode': 'whole-design-backup', 'sourceDesignId': source['id'], 'backupDesignId': backup['id'],
            'returnedPropertiesPreserved': True, 'unreturnedStyles': 'require visual/UI evidence'}


def compile_plan(design, readback, mapping, link_id, transaction_id, protected_pages, transaction_readback=None,
                 baseline_readback=None, backup_evidence=None):
    mode = design.get('mode')
    if mode not in ('copy-only', 'copy-add') or not design.get('pages'):
        raise ValueError('Use copy-only or copy-add with nonempty pages.')
    d = decode(readback)
    evidence = decode(transaction_readback) if transaction_readback is not None else d
    if not link_id or not transaction_id or evidence.get('transaction', {}).get('transaction_id') != transaction_id:
        raise ValueError('Supply the current connection and exact transaction ID observed in the start receipt.')
    if {p['page_id'] for p in evidence['pages']} != {p['page_id'] for p in d['pages']}:
        raise ValueError('Transaction evidence and current snapshot refer to different page sets.')
    before = snapshot(d)
    baseline = snapshot(baseline_readback) if baseline_readback is not None else before
    if mode == 'copy-add' and baseline_readback is None:
        raise ValueError('Additions require the complete baseline from before native text creation.')
    expected = copy.deepcopy(before)
    by_page = {p['page_id']: p for p in before['pages']}
    by_element = {r['element_id']: r for r in expected['richtexts'] if r.get('containerElement', {}).get('type') == 'TEXT'}
    protected = set(protected_pages)
    indices = {p['page_number'] for p in before['pages']}
    policy = design.get('preservation', 'paired-pages')
    if policy == 'whole-design-backup':
        preservation = check_backup(baseline, backup_evidence)
    elif policy == 'paired-pages' and protected and protected.issubset(indices):
        preservation = {'mode': policy, 'protectedPageIndices': sorted(protected)}
    else:
        raise ValueError('List the existing original pages to protect after copying/reordering.')
    if not protected.issubset(indices):
        raise ValueError('Unknown protected page index.')
    baseline_ids = {r['element_id'] for r in baseline['richtexts']}
    if mode == 'copy-add':
        for key, field in [('pages', 'page_id'), ('fills', 'element_id')]:
            if {r[field]: r for r in baseline[key]} != {r[field]: r for r in before[key]}:
                raise ValueError('Native text creation changed original pages/photos/graphics.')
        current_records = {r['element_id']: r for r in before['richtexts']}
        if any(current_records.get(r['element_id']) != r for r in baseline['richtexts']):
            raise ValueError('Native text creation changed an original record.')
    requests = []
    source_ids = set()
    bound_pages = set()
    edit_ids = set()
    changed = []
    additions = []
    for page in design['pages']:
        sid = page['id']
        pid = mapping.get('pages', {}).get(sid)
        if sid in source_ids or pid not in by_page or pid in bound_pages:
            raise ValueError('Missing, duplicate or ambiguous observed page mapping.')
        source_ids.add(sid)
        bound_pages.add(pid)
        index = by_page[pid]['page_number']
        if index in protected:
            raise ValueError('An edit targets a protected original page.')
        if not by_page[pid].get('is_editable', False) or not (page.get('edits') or page.get('additions')):
            raise ValueError('Target page must be editable and contain requested substitutions.')
        operations = []
        for edit in page.get('edits', []):
            eid = mapping.get('elements', {}).get(edit['id'])
            if edit['id'] in edit_ids or eid not in by_element:
                raise ValueError('Each edit needs a unique source ID and an observed text-element mapping.')
            if mode == 'copy-add' and eid not in baseline_ids:
                raise ValueError('Existing-text edits must target a baseline element; use additions for new text.')
            edit_ids.add(edit['id'])
            r = by_element[eid]
            if r['page_index'] != index:
                raise ValueError('Text element does not belong to its mapped target page.')
            find, replacement = edit['find'], edit['replace']
            if not isinstance(find, str) or not find or not isinstance(replacement, str) or not replacement.strip() or find == replacement:
                raise ValueError('Provide a nonempty exact find and a different nonempty replacement.')
            regions = [z for z in r['regions'] if find in z['text']]
            if text(r).count(find) != 1 or len(regions) != 1:
                raise ValueError('Find text must occur exactly once within one native text region. Split mixed-style substitutions by region.')
            regions[0]['text'] = regions[0]['text'].replace(find, replacement, 1)
            operations.append({'type': 'find_and_replace_text', 'element_id': eid, 'find_text': find, 'replace_text': replacement})
            changed.append(eid)
        for item in page.get('additions', []):
            eid = mapping.get('elements', {}).get(item['id'])
            if mode != 'copy-add' or item['id'] in edit_ids or eid in baseline_ids or eid in additions or eid not in by_element:
                raise ValueError('Addition must uniquely bind a newly observed native TEXT element.')
            edit_ids.add(item['id'])
            r = by_element[eid]
            if r['page_index'] != index:
                raise ValueError('New text belongs to the wrong page; fix UI insertion and reread IDs.')
            box, fmt, wording = item['box'], item['formatting'], item['text']
            dim = by_page[pid]['dimension']
            if not isinstance(wording, str) or not wording.strip():
                raise ValueError('Addition text is empty.')
            if any(not isinstance(box.get(k), (int, float)) or isinstance(box[k], bool) or not math.isfinite(box[k]) for k in ('x', 'y', 'width')):
                raise ValueError('Addition geometry must be finite numbers.')
            if box['x'] < 0 or box['y'] < 0 or box['width'] <= 0 or box['x'] + box['width'] > dim['width'] or box['y'] >= dim['height']:
                raise ValueError('Addition is outside its intended page.')
            allowed = {'color', 'font_size', 'font_style', 'font_weight', 'line_height', 'link', 'list_level', 'list_marker', 'strikethrough', 'text_align', 'decoration'}
            if set(fmt) - allowed or not isinstance(fmt.get('font_size'), (int, float)) or isinstance(fmt['font_size'], bool) or not math.isfinite(fmt['font_size']) or fmt['font_size'] <= 0:
                raise ValueError('Use supported formatting and a positive inherited body size.')
            operations.extend([
                {'type': 'replace_text', 'element_id': eid, 'text': wording},
                {'type': 'format_text', 'element_id': eid, 'formatting': fmt},
                {'type': 'resize_element', 'element_id': eid, 'width': box['width']},
                {'type': 'position_element', 'element_id': eid, 'left': box['x'], 'top': box['y']}])
            r['regions'] = [{'type': 'character', 'text': wording}]
            r['containerElement']['position'] = {'left': box['x'], 'top': box['y']}
            additions.append(eid)
            changed.append(eid)
        requests.append({'sourcePageId': sid, 'nativePageId': pid, 'readyToSend': True,
                         'expectedOperationCount': len(operations), 'arguments': {'link_id': link_id, 'transaction_id': transaction_id,
                         'page_index': index, 'operations': operations}})
    if mode == 'copy-add' and set(additions) != {r['element_id'] for r in before['richtexts']} - baseline_ids:
        raise ValueError('Unexpected new native elements; resolve every addition before compiling.')
    return {'mode': mode, 'status': 'compiled_not_applied', 'readyToSend': True, 'preservation': preservation,
            'addedTextIds': additions, 'baseline': baseline,
            'protectedPageIndices': sorted(protected), 'changedTextIds': sorted(set(changed)),
            'requests': requests, 'before': before, 'expected': expected,
            'limitations': 'Existing copy-only targets keep inherited styles. Only new additions receive format/geometry operations. Actual reflow, font inheritance and omitted properties require Canva preview/UI inspection.'}


def verify_plan(plan, readback):
    current = snapshot(readback)
    expected = plan['expected']
    changed = set(plan['changedTextIds'])
    added = set(plan.get('addedTextIds', []))
    observed = {r['element_id']: r for r in current['richtexts']}
    checks = []
    for r in expected['richtexts']:
        eid = r['element_id']
        got = observed.get(eid)
        exact = got == r
        if eid in changed:
            # Canva recalculates text width/height. Do not resize or shrink it to fake equality.
            try:
                a = r['containerElement']['position']
                b = got['containerElement']['position']
                position = all(math.isclose(a[k], b[k], abs_tol=.01) for k in ('top', 'left'))
                exact = text(got) == text(r) and got['page_index'] == r['page_index'] and position
                if eid in added:
                    target = next(a for request in plan['requests'] for a in request['arguments']['operations'] if a['type'] == 'resize_element' and a['element_id'] == eid)
                    measured = got['containerElement']['dimension']
                    page = next(p for p in current['pages'] if p['page_number'] == got['page_index'])
                    exact = exact and math.isclose(measured['width'], target['width'], abs_tol=.01) and b['top'] + measured['height'] <= page['dimension']['height']
            except (KeyError, TypeError):
                exact = False
        checks.append({'elementId': eid, 'passed': exact, 'scope': 'copy_position_width_and_page_bounds' if eid in added else ('copy_and_position' if eid in changed else 'full_returned_record')})
    def indexed(records, field):
        return {r[field]: r for r in records}
    shape_ok = indexed(current['fills'], 'element_id') == indexed(expected['fills'], 'element_id')
    pages_ok = indexed(current['pages'], 'page_id') == indexed(expected['pages'], 'page_id')
    text_set_ok = set(observed) == {r['element_id'] for r in expected['richtexts']}
    return {'passed': shape_ok and pages_ok and text_set_ok and all(c['passed'] for c in checks),
            'photosAndGraphicsUnchanged': shape_ok, 'pageStructureUnchanged': pages_ok, 'textElementSetUnchanged': text_set_ok,
            'checks': checks, 'visualQa': 'unverified_by_script',
            'fontVerification': 'Original styles were not formatted; new text formatting acceptance is separate from visual/UI verification. Omitted font metadata is not proved by this script.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('compile')
    for name in ('design', 'readback', 'mapping', 'link-id', 'transaction-id', 'out'):
        c.add_argument('--' + name, required=True)
    c.add_argument('--protected-pages', type=int, nargs='*', default=[])
    c.add_argument('--baseline-readback', help='Required before native element creation for copy-add.')
    c.add_argument('--backup-evidence', help='Whole-design preservation metadata and readbacks.')
    c.add_argument('--transaction-readback', help='Original start receipt when a later current readback omits transaction metadata.')
    v = sub.add_parser('verify')
    for name in ('plan', 'readback', 'out'):
        v.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'compile':
            result = compile_plan(load(args.design), load(args.readback), load(args.mapping), args.link_id, args.transaction_id, args.protected_pages, load(args.transaction_readback) if args.transaction_readback else None,
                                  load(args.baseline_readback) if args.baseline_readback else None, load(args.backup_evidence) if args.backup_evidence else None)
        else:
            result = verify_plan(load(args.plan), load(args.readback))
        save(args.out, result)
        print(json.dumps({k: result[k] for k in ('status', 'readyToSend', 'passed') if k in result}))
        return 0 if result.get('passed', True) else 1
    except (ValueError, KeyError, TypeError) as exc:
        save(args.out, {'readyToSend': False, 'error': str(exc)})
        print(str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
