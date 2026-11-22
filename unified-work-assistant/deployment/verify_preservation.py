"""Check original container identities/mounts and isolation; never mutates Docker."""
import argparse, json
import manage

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--copy',required=True,type=manage.project_name)
args=parser.parse_args()
saved=manage.read(manage.PRIVATE/'preserved-containers.json')
current=json.loads(manage.run(['docker','inspect',*[c['id'] for c in saved['containers']]]))
byid={c['Id']:c for c in current}
results=[]
sources=set()
for before in saved['containers']:
    after=byid[before['id']]
    # Docker does not guarantee the order of its mount list.
    same_mounts=sorted(after['Mounts'],key=lambda m:m['Destination'])==sorted(before['mounts'],key=lambda m:m['Destination'])
    ok=after['State']['Running'] and after['Image']==before['image'] and same_mounts
    results.append({'service':before['service'],'preserved_and_running':ok,'health':after['State'].get('Health',{}).get('Status','not_configured')})
    sources.update((m['Type'],m.get('Name') or m['Source']) for m in after['Mounts'])
isolated={}
for project in (args.copy,):
    rows=manage.containers(project)
    shared=[c['Name'] for c in rows if any((m['Type'],m.get('Name') or m['Source']) in sources and m.get('RW') for m in c['Mounts'])]
    isolated[project]={'containers':len(rows),'all_stopped':all(not c['State']['Running'] for c in rows),'source_data_shared_for_writing':bool(shared)}
result={'at':manage.now(),'original_count':len(results),'originals':results,'copies':isolated}
result['passed']=all(c['preserved_and_running'] and c['health'] not in ('starting','unhealthy') for c in results) and all(v['containers']==len(manage.read(manage.ROOT/'compose.json')['services']) and not v['source_data_shared_for_writing'] and v['all_stopped'] for v in isolated.values())
manage.write(manage.ROOT/'reports/preservation.json',result)
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['passed'] else 1)
