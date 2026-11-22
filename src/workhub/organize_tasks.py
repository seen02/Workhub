"""Explicit, resumable hierarchy migration. Never runs during ordinary sync."""
import argparse, json, sqlite3, uuid
from pathlib import Path
from . import outline, domain, store

def snapshot():
    return [{'project':p,'documents':[outline.api('documents.info',{'id':d['id']})
        for d in outline.all_items('documents.list',{'collectionId':p['id']})
        if d.get('publishedAt') and not d.get('archivedAt') and not d.get('deletedAt')]}
        for p in outline.projects()]

def is_task(d):return domain.is_legacy_task(d.get('text',''))

def organize(apply=False):
    before=snapshot()
    plan=[{'project':p['project']['name'],'collectionId':p['project']['id'],
        'tasks':[{'id':d['id'],'title':d['title'],'parentDocumentId':d.get('parentDocumentId')} for d in p['documents'] if is_task(d)]} for p in before]
    if not apply:return {'apply':False,'plan':plan}
    folder=Path(store.DB).parent/'hierarchy-backups'/str(uuid.uuid4());folder.mkdir(parents=True)
    (folder/'before.json').write_text(store.dump(before),encoding='utf-8')
    with store.db() as src,sqlite3.connect(folder/'workhub.sqlite3') as dst:src.backup(dst)
    result={'at':store.now(),'backup':str(folder),'projects':[],'moved':0,'verified':False}
    def save():(folder/'result.json').write_text(store.dump(result),encoding='utf-8')
    save()
    # Each successful move is journaled. Rerunning skips already organized tasks.
    for group in before:
        cid=group['project']['id'];tasks=[d for d in group['documents'] if is_task(d)]
        if not tasks:continue
        parent=outline.task_parent(cid)
        entry={'name':group['project']['name'],'collectionId':cid,'parentId':parent['id'],'parentUrl':outline.PUBLIC+parent['url'],'tasks':[]}
        result['projects'].append(entry);save()
        for old in tasks:
            current=outline.api('documents.info',{'id':old['id']})
            for field in ('text','collectionId','parentDocumentId','updatedAt'):
                if current.get(field)!=old.get(field):raise RuntimeError('Migration interrupted: document changed '+old['id'])
            moved=current.get('parentDocumentId')!=parent['id']
            if moved:outline.api('documents.move',{'id':old['id'],'collectionId':cid,'parentDocumentId':parent['id']})
            after=outline.api('documents.info',{'id':old['id']})
            assert after['parentDocumentId']==parent['id']
            for field in ('id','title','text','url','collectionId'):assert after.get(field)==old.get(field),(old['id'],field)
            entry['tasks'].append({'id':old['id'],'title':old['title'],'moved':moved,'contentPreserved':True,
                'revisionBefore':old.get('revision'),'revisionAfter':after.get('revision')})
            result['moved']+=int(moved);save()
        for old in group['documents']:
            if is_task(old):continue
            after=outline.api('documents.info',{'id':old['id']})
            for field in ('id','title','text','url','collectionId','parentDocumentId','revision','updatedAt'):
                assert after.get(field)==old.get(field),(old['id'],field)
        entry['referenceDocumentsUnchanged']=True;save()
    outline.sync();result['verified']=True;save()
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    print(json.dumps(organize(args.apply),ensure_ascii=False,indent=2))
