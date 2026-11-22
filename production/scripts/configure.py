"""Generate fresh configuration and configure this deployment's OIDC provider."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def load_env(path=None):
    path = path or ROOT / '.env'
    if not path.exists():
        raise SystemExit('Run configure.py init first.')
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip("'\"")
    return values


def save_env(values):
    path = ROOT / '.env'
    path.write_text('# Generated only for this independent deployment. Keep private.\n' +
                    ''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    try:
        path.chmod(0o600)
    except OSError:
        pass


def public_urls(env):
    port = env.get('PUBLIC_PORT', env['HTTP_PORT'])
    return (f"http://{env['OUTLINE_DOMAIN']}:{port}",
            f"http://{env.get('AUTH_PUBLIC_DOMAIN', env['AUTH_DOMAIN'])}:{port}")


def call_api(base, path, token, body=None, method=None, host=None):
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    if host:
        headers['Host'] = host
    request = urllib.request.Request(base.rstrip('/') + path,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers=headers, method=method or ('GET' if body is None else 'POST'))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise SystemExit(f'API {path} returned HTTP {error.code}. Check service readiness and credentials.') from None
    except urllib.error.URLError:
        raise SystemExit('Service connection failed. Start the selected stack and check the proxy port.') from None


def init(args):
    if (ROOT / '.env').exists():
        raise SystemExit('.env already exists; refusing to replace secrets or change the deployment mode.')
    if not args.admin_email or '@' not in args.admin_email:
        raise SystemExit('--admin-email is required.')
    profile = getattr(args, 'profile', 'local')
    if profile == 'vm' and args.mode != 'docker':
        raise SystemExit('The VM profile requires --mode docker.')
    env = load_env(ROOT / ('.env.vm.example' if profile == 'vm' else '.env.example'))
    env['DEPLOY_MODE'] = args.mode
    env['AUTHENTIK_BOOTSTRAP_EMAIL'] = args.admin_email
    for key in ['OUTLINE_DB_PASSWORD', 'AUTHENTIK_DB_PASSWORD', 'OUTLINE_SECRET_KEY',
                'OUTLINE_UTILS_SECRET', 'AUTHENTIK_SECRET_KEY', 'AUTHENTIK_BOOTSTRAP_PASSWORD',
                'AUTHENTIK_BOOTSTRAP_TOKEN', 'OIDC_CLIENT_SECRET', 'OUTLINE_WORKHUB_BRIDGE_SECRET']:
        env[key] = secrets.token_hex(32)
    env['AUTHENTIK_DIRECTORY_TOKEN'] = env['AUTHENTIK_BOOTSTRAP_TOKEN']
    save_env(env)
    outline, auth = public_urls(env)
    print(f'Created .env for {args.mode}; credentials are in .env, not in images.')
    print(f'Outline: {outline}\nAuthentik: {auth}\nInitial administrator: akadmin')
    if profile == 'vm':
        print('Use compose.yaml + compose.vm.yaml. Team members do not need hosts entries.')
        print(f"Administrator hosts entry: VM_IP {env['AUTH_DOMAIN']}")
    else:
        print(f"Hosts entry: 127.0.0.1 {env['OUTLINE_DOMAIN']} {env['AUTH_DOMAIN']}")


def oidc(args):
    env = load_env()
    outline_url, auth_url = public_urls(env)
    base = f"http://127.0.0.1:{env['HTTP_PORT']}"
    port = env.get('PUBLIC_PORT', env['HTTP_PORT'])
    host = f"{env['AUTH_DOMAIN']}:{port}"
    prefix = env.get('AUTHENTIK_PATH', '/').rstrip('/')
    token = env['AUTHENTIK_BOOTSTRAP_TOKEN']
    def api(path, body=None, method=None):
        return call_api(base, prefix + '/api/v3/' + path, token, body, method, host)
    def listing(path):
        result, page = [], 1
        while True:
            payload = api(path + f'?page_size=100&page={page}')
            result.extend(payload['results'])
            if not payload.get('pagination', {}).get('next'):
                return result
            page += 1
    groups = listing('core/groups/')
    for name in ['work-assistant-users', 'work-assistant-admins']:
        if not any(group['name'] == name for group in groups):
            groups.append(api('core/groups/', {'name': name, 'is_superuser': False}))
    admins = [user for user in listing('core/users/') if user['username'] == 'akadmin']
    if len(admins) != 1 or not admins[0].get('is_active') or not admins[0].get('email'):
        raise SystemExit('An active akadmin account with an email is required.')
    admin = admins[0]
    role_ids = [group['pk'] for group in groups if group['name'] in ('work-assistant-users', 'work-assistant-admins')]
    api(f"core/users/{admin['pk']}/", {'groups': list(set(admin.get('groups', []) + role_ids))}, 'PATCH')
    mappings = listing('propertymappings/provider/scope/')
    specs = [
        {'name': 'Custom Outline email', 'scope_name': 'email',
         'expression': 'return {"email": request.user.email, "email_verified": bool(request.user.attributes.get("email_verified", False))}'},
        {'name': 'Custom Outline groups', 'scope_name': 'work_groups',
         'expression': 'return {"groups": list(request.user.ak_groups.values_list("name", flat=True))}'}]
    mapping_ids = []
    for spec in specs:
        old = next((mapping for mapping in mappings if mapping['name'] == spec['name']), None)
        saved = api('propertymappings/provider/scope/' + (str(old['pk']) + '/' if old else ''), spec, 'PATCH' if old else 'POST')
        mapping_ids.append(saved['pk'])
    # Only the known bootstrap administrator is verified here. Verify employee
    # addresses before setting their email_verified attribute in Authentik.
    api(f"core/users/{admin['pk']}/", {'attributes': {**admin.get('attributes', {}), 'email_verified': True}}, 'PATCH')
    for scope in ['openid', 'profile']:
        mapping = next((value for value in mappings if value.get('scope_name') == scope), None)
        if not mapping:
            raise SystemExit(f'Default {scope} scope mapping is not ready. Wait for Authentik bootstrap.')
        mapping_ids.append(mapping['pk'])
    flows = listing('flows/instances/')
    def flow(slug):
        match = next((value for value in flows if value['slug'] == slug), None)
        if not match:
            raise SystemExit(f'Default flow {slug} is not ready. Wait for Authentik bootstrap.')
        return match['pk']
    certificates = listing('crypto/certificatekeypairs/')
    cert = next((value for value in certificates if value['name'] == 'authentik Self-signed Certificate'), None)
    if not cert:
        raise SystemExit('Default OIDC signing certificate is not ready.')
    payload = {'name': 'Custom Outline', 'authorization_flow': flow('default-provider-authorization-implicit-consent'),
               'invalidation_flow': flow('default-provider-invalidation-flow'), 'property_mappings': mapping_ids,
               'client_type': 'confidential', 'grant_types': ['authorization_code', 'refresh_token'],
               'client_id': env['OIDC_CLIENT_ID'], 'client_secret': env['OIDC_CLIENT_SECRET'],
               'include_claims_in_id_token': True, 'signing_key': cert['pk'], 'sub_mode': 'user_uuid',
               'issuer_mode': 'per_provider', 'redirect_uris': [{'matching_mode': 'strict', 'url': outline_url + '/auth/oidc.callback', 'redirect_uri_type': 'authorization'}]}
    provider = next((value for value in listing('providers/oauth2/') if value['client_id'] == env['OIDC_CLIENT_ID']), None)
    provider = api('providers/oauth2/' + (str(provider['pk']) + '/' if provider else ''), payload, 'PATCH' if provider else 'POST')
    existing = next((value for value in listing('core/applications/') if value['slug'] == 'custom-outline'), None)
    application = api('core/applications/' + ('custom-outline/' if existing else ''),
                      {'name': 'Custom Outline', 'slug': 'custom-outline', 'provider': provider['pk'], 'meta_launch_url': outline_url},
                      'PATCH' if existing else 'POST')
    group = next(value for value in groups if value['name'] == 'work-assistant-users')
    bindings = listing('policies/bindings/')
    if not any(value.get('target') == application['pk'] and value.get('group') == group['pk'] for value in bindings):
        api('policies/bindings/', {'target': application['pk'], 'group': group['pk'], 'order': 0, 'enabled': True, 'negate': False, 'timeout': 30})
    print('OIDC provider and administrator groups configured. Sign into Outline as akadmin.')


def vm(args):
    """Apply VM routing to a Docker deployment while preserving its credentials."""
    env = load_env()
    if env.get('DEPLOY_MODE') != 'docker':
        raise SystemExit('VM routing requires a Docker deployment. Keep the native test folder separate.')
    defaults = load_env(ROOT / '.env.vm.example')
    for key in ['COMPOSE_FILE', 'COMPOSE_PATH_SEPARATOR', 'HTTP_PORT', 'PUBLIC_PORT',
                'OUTLINE_DOMAIN', 'AUTH_DOMAIN', 'AUTH_PUBLIC_DOMAIN', 'AUTHENTIK_PATH']:
        env[key] = defaults[key]
    save_env(env)
    print('Applied VM routing without replacing credentials. Recreate containers and run oidc again.')


def connect(args):
    env = load_env()
    token = getpass.getpass('Outline administrator API key: ').strip()
    if not token:
        raise SystemExit('API key is required.')
    base = f"http://127.0.0.1:{env['HTTP_PORT']}"
    host = urllib.parse.urlsplit(public_urls(env)[0]).netloc
    data = call_api(base, '/api/auth.info', token, {}, host=host)['data']
    if data.get('user', {}).get('role') != 'admin':
        raise SystemExit('Use an Outline administrator API key.')
    env['OUTLINE_API_KEY'] = token
    env['OUTLINE_WORKHUB_TEAM_ID'] = data['team']['id']
    save_env(env)
    print('Saved Outline team and API key. Recreate Workhub (Docker) or restart the native Workhub process, then sync accounts.')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('init')
    create.add_argument('--mode', choices=['docker', 'native'], default='docker')
    create.add_argument('--profile', choices=['local', 'vm'], default='local')
    create.add_argument('--admin-email', required=True)
    sub.add_parser('oidc')
    sub.add_parser('vm')
    sub.add_parser('connect-outline')
    args = parser.parse_args()
    {'init': init, 'vm': vm, 'oidc': oidc, 'connect-outline': connect}[args.command](args)


if __name__ == '__main__':
    main()
