import json
from pathlib import Path
import sys
from urllib.request import build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parent/'evidence'
ROOT.mkdir(exist_ok=True)
op=build_opener(ProxyHandler({}))
def read(path):
 with op.open('http://127.0.0.1:8001/api/v1'+path,timeout=20) as r:return json.load(r)
def save(name,obj):(ROOT/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
def main():
 stage=sys.argv[1]
 for name,path in [('dashboard','/dashboard'),('plans','/plans'),('ledger','/dashboard/transactions'),('conversations','/conversations'),('reports','/reports'),('security','/security/status')]:save(stage+'-'+name,read(path))
 cs=read('/conversations')
 for c in cs:save(stage+'-conversation-'+c['conversation_id'],read('/conversations/'+c['conversation_id']))
 for r in read('/reports'):save(stage+'-report-'+r['report_id'],read('/reports/'+r['report_id']))
 ws=read('/workflows');save(stage+'-workflows',ws)
 for w in ws:
  wid=w['workflow_id'];save(stage+'-'+wid,w)
  save(stage+'-'+wid+'-audit',read('/tasks/'+w['source_task_id']+'/audit'))
  if w.get('operation_summary'):save(stage+'-'+wid+'-operation',read('/operations/'+w['operation_summary']['operation_id']))
 print(json.dumps({'stage':stage,'conversations':len(cs),'workflows':[(w['workflow_type'],w['status']) for w in ws]},ensure_ascii=False))
if __name__=='__main__':main()
