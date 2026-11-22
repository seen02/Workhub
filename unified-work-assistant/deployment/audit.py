"""Read-only restored-data inventory; no secrets or document contents are printed."""
import argparse,json,pathlib
import manage

def capture(project):
    def sql(service,user,db,tables):
        query=' UNION ALL '.join("SELECT '"+t+"',count(*) FROM \""+t+'"' for t in tables)
        raw=manage.compose(project,'exec','-T',service,'psql','-U',user,'-d',db,'-At','-c',query)
        return {k:int(v) for k,v in (line.split('|') for line in raw.strip().splitlines())}
    def sqlite(service,path,tables):
        code="import sqlite3,json; c=sqlite3.connect('file:"+path+"?mode=ro',uri=True); print(json.dumps({t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in "+repr(tables)+"}))"
        return json.loads(manage.compose(project,'exec','-T',service,'python','-c',code))
    return {'outline':sql('postgres','outline','outline',['documents','revisions','collections','users','attachments']),
        'authentik':sql('postgresql','authentik','authentik',['authentik_core_user','authentik_core_application']),
        'workhub':sqlite('workhub','/app/data/workhub.sqlite3',['tasks','events','proposals']),
        'webui':sqlite('open-webui','/app/backend/data/webui.db',['chat','user','model','tool']),
        'document_agent':sqlite('document-agent','/app/data/agent.sqlite3',['drafts','events','research','files']),
        'rocketchat':json.loads(manage.compose(project,'exec','-T','mongodb','mongosh','--quiet','--eval',
            "JSON.stringify({users:db.getSiblingDB('rocketchat').users.countDocuments(),messages:db.getSiblingDB('rocketchat').rocketchat_message.countDocuments(),rooms:db.getSiblingDB('rocketchat').rocketchat_room.countDocuments()})")),
        'rag':sql('rag-postgres','rag','rag',['rag_documents','rag_chunks','rag_workhub_projects'])}
def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True,type=manage.project_name);p.add_argument('--compare');a=p.parse_args()
    data=capture(a.project);result={'at':manage.now(),'project':a.project,'counts':data}
    if a.compare:
        expected=manage.read(a.compare)['counts'];result['matches_backup_inventory']=expected==data
        if expected!=data:
            result['differences']={k:{'before':expected[k],'after':data[k]} for k in expected if expected[k]!=data[k]}
    manage.write(manage.ROOT/'reports'/('inventory-'+a.project+'.json'),result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if a.compare and not result['matches_backup_inventory']:raise SystemExit(1)
if __name__=='__main__':main()
