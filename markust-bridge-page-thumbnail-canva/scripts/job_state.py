#!/usr/bin/env python3
"""Offline stage reuse ledger. No network, Canva calls, generation or authentication."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve(root, path):
    p = Path(path)
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def plan(spec, state, root):
    root = Path(root)
    rows, fingerprints, reusable = [], {}, {}
    stages = spec['stages']
    ids = [s['id'] for s in stages]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate stage IDs.')
    for stage in stages:
        sid = stage['id']
        deps = stage.get('dependsOn', [])
        if any(d not in fingerprints for d in deps):
            raise ValueError('Stages must be dependency-ordered; no missing or circular dependency.')
        files, missing = {}, []
        for name in stage.get('files', []):
            path = resolve(root, name)
            if path.is_file():
                files[name] = file_hash(path)
            else:
                missing.append(name)
        parent_outputs = {d: state.get('stages', {}).get(d, {}).get('outputs', {}) for d in deps}
        fp = digest({'params': stage.get('params', {}), 'files': files,
                     'dependencies': {d: fingerprints[d] for d in deps}, 'parentOutputs': parent_outputs})
        fingerprints[sid] = fp
        previous = state.get('stages', {}).get(sid, {})
        outputs = previous.get('outputs', {})
        valid_outputs = bool(outputs) and all(resolve(root, p).is_file() and file_hash(resolve(root, p)) == h for p,h in outputs.items())
        ok = not missing and all(reusable[d] for d in deps) and previous.get('fingerprint') == fp and previous.get('qaStatus') == 'passed' and valid_outputs
        reusable[sid] = ok
        reason = 'verified_unchanged' if ok else 'missing_input' if missing else 'dependency_changed' if any(not reusable[d] for d in deps) else 'input_changed' if previous.get('fingerprint') != fp else 'qa_not_passed' if previous.get('qaStatus') != 'passed' else 'output_missing_or_changed'
        rows.append({'id': sid, 'action': 'reuse' if ok else 'run', 'reason': reason, 'fingerprint': fp, 'missingInputs': missing})
    return {'stages': rows, 'runCount': sum(r['action'] == 'run' for r in rows), 'reuseCount': sum(r['action'] == 'reuse' for r in rows)}


def record(spec, state, root, stage_id, outputs, qa_status, usage=None):
    result = plan(spec, state, root)
    row = next((r for r in result['stages'] if r['id'] == stage_id), None)
    if row is None or row['missingInputs']:
        raise ValueError('Unknown stage or missing input.')
    stage = next(s for s in spec['stages'] if s['id'] == stage_id)
    by_id = {r['id']: r for r in result['stages']}
    if any(by_id[d]['action'] != 'reuse' for d in stage.get('dependsOn', [])):
        raise ValueError('Record and verify dependencies first.')
    if qa_status not in ('passed', 'failed', 'unverified') or not outputs:
        raise ValueError('Record explicit QA status and actual output files.')
    actual = {str(p): file_hash(resolve(Path(root), p)) for p in outputs}
    entry = {'fingerprint': row['fingerprint'], 'outputs': actual, 'qaStatus': qa_status,
             'usage': usage or {'toolCalls': None, 'inputTokens': None, 'outputTokens': None}}
    state.setdefault('history', []).append({'stage': stage_id, **entry})
    state.setdefault('stages', {})[stage_id] = entry
    state['schemaVersion'] = 1
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'record'])
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--stage')
    parser.add_argument('--outputs', nargs='*', default=[])
    parser.add_argument('--qa-status', choices=['passed', 'failed', 'unverified'])
    parser.add_argument('--usage-json', type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    root = args.spec.resolve().parent
    if args.command == 'record':
        usage = json.loads(args.usage_json.read_text()) if args.usage_json else None
        record(spec, state, root, args.stage, args.outputs, args.qa_status, usage)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        temp = args.state.with_name(args.state.name + '.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
        temp.replace(args.state)
    print(json.dumps(plan(spec, state, root), ensure_ascii=False))


if __name__ == '__main__':
    main()
