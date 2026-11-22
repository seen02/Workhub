"""Local authenticated RAG administration; credentials stay in the container."""
import argparse,json,os
import httpx

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['status','sync','reindex','result','cancel'])
    parser.add_argument('--event-id');parser.add_argument('--user-id');parser.add_argument('--chat-id')
    args=parser.parse_args()
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=1800,headers={'Authorization':'Bearer '+os.environ['AGENT_TOKEN']}) as client:
        if args.action=='status':response=client.get('/rag/status')
        elif args.action in ('sync','reindex'):response=client.post('/rag/'+args.action)
        else:
            if not all((args.event_id,args.user_id,args.chat_id)):parser.error('result/cancel require event-id, user-id and chat-id')
            response=client.post('/agent/'+args.action,json={'tool':args.action,'arguments':{'event_id':args.event_id},'user_id':args.user_id,'chat_id':args.chat_id})
        response.raise_for_status();print(json.dumps(response.json(),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
