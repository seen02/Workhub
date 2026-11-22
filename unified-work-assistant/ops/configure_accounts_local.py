"""Update the ORIGINAL compose only; preserve original mounts and all other settings."""
import json, pathlib, shutil
root=pathlib.Path(__file__).resolve().parents[1]
cfg=root/'.local/compose.json'
backup=root/'.local/original-before-accounts'
backup.mkdir(exist_ok=True)
if not (backup/'compose.json').exists():shutil.copy2(cfg,backup/'compose.json')
d=json.loads(cfg.read_text(encoding='utf-8-sig'))
secret=json.loads((root/'.local/account-reader.json').read_text())
d['services']['workhub']['environment'].update({
    'AUTHENTIK_API_URL':d['services']['workhub']['environment']['OIDC_ISSUER'].split('/application')[0],
    'AUTHENTIK_DIRECTORY_TOKEN':secret['token'].replace('$','$$'),
    'ACCOUNT_SECURITY_CHECK_SECONDS':'60'})
d['services']['workhub']['environment'].pop('ACCOUNT_SYNC_SECONDS',None)
# Installed WebUI supports signed OIDC back-channel token revocation via Redis.
# No WebUI administrator credential is issued or stored.
d['services']['open-webui']['environment']['REDIS_URL']='redis://redis:6379/5'
d['services']['open-webui']['environment']['ENABLE_OAUTH_BACKCHANNEL_LOGOUT']='true'
d['services']['open-webui']['networks']['outline-net']=None
cfg.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
print('Original compose updated. Credentials expire:',secret['expires'])
