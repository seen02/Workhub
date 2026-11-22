"""Project-scoped bridge to the shared document RAG; no credentials reach the browser."""
import logging, os, threading
import httpx
from fastapi import HTTPException
from . import outline, auth, permissions, http_pool

dirty = threading.Event()

def agent(path, body=None, timeout=35, user=None):
    from .search_identity import issue
    headers={'Authorization':'Bearer '+os.environ['AGENT_TOKEN']}
    if user is not None:headers['X-Workhub-Identity']=issue(user)
    try:
        r=http_pool.request('document-agent','GET' if body is None else 'POST',os.environ['DOCUMENT_AGENT_URL']+path,metric=path,
            headers=headers,json=body,timeout=timeout)
    except httpx.HTTPError:
        raise HTTPException(503,'자료 검색 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.')
    if not r.is_success:
        detail=r.json().get('detail','자료 검색 요청에 실패했습니다.')
        raise HTTPException(r.status_code if r.status_code in (403,409,422,503) else 502,detail)
    return r.json()

def sync_registry():
    refresh=dirty.is_set()
    dirty.clear()
    try:
        from . import knowledge
        if knowledge.enabled():
            projects=[{'id':p['id'],'name':p['name']} for p in knowledge.targets() if p['included']]
            return agent('/rag/workhub/projects',{'projects':projects,'refresh':refresh,'managed':True})
        return agent('/rag/workhub/projects',{'projects':[{'id':p['id'],'name':p['name']} for p in outline.projects()], 'refresh':refresh})
    except Exception:
        if refresh:dirty.set()
        raise

def authorize(user, collection_id):
    auth.allowed(user)
    return permissions.project(user,collection_id)

def status(user, collection_id):
    p=authorize(user,collection_id)
    sync_registry()
    d=agent('/rag/status')
    entry=next((s for s in d.get('collections',[]) if s['collection_id']==p['id']),None)
    result=entry.get('result',{}) if entry else {}
    return {'project':p['name'],'collection_id':p['id'],'state':('disabled' if not d.get('enabled') else
        'syncing' if d.get('syncing') else 'preparing' if not entry else
        'partial' if result.get('failed') or not result.get('inventory_complete') or d.get('poll_error') else 'ready'),
        'documents':result.get('inventory_count',0),'failed':len(result.get('failed',[])),
        'synced_at':entry.get('synced_at') if entry else None}

def refresh(user, collection_id):
    auth.admin(user);p=authorize(user,collection_id);sync_registry()
    agent('/rag/sync',{'collection_id':p['id']},timeout=240)
    return status(user,p['id'])
