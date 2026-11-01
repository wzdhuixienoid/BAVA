import json
from pathlib import Path
import sys
import os
from urllib.request import build_opener,ProxyHandler

ROOT=Path(os.environ.get('BAVA_RECORDING_EVIDENCE',str(Path(__file__).resolve().parent/'evidence')))
ROOT.mkdir(parents=True,exist_ok=True)
OP=build_opener(ProxyHandler({}))
def read(path):
    with OP.open('http://127.0.0.1:8001/api/v1'+path,timeout=20) as r:return json.load(r)
def save(name,obj):
    (ROOT/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
def main():
    label=sys.argv[1]
    workflows=read('/workflows')
    save(label+'-workflows',workflows)
    save(label+'-dashboard',read('/dashboard'))
    save(label+'-plans',read('/plans'))
    for workflow in workflows:
        wid=workflow['workflow_id']
        obj=read('/workflows/'+wid)
        save(label+'-'+wid,obj)
        save(label+'-'+wid+'-task',read('/tasks/'+obj['source_task_id']))
        save(label+'-'+wid+'-audit',read('/tasks/'+obj['source_task_id']+'/audit'))
        if obj.get('operation_summary'):
            save(label+'-'+wid+'-operation',read('/operations/'+obj['operation_summary']['operation_id']))
        print(json.dumps({'label':label,'workflow':wid,'status':obj['status'],'risk':obj['risk_level'],'task':obj['source_task_id']},ensure_ascii=False))
if __name__=='__main__':main()
