from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
E=ROOT/'evidence'
def read(name):return json.loads((E/(name+'.json')).read_text())
def salary(stage):return Decimal(next(a['balance'] for a in read(stage+'-dashboard')['accounts'] if a['account_id']=='acc_salary'))
final=read('final-workflows');yellow=next(w for w in final if w['state']['draft']['amount']=='100');red=next(w for w in final if w['state']['draft']['amount']=='1200')
yid=yellow['workflow_id'];rid=red['workflow_id']
approved=next(w for w in read('yellow-approved-workflows') if w['workflow_id']==yid)
challenge=next(w for w in read('red-challenge-workflows') if w['workflow_id']==rid)
verified=next(w for w in read('red-verified-workflows') if w['workflow_id']==rid)
plan=read('final-plans')[0];paused=read('plan-paused-plans')[0]
a,b,c=plan['steps'];decision=b['condition_decision']
checks={
 'zero_initial_transfers':read('before-workflows')==[],
 'initial_salary_correct':salary('before')==Decimal('23864.52'),
 'exactly_two_transfer_workflows':len(final)==2 and all(w['workflow_type']=='TRANSFER' for w in final),
 'yellow_payee_and_remark_match_plan':yellow['state']['review_payload']['payee_display_name']=='李小雨' and yellow['state']['draft']['remark']=='餐费',
 'red_payee_matches_plan':red['state']['review_payload']['payee_display_name']=='张三' and red['state']['review_payload']['payee_masked_account']=='****2231',
 'yellow_policy':yellow['risk_level']=='YELLOW' and not yellow['risk_decision']['required_reauthentication'],
 'red_policy':red['risk_level']=='RED' and red['risk_decision']['required_reauthentication'],
 'yellow_approval_does_not_submit':approved['status']=='READY_FOR_COMMIT' and approved['approval_summary']['status']=='APPROVED' and approved['operation_summary'] is None and salary('yellow-approved')==salary('before'),
 'red_confirmation_does_not_submit':challenge['status']=='REAUTH_REQUIRED' and challenge['operation_summary'] is None and salary('red-challenge')==Decimal('23764.52'),
 'mock_code_pending':challenge['reauth_summary']['method']=='MOCK_CODE' and challenge['reauth_summary']['status']=='PENDING',
 'verification_does_not_submit':verified['status']=='READY_FOR_COMMIT' and verified['operation_summary'] is None and verified['reauth_summary']['status']=='VERIFIED' and salary('red-verified')==Decimal('23764.52'),
 'same_bound_challenge':challenge['reauth_summary']['reauth_id']==verified['reauth_summary']['reauth_id']==red['reauth_summary']['reauth_id'],
 'same_approval':challenge['approval_summary']['approval_id']==verified['approval_summary']['approval_id']==red['approval_summary']['approval_id'],
 'one_plan':len(read('final-plans'))==1,
 'three_dependent_steps':len(plan['steps'])==3 and a['capability']=='ACCOUNT_QUERY' and b['step_kind']=='CONDITION' and c['capability']=='TRANSFER_WORKFLOW' and b['depends_on']==[a['step_id']] and c['depends_on']==[b['step_id']],
 'real_balance_and_threshold':Decimal(decision['actual_value'])==Decimal('23764.52') and Decimal(decision['threshold_value'])==Decimal('3000') and decision['outcome']=='TRUE',
 'guard_binds_condition':c['guard_condition_step_id']==b['step_id'] and c['linked_workflow_id']==rid,
 'manual_takeover_paused_same_plan':paused['status']=='PAUSED' and paused['manual_takeover'] and paused['plan_id']==plan['plan_id'],
 'same_plan_completed':plan['status']=='COMPLETED' and not plan['manual_takeover'] and all(s['status']=='COMPLETED' for s in plan['steps']),
 'final_business_success':all(w['status']=='SUCCEEDED' and w['operation_summary']['status']=='SUCCEEDED' and w['presentation']['business_success'] for w in final),
 'approvals_consumed_once':all(w['approval_summary']['status']=='CONSUMED' for w in final),
 'final_salary_exact_debits':salary('final')==salary('before')-Decimal('1300')==Decimal('22564.52'),
}
for w in final:
 audit=read('final-'+w['workflow_id']+'-audit')['write_evidence']
 checks['unique_execution_'+w['state']['draft']['amount']]=all(audit[k]==1 for k in ['workflow_count','approval_count','operation_count','provider_ledger_count','provider_submission_count']) and audit['business_success']
events=json.loads((ROOT/'events.json').read_text())
checks['original_questions_exact']=[m['content'] for m in read('conversation')['messages'] if m['role']=='USER']==['从工资卡给李小雨转100元，备注餐费','查工资卡余额，如果余额不少于3000元，给张三转1200元']
video_root=ROOT.parents[2]
prior=json.loads((ROOT.parents[1]/'evidence/previous-videos-sha256.json').read_text())
checks['previous_three_sections_unchanged']=all(hashlib.sha256((video_root/p).read_bytes()).hexdigest()==sha for p,sha in prior.items())
result={'checks':checks,'all_passed':all(checks.values()),'workflow_ids':[yid,rid],'plan_id':plan['plan_id'],'before_balance':str(salary('before')),'after_balance':str(salary('final'))}
(ROOT/'business-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
assert result['all_passed']
