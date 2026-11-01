"""Verify one conversation and one mock fixture across the whole demonstration."""
from decimal import Decimal as D
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
E=ROOT/'evidence'
def read(n):return json.loads((E/(n+'.json')).read_text())
def balance(stage):return D(next(a['balance'] for a in read(stage+'-dashboard')['accounts'] if a['account_id']=='acc_salary'))
stages=['baseline','bill-complete','subscription-read','subscription-review','subscription-approved','subscription-posted','before-transfer','yellow-review','yellow-approved','yellow-posted','plan-ready','plan-paused','plan-resumed','red-review','red-challenge','red-verified','final']
cid=read('baseline-conversations')[0]['conversation_id']
convs=[read(s+'-conversation-'+cid) for s in stages]
msgs=convs[-1]['messages']
users=[m['content'] for m in msgs if m['role']=='USER']
ids=lambda c:[m['message_id'] for m in c['messages']]
ws=read('final-workflows')
sub=next(w for w in ws if w['workflow_type']=='SUBSCRIPTION_CANCEL')
y=next(w for w in ws if w['workflow_type']=='TRANSFER' and D(w['state']['draft']['amount'])==100)
r=next(w for w in ws if w['workflow_type']=='TRANSFER' and D(w['state']['draft']['amount'])==1200)
def stage_w(s,w):return next(v for v in read(s+'-workflows') if v['workflow_id']==w['workflow_id'])
sa=stage_w('subscription-approved',sub)
ya=stage_w('yellow-approved',y)
rc=stage_w('red-challenge',r)
rv=stage_w('red-verified',r)
plan=read('final-plans')[0]
paused=read('plan-paused-plans')[0]
resumed=read('plan-resumed-plans')[0]
a,b,c=plan['steps'];decision=b['condition_decision']
report=read('bill-complete-reports')[0]
report_detail=read('bill-complete-report-'+report['report_id'])
proj=lambda s:read(s+'-dashboard')['subscriptions']
cost=lambda s:D(next(x['amount'] for x in proj(s)['monthly_cost_by_currency'] if x['currency']=='CNY'))
checks={
 'one_conversation_at_every_stage':all(len(read(s+'-conversations'))==1 and read(s+'-conversations')[0]['conversation_id']==cid for s in stages),
 'one_visible_title':all(read(s+'-conversations')[0]['title']=='BAVA 银行服务演示' for s in stages),
 'all_prior_message_ids_preserved':all(ids(convs[i])==ids(convs[i+1])[:len(ids(convs[i]))] for i in range(len(convs)-1)),
 'exact_prompts_in_progressive_order':users==['分析2026年8月消费，生成报告','我有哪些订阅？','我有哪些订阅？','取消星幕视频','从工资卡给李小雨转100元，备注餐费','查工资卡余额，如果余额不少于3000元，给张三转1200元'],
 'all_workflows_in_same_conversation':all(w['conversation_id']==cid for w in ws),
 'same_report_retained':all(len(read(s+'-reports'))==1 and read(s+'-reports')[0]['report_id']==report['report_id'] for s in stages[1:]),
 'report_facts':report_detail['period']=='2026-08' and D(report_detail['content']['overview']['total_spending'])==D('16547.30') and report_detail['content']['overview']['transaction_count']==45,
 'no_initial_financial_writes':read('baseline-workflows')==[] and read('bill-complete-workflows')==[] and read('subscription-read-workflows')==[],
 'read_and_subscription_do_not_debit':all(balance(s)==D('23864.52') for s in stages[:9]),
 'exact_three_workflows':len(ws)==3 and sum(w['workflow_type']=='TRANSFER' for w in ws)==2,
 'subscription_confirm_before_commit':sa['status']=='READY_FOR_COMMIT' and sa['operation_summary'] is None,
 'subscription_succeeded':sub['status']=='SUCCEEDED' and sub['risk_level']=='YELLOW' and sub['operation_summary']['status']=='SUCCEEDED',
 'subscription_monthly_cost_changes':cost('baseline')==258 and cost('subscription-posted')==230,
 'yellow_payee_and_remark':y['state']['review_payload']['payee_display_name']=='李小雨' and y['state']['draft']['remark']=='餐费',
 'yellow_risk':y['risk_level']=='YELLOW' and not y['risk_decision']['required_reauthentication'],
 'yellow_confirmation_no_debit':ya['status']=='READY_FOR_COMMIT' and ya['operation_summary'] is None and balance('yellow-approved')==D('23864.52'),
 'yellow_posted_balance':balance('yellow-posted')==D('23764.52'),
 'red_payee_disambiguated':r['state']['review_payload']['payee_display_name']=='张三' and r['state']['review_payload']['payee_masked_account']=='****2231',
 'red_requires_verification':r['risk_level']=='RED' and r['risk_decision']['required_reauthentication'],
 'red_confirmation_no_debit':rc['status']=='REAUTH_REQUIRED' and rc['operation_summary'] is None and balance('red-challenge')==D('23764.52'),
 'mock_challenge_pending':rc['reauth_summary']['method']=='MOCK_CODE' and rc['reauth_summary']['status']=='PENDING',
 'verification_does_not_submit':rv['status']=='READY_FOR_COMMIT' and rv['operation_summary'] is None and rv['reauth_summary']['status']=='VERIFIED' and balance('red-verified')==D('23764.52'),
 'same_bound_verification':rc['reauth_summary']['reauth_id']==rv['reauth_summary']['reauth_id']==r['reauth_summary']['reauth_id'],
 'one_three_step_plan':len(read('final-plans'))==1 and len(plan['steps'])==3 and a['capability']=='ACCOUNT_QUERY' and b['step_kind']=='CONDITION' and c['capability']=='TRANSFER_WORKFLOW',
 'dag_dependencies':b['depends_on']==[a['step_id']] and b['step_id'] in c['depends_on'] and set(c['depends_on']).issubset({a['step_id'],b['step_id']}) and c['guard_condition_step_id']==b['step_id'],
 'condition_uses_real_facts':D(decision['actual_value'])==D('23764.52') and D(decision['threshold_value'])==3000 and decision['outcome']=='TRUE',
 'pause_resume_same_plan':paused['plan_id']==resumed['plan_id']==plan['plan_id'] and paused['manual_takeover'] and paused['status']=='PAUSED' and not resumed['manual_takeover'],
 'plan_completed':plan['status']=='COMPLETED' and all(s['status']=='COMPLETED' for s in plan['steps']),
 'all_business_succeeded':all(w['status']=='SUCCEEDED' and w['operation_summary']['status']=='SUCCEEDED' and w['presentation']['business_success'] for w in ws),
 'all_approvals_consumed':all(w['approval_summary']['status']=='CONSUMED' for w in ws),
 'exact_final_balance':balance('final')==balance('baseline')-D('1300')==D('22564.52'),
 'no_security_lock':read('final-security')['status']=='NORMAL',
}
for w in [y,r]:
 au=read('final-'+w['workflow_id']+'-audit')['write_evidence']
 checks['exactly_once_'+w['state']['draft']['amount']]=all(au[k]==1 for k in ['workflow_count','approval_count','operation_count','provider_ledger_count','provider_submission_count']) and au['business_success']
result=dict(all_passed=all(checks.values()),checks=checks,conversation_id=cid,title='BAVA 银行服务演示',user_messages=users,workflow_ids=[w['workflow_id'] for w in ws],report_id=report['report_id'],final_balance='22564.52')
(ROOT/'business-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
assert result['all_passed']
