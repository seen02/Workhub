"""Directory read only; account deactivation triggers Authentik's native logout."""
from datetime import timedelta
from pathlib import Path
import json
from django.utils import timezone
from authentik.core.models import User, Token
from authentik.rbac.models import Role

user, _ = User.objects.get_or_create(username='workhub-directory-reader', defaults={
    'name':'Workhub directory reader', 'type':'service_account', 'path':'service-accounts'})
user.set_unusable_password()
user.save()
role,_=Role.objects.get_or_create(name='Workhub directory read only')
role.assign_perms(['authentik_core.view_user', 'authentik_core.view_group'])
user.roles.add(role)
token, _ = Token.objects.get_or_create(identifier='workhub-directory-reader', defaults={
    'user':user, 'intent':'api', 'expiring':True, 'expires':timezone.now()+timedelta(days=365),
    'description':'Workhub employee inventory; read users and groups only'})
Path('/tmp/workhub-reader.json').write_text(json.dumps({'token':token.key,'expires':str(token.expires)}))
Path('/tmp/workhub-reader.json').chmod(0o600)
from authentik.providers.oauth2.models import OAuth2Provider
provider=OAuth2Provider.objects.get(application__slug='outline-webui')
provider.logout_uri='http://host.docker.internal:3001/oauth/backchannel-logout'
provider.logout_method='backchannel'
provider.save()
print('Read-only directory and signed OIDC back-channel logout configured (secret omitted).')
