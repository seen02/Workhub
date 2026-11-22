"""Complete inventories gate tombstones; transient failures never mean deletion."""
import asyncio
import hashlib
import json
import time
from fastapi import HTTPException

def version(doc, profile):
    fields={k:doc.get(k) for k in ('id','title','text','revision','updatedAt','collectionId','parentDocumentId','archivedAt','deletedAt','url')}
    return hashlib.sha256(json.dumps([fields,profile,'source-context-v2'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def available(doc, collection):
    collections={collection} if isinstance(collection,str) else set(collection)
    return not doc.get('archivedAt') and not doc.get('deletedAt') and doc.get('collectionId') in collections

class Synchronizer:
    def __init__(self, core, store, embeddings, collection_names):
        self.core=core;self.store=store;self.embeddings=embeddings
        self.collection_names=[collection_names] if isinstance(collection_names,str) else list(collection_names)
        self.lock=asyncio.Lock()

    async def collections(self):
        rows=[]
        for offset in range(0,10000,100):
            page=await self.core.outline('collections.list',{'limit':100,'offset':offset},read=True)
            rows+=page
            if len(page)<100:break
        matches={name:[r for r in rows if r['name']==name] for name in self.collection_names}
        invalid=[name for name,found in matches.items() if len(found)!=1]
        managed=(await self.store.managed_scope()) is True if hasattr(self.store,'managed_scope') else False
        if invalid and not managed:raise HTTPException(409,{'message':'RAG 컬렉션을 하나로 확인하지 못했습니다.','collections':invalid})
        result={} if managed else {name:found[0]['id'] for name,found in matches.items()}
        self.names={r['id']:r['name'] for r in rows}
        # Explicit IDs added by Workhub do not broaden the legacy default scope.
        if hasattr(self.store,'workhub_projects'):
            for p in await self.store.workhub_projects():
                if p['id'] in self.names:result[p['id']]=p['id']
        if managed:
            # Keep legacy callers' name aliases, but only for explicitly active IDs.
            for name,found in matches.items():
                if len(found)==1 and found[0]['id'] in result:result[name]=found[0]['id']
        return result

    async def collection(self):
        """Backward-compatible helper for the first configured collection."""
        return (await self.collections())[self.collection_names[0]]

    async def one(self, docid, collection, force=False):
        try:
            doc=await self.core.info(docid)
            if not available(doc,collection):
                await self.store.deactivate(docid);return 'excluded'
            ver=version(doc,self.store.profile)
            old=await self.store.current(docid)
            if not force and old and old['active'] and old['active_version']==ver:return 'unchanged'
            # A stale accessible copy must not remain searchable while its replacement is built.
            chunks=(await self.embeddings.call(document=doc))['chunks']
            latest=await self.core.info(docid)
            if not available(latest,collection):
                await self.store.deactivate(docid);return 'excluded'
            if version(latest,self.store.profile)!=ver:return 'changed_during_sync'
            await self.store.replace({k:v for k,v in doc.items() if k!='text'},ver,chunks)
            return 'indexed'
        except HTTPException as exc:
            if exc.status_code in (403,404):
                await self.store.deactivate(docid);return 'excluded'
            raise

    async def sync(self, force=False, collection_id=''):
        async with self.lock:
            await self.store.migrate()
            started=time.monotonic();collections=await self.collections()
            if collection_id and collection_id not in collections.values():raise HTTPException(403,'등록된 검색 대상이 아닙니다.')
            total={'inventory_complete':True,'inventory_count':0,'indexed':0,'unchanged':0,'excluded':0,'failed':[],'collections':[]}
            for collection in dict.fromkeys(collections.values()):
                if collection_id and collection!=collection_id:continue
                name=self.names.get(collection,collection)
                rows=[];complete=False;collection_started=time.monotonic()
                for offset in range(0,10000,100):
                    page=await self.core.outline('documents.list',{'collectionId':collection,'limit':100,'offset':offset},read=True)
                    rows+=page
                    if len(page)<100:complete=True;break
                # Only a complete, successful inventory may invalidate absent documents.
                if complete:await self.store.reconcile(collection,[d['id'] for d in rows])
                result={'collection_name':name,'inventory_complete':complete,'inventory_count':len(rows),'indexed':0,'unchanged':0,'excluded':0,'failed':[]}
                for doc in rows:
                    try:
                        state=await self.one(doc['id'],collection,force)
                        if state=='changed_during_sync':result['failed'].append({'id':doc['id'],'reason':state})
                        else:result[state]+=1
                    except Exception as exc:
                        result['failed'].append({'id':doc['id'],'reason':type(exc).__name__})
                result['seconds']=round(time.monotonic()-collection_started,3)
                result['status']='succeeded' if complete and not result['failed'] else 'partial'
                await self.store.sync_state(collection,result)
                total['inventory_complete']=total['inventory_complete'] and complete
                for field in ('inventory_count','indexed','unchanged','excluded'):total[field]+=result[field]
                total['failed'] += [{'collection_name':name,**failure} for failure in result['failed']]
                total['collections'].append(result)
            total['seconds']=round(time.monotonic()-started,3)
            total['status']='succeeded' if total['inventory_complete'] and not total['failed'] else 'partial'
            return total
