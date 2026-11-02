#!/usr/bin/env python3
"""POST local assets once to tool-issued single-use Canva URLs. Standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_receipt(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    temporary.replace(path)


def prepare_queue(queue_path, previous):
    queue_path = Path(queue_path).resolve()
    queue = read_json(queue_path)
    if not isinstance(queue, list) or not queue:
        raise ValueError('Queue must be a non-empty list')
    used = {r.get('urlFingerprint') for r in previous.get('attempts', [])}
    ids, fingerprints, prepared = set(), set(), []
    for item in queue:
        identity, raw_url = item.get('id'), item.get('uploadUrl')
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('Each queue item needs a unique non-empty id')
        if not isinstance(raw_url, str):
            raise ValueError('Missing uploadUrl for ' + identity)
        url = urllib.parse.urlparse(raw_url)
        host = (url.hostname or '').lower()
        if url.scheme != 'https' or not (host == 'canva.com' or host.endswith('.canva.com')) or url.username or url.password or url.fragment or url.port not in (None, 443):
            raise ValueError('Expected a tool-issued HTTPS Canva URL for ' + identity)
        fingerprint = hashlib.sha256(raw_url.encode()).hexdigest()
        if fingerprint in used or fingerprint in fingerprints:
            raise ValueError('Single-use URL already attempted or duplicated for ' + identity + '; obtain a new URL')
        raw_path = item.get('path')
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError('Missing file path for ' + identity)
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = queue_path.parent / path
        path = path.resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('Missing or empty file for ' + identity)
        ids.add(identity)
        fingerprints.add(fingerprint)
        prepared.append((identity, path, raw_url, fingerprint))
    return prepared


def upload(queue_path, out_path, opener=None):
    out_path = Path(out_path)
    receipt = read_json(out_path) if out_path.exists() else {'schemaVersion': 1, 'attempts': []}
    if not isinstance(receipt.get('attempts'), list):
        raise ValueError('Invalid existing receipt')
    prepared = prepare_queue(queue_path, receipt)
    opener = opener or urllib.request.build_opener(NoRedirect)
    for identity, path, url, fingerprint in prepared:
        payload = path.read_bytes()
        attempt = {'id': identity, 'path': str(path), 'urlFingerprint': fingerprint,
                   'fileSha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload),
                   'attempted': True, 'status': 'started'}
        receipt['attempts'].append(attempt)
        # Persist before sending: even an interrupted connection consumes this URL.
        save_receipt(out_path, receipt)
        request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/octet-stream'}, method='POST')
        try:
            with opener.open(request, timeout=45) as response:
                status = response.status
                body = response.read()
            attempt['httpStatus'] = status
            attempt['response'] = json.loads(body)
            if not 200 <= status < 300:
                raise ValueError('Non-success HTTP status')
            attempt['status'] = 'received'
        except Exception as error:
            attempt['status'] = 'failed'
            attempt['errorType'] = type(error).__name__
            if isinstance(error, urllib.error.HTTPError):
                attempt['httpStatus'] = error.code
            # Do not print exception strings: some include the signed URL.
            save_receipt(out_path, receipt)
            return False
        save_receipt(out_path, receipt)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True, help='Private JSON list of id/path/uploadUrl; relative paths resolve from this file')
    parser.add_argument('--out', required=True, help='Append-only attempt receipt; signed URLs are omitted')
    args = parser.parse_args()
    try:
        ok = upload(args.queue, args.out)
    except (ValueError, OSError, TypeError, json.JSONDecodeError) as error:
        print('Upload blocked: ' + str(error), file=sys.stderr)
        return 2
    print('Upload responses recorded' if ok else 'Upload failed; obtain a fresh URL before retrying')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
