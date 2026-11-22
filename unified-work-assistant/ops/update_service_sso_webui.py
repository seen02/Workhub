"""Patch only SSO bridge methods in existing WebUI tools; run inside Open WebUI.

Default is a read-only preview. --apply backs up definitions and preserves existing
tool methods, valves, access grants and IDs. No users or conversations are rewritten.
"""
import argparse
import ast
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import time

TARGETS = [('tools', name) for name in ('outline_read', 'outline_write', 'outline_files', 'outline_edit')]
TARGETS += [('functions', 'outline_receipt')]


def spans(content):
    tree = ast.parse(content)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Tools')
    methods = {node.name: node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)}
    identity = methods['_identity_headers']
    run = methods['_run']
    handlers = next(node.handlers for node in run.body if isinstance(node, ast.Try)
                    and any(isinstance(h.type, ast.Attribute) and h.type.attr == 'HTTPStatusError'
                            for h in node.handlers))
    start = next(h for h in handlers if isinstance(h.type, ast.Attribute) and h.type.attr == 'HTTPStatusError')
    return [(identity.lineno - 1, identity.end_lineno), (start.lineno - 1, handlers[-1].end_lineno)]


def patch_content(content, bridge):
    old_spans, new_spans = spans(content), spans(bridge)
    lines, new_lines = content.splitlines(keepends=True), bridge.splitlines(keepends=True)
    for (start, end), (new_start, new_end) in reversed(list(zip(old_spans, new_spans))):
        lines[start:end] = new_lines[new_start:new_end]
    result = ''.join(lines)
    compile(result, '<updated-webui-tool>', 'exec')
    return result


def apply_updates(client, updates):
    attempted = []
    try:
        for kind, ident, before, after in updates:
            attempted.append((kind, ident, before))  # Include an ambiguous failed write.
            url = f'/api/v1/{kind}/id/{ident}'
            response = client.post(url + '/update', json=after, timeout=60)
            response.raise_for_status()
            check = client.get(url, timeout=30); check.raise_for_status()
            if check.json()['content'] != after['content']:
                raise RuntimeError('WebUI source verification failed')
    except Exception:
        failed = []
        for kind, ident, before in reversed(attempted):
            try:
                url = f'/api/v1/{kind}/id/{ident}'
                result = client.post(url + '/update', json=before, timeout=60)
                result.raise_for_status()
                check = client.get(url, timeout=30); check.raise_for_status()
                if check.json()['content'] != before['content']: raise RuntimeError()
            except Exception: failed.append(ident)
        raise RuntimeError('Update failed; ' + ('manual restore needed for: ' + ', '.join(failed)
                           if failed else 'previous tool definitions restored.')) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge', type=Path, required=True)
    parser.add_argument('--admin-email', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path, default=Path('/app/backend/data/workhub-sso-backups'))
    args = parser.parse_args()
    bridge = args.bridge.read_text(encoding='utf-8')
    spans(bridge)  # Validate before connecting to the local service.
    sys.path.insert(0, '/app/backend')
    os.environ['WEBUI_SECRET_KEY'] = os.environ.get('WEBUI_SECRET_KEY') or Path('/app/backend/.webui_secret_key').read_text().strip()
    from open_webui.models.users import Users
    from open_webui.utils.auth import create_token
    import requests
    admin = asyncio.run(Users.get_user_by_email(args.admin_email))
    if not admin or admin.role != 'admin': raise RuntimeError('An existing WebUI administrator is required.')
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + create_token({'id': admin.id})

    class LocalClient:
        def get(self, path, **kwargs): return session.get('http://127.0.0.1:8080' + path, **kwargs)
        def post(self, path, **kwargs): return session.post('http://127.0.0.1:8080' + path, **kwargs)

    client = LocalClient()
    updates = []
    # Prepare and compile ALL definitions before making any changes.
    for kind, ident in TARGETS:
        response = client.get(f'/api/v1/{kind}/id/{ident}', timeout=30)
        response.raise_for_status()
        before = response.json(); after = copy.deepcopy(before)
        after['content'] = patch_content(before['content'], bridge)
        if after['content'] != before['content']: updates.append((kind, ident, before, after))
    print('SSO tool definitions to update:', len(updates))
    if not args.apply or not updates: return
    args.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = args.backup_dir / ('before-sso-' + str(time.time_ns()) + '.json')
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump([{'kind': k, 'id': i, 'definition': before} for k, i, before, _ in updates], output)
    print('Backup:', backup)
    apply_updates(client, updates)
    print('Verified SSO update. Tool settings, access grants and conversations preserved.')


if __name__ == '__main__': main()
