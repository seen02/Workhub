"""Durable display-name directory populated only from verified Authentik identities.

Names are presentation; email remains the existing Outline assignment key. Signing out
must not erase a person's name or make historical assignments appear unassigned.
"""
import json
from . import store

def remember(info):
    if not info.get('sub') or not info.get('email') or info.get('email_verified') is not True:
        return
    active='work-assistant-users' in info.get('groups',[])
    entry={'id':info['sub'],'email':info['email'].lower(),
           'name':str(info.get('name') or info.get('preferred_username') or info['email'])[:160],
           'username':str(info.get('preferred_username') or '')[:160],
           'admin':'work-assistant-admins' in info.get('groups',[]),
           'active':active,'verified_at':store.now()}
    store.put('person:'+info['sub'],entry)

def people(include_inactive=False):
    with store.db() as c:
        rows=c.execute("SELECT v FROM kv WHERE k LIKE 'person:%'").fetchall()
    entries=[json.loads(r[0]) for r in rows]
    return sorted([p for p in entries if include_inactive or p['active']],key=lambda p:(p['name'],p['email']))

def names():
    return {p['email']:p['name'] for p in people(include_inactive=True)}

def label(email):
    return names().get(email.lower(),email)

def resolve(person_id):
    person=store.get('person:'+person_id)
    if not person or not person.get('active'):
        raise ValueError('선택한 담당자의 업무 계정 연결을 확인하세요. 관리자 계정 동기화가 필요합니다.')
    return person['email']

def assignments(items):
    """Translate explicit selected account IDs; never fuzzy-match a person's name."""
    return [{**i,'owner':resolve(i['assignee_id'])} if i.get('assignee_id') else i for i in items]
