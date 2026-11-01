"""Verify recorded mock-bank results from saved API evidence."""
from decimal import Decimal as D
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def read(folder,name):return json.loads((ROOT/folder/(name+'.json')).read_text())
def salary(folder,stage):return D(next(a['balance'] for a in read(folder,stage+'-dashboard')['accounts'] if a['account_id']=='acc_salary'))
E='transfers-evidence'
ws=read(E,'final-workflows')
y=next(w for w in ws if D(w['state']['draft']['amount'])==100)
r=next(w for w in ws if D(w['state']['draft']['amount'])==1200)
def stage(name,wid):return next(w for w in read(E,name+'-workflows') if w['workflow_id']==wid)
ya=stage('yellow-approved',y['workflow_id'])
rc=stage('red-challenge',r['workflow_id'])
rv=stage('red-verified',r['workflow_id'])
plans=read(E,'final-plans')
p=next(p for p in plans if any(s.get('linked_workflow_id')==r['workflow_id'] for s in p['steps']))
paused=next(x for x in read(E,'plan-paused-plans') if x['plan_id']==p['plan_id'])
resumed=next(x for x in read(E,'plan-resumed-plans') if x['plan_id']==p['plan_id'])
a,b,c=p['steps'];decision=b['condition_decision']
sub=read('evidence','subscription-commit-check-workflows')[0]
suba=read('evidence','subscription-approved-workflows')[0]
report=read('evidence','reports')[0]
report=read('evidence','report-'+report['report_id'])
billconv=read('evidence','conversation-'+report['conversation_id'])
subconv=next(read('evidence','conversation-'+x['conversation_id']) for x in read('evidence','conversations') if x['title']=='我有哪些订阅？')
msgs=[]
for conv in read(E,'conversations'):
 msgs += [m['content'] for m in read(E,'conversation-'+conv['conversation_id'])['messages'] if m['role']=='USER']
ledger=read(E,'ledger')['transactions']
checks={
 'fresh_transfer_fixture':read(E,'before-workflows')==[] and salary(E,'before')==D('23864.52'),
 'only_two_transfer_workflows':len(ws)==2 and all(w['workflow_type']=='TRANSFER' for w in ws),
 'bill_question_exact':[m['content'] for m in billconv['messages'] if m['role']=='USER']==['分析2026年8月消费，生成报告'],
 'report_facts':report['period']=='2026-08' and D(report['content']['overview']['total_spending'])==D('16547.30') and report['content']['overview']['transaction_count']==45 and D(report['content']['period_comparison']['previous_spending'])==D('9333.20'),
 'bill_read_has_no_financial_write':read('evidence','baseline-workflows')==[] and len(read('evidence','subscription-approved-workflows'))==1 and sub['workflow_type']=='SUBSCRIPTION_CANCEL',
 'subscription_questions_exact':[m['content'] for m in subconv['messages'] if m['role']=='USER']==['我有哪些订阅？','我有哪些订阅？','取消星幕视频'],
 'subscription_confirmation_not_execution':suba['status']=='READY_FOR_COMMIT' and suba['operation_summary'] is None,
 'subscription_final_result':sub['status']=='SUCCEEDED' and sub['operation_summary']['status']=='SUCCEEDED' and sub['approval_summary']['status']=='CONSUMED' and sub['risk_level']=='YELLOW',
 'planned_transfer_prompts_exact':msgs.count('从工资卡给李小雨转100元，备注餐费')==1 and msgs.count('查工资卡余额，如果余额不少于3000元，给张三转1200元')==2,
 'yellow_payee_and_remark':y['state']['review_payload']['payee_display_name']=='李小雨' and y['state']['draft']['remark']=='餐费',
 'red_disambiguated_payee':r['state']['review_payload']['payee_display_name']=='张三' and r['state']['review_payload']['payee_masked_account']=='****2231',
 'yellow_policy':y['risk_level']=='YELLOW' and not y['risk_decision']['required_reauthentication'],
 'red_policy':r['risk_level']=='RED' and r['risk_decision']['required_reauthentication'],
 'yellow_confirmation_no_debit':ya['status']=='READY_FOR_COMMIT' and ya['operation_summary'] is None and salary(E,'yellow-approved')==D('23864.52'),
 'red_confirmation_no_debit':rc['status']=='REAUTH_REQUIRED' and rc['operation_summary'] is None and salary(E,'red-challenge')==D('23764.52'),
 'mock_challenge_pending':rc['reauth_summary']['method']=='MOCK_CODE' and rc['reauth_summary']['status']=='PENDING',
 'verification_no_debit':rv['status']=='READY_FOR_COMMIT' and rv['operation_summary'] is None and rv['reauth_summary']['status']=='VERIFIED' and salary(E,'red-verified')==D('23764.52'),
 'same_bound_challenge':rc['reauth_summary']['reauth_id']==rv['reauth_summary']['reauth_id']==r['reauth_summary']['reauth_id'],
 'same_bound_approval':rc['approval_summary']['approval_id']==rv['approval_summary']['approval_id']==r['approval_summary']['approval_id'],
 'three_dependent_steps':len(p['steps'])==3 and a['capability']=='ACCOUNT_QUERY' and b['step_kind']=='CONDITION' and c['capability']=='TRANSFER_WORKFLOW' and b['depends_on']==[a['step_id']] and c['depends_on']==[b['step_id']],
 'condition_uses_real_balance':D(decision['actual_value'])==D('23764.52') and D(decision['threshold_value'])==3000 and decision['outcome']=='TRUE',
 'guard_binds_condition':c['guard_condition_step_id']==b['step_id'] and c['linked_workflow_id']==r['workflow_id'],
 'pause_resume_same_plan':paused['status']=='PAUSED' and paused['manual_takeover'] and not resumed['manual_takeover'] and resumed['plan_id']==paused['plan_id']==p['plan_id'],
 'completed_plan':p['status']=='COMPLETED' and all(s['status']=='COMPLETED' for s in p['steps']),
 'both_business_results_succeeded':all(w['status']=='SUCCEEDED' and w['operation_summary']['status']=='SUCCEEDED' and w['presentation']['business_success'] for w in ws),
 'approvals_consumed':all(w['approval_summary']['status']=='CONSUMED' for w in ws),
 'exact_final_balance':salary(E,'final')==salary(E,'before')-D('1300')==D('22564.52'),
 'security_normal':read(E,'security-status')['status']=='NORMAL',
}
for w in ws:
 au=read(E,'final-'+w['workflow_id']+'-audit')['write_evidence']
 checks['once_only_'+w['state']['draft']['amount']]=all(au[k]==1 for k in ['workflow_count','approval_count','operation_count','provider_ledger_count','provider_submission_count']) and au['business_success']
failed=[x for x in plans if x['status']=='FAILED']
checks['discarded_planning_attempt_failed_closed']=len(failed)==1 and all(not s.get('linked_workflow_id') for x in failed for s in x['steps']) and any(s.get('error_code')=='CONDITION_INPUT_UNAVAILABLE' for x in failed for s in x['steps'])
result=dict(all_passed=all(checks.values()),checks=checks,completed_plan_id=p['plan_id'],recorded_workflow_ids=[y['workflow_id'],r['workflow_id']],before_balance='23864.52',after_balance='22564.52',notes=['Read-only/report/subscription and final transfer takes use separate isolated mock fixtures.','One discarded conditional planning take failed closed before creating a transfer; the unchanged original prompt was successfully re-recorded in a new conversation.','Mock verification is a demo gate, not production SMS/face/multifactor authentication.'])
(ROOT/'business-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
assert result['all_passed']
