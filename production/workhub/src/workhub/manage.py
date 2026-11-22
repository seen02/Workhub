"""Local administrative commands; no public administration endpoint."""
import argparse
import json
from . import store, lifecycle, outline, project_service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['sync-accounts', 'sync-tasks', 'status', 'map-group'])
    parser.add_argument('--authentik-group-id')
    args = parser.parse_args()
    store.init()
    if args.command == 'sync-accounts':
        result = lifecycle.reconcile()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get('ok'):
            raise SystemExit(1)
    elif args.command == 'sync-tasks':
        jobs = project_service.sync_snapshot()
        outline.sync_shared()
        project_service.sync_complete(jobs)
        print(json.dumps(store.get('last_sync'), ensure_ascii=False, indent=2))
    elif args.command == 'map-group':
        if not args.authentik_group_id:
            parser.error('--authentik-group-id is required')
        print(json.dumps(lifecycle.map_group(args.authentik_group_id, {'email': 'local administrator'}), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({'sync': store.get('employee_sync'), 'task_sync': store.get('last_sync'),
                         'accounts': [{'email': r['email'], 'active': r.get('active'),
                                       'review': r.get('review'), 'outline_id': r.get('outline_id')}
                                      for r in lifecycle.records()]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
