"""Export isolated submit results for byte-for-byte old/new comparison."""
import argparse, json
from pathlib import Path
from workhub.test_report_submit_integration import SubmitIntegrationTests

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
args=parser.parse_args()
case=SubmitIntegrationTests('test_multi_project_update_and_new_task_submit_then_duplicate')
try:
    case.setUp()
    case.test_multi_project_update_and_new_task_submit_then_duplicate()
    result={'posted_text':[m['msg'] for m in case.messages.values()],
            'documents':sorted([{'title':d['title'],'project':d['collectionId'],'text':d['text'],
                'writes':case.writes[d['id']]} for d in case.docs.values() if d.get('parentDocumentId')],key=lambda d:(d['project'],d['title']))}
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('PASS: isolated multi-project updates, new task, posting and retry; output exported')
finally:
    case.doCleanups()
