"""Read-only comparison against the pre-change SQLite backup."""
import json,pathlib,sqlite3
root=pathlib.Path(__file__).resolve().parents[1]
base=sqlite3.connect(root/'.local/original-before-accounts/workhub.sqlite3')
live=sqlite3.connect('file:'+str(root/'runtime/workhub/workhub.sqlite3')+'?mode=ro',uri=True)
result={}
for table,columns in {'tasks':'id','events':'seq,doc_id,source_key','proposals':'id'}.items():
    before=set(base.execute('SELECT '+columns+' FROM '+table))
    after=set(live.execute('SELECT '+columns+' FROM '+table))
    assert before<=after,table+' original rows missing'
    result[table]={'before':len(before),'after':len(after),'all_original_records_preserved':True}
(root/'reports/accounts-preservation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
