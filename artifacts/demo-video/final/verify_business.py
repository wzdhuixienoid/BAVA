"""Read-only evidence verification for the continuous final demonstration."""
from decimal import Decimal as D
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
E=ROOT/'evidence';OLD=ROOT.parent/'continuous-retake'
def read(stage,name):return json.loads((E/f'{stage}-{name}.json').read_text())
old=json.loads((OLD/'business-verification.json').read_text())
cid=old['conversation_id']
stages=['before-wealth','wealth-assessed','wealth-review','wealth-challenge','wealth-verified','wealth-posted','final']
convs=[read(s,'conversation-'+cid) for s in stages]
ids=lambda c:[m['message_id'] for m in c['messages']]
base=json.loads((OLD/'evidence'/f'final-conversation-{cid}.json').read_text())
ws=read('final','workflows');w=next(w for w in ws if w['workflow_type']=='WEALTH_PURCHASE')
def wf(s):return next(x for x in read(s,'workflows') if x['workflow_id']==w['workflow_id'])
def balance(s):return D(next(a['balance'] for a in read(s,'dashboard')['accounts'] if a['account_id']=='acc_salary'))
review,challenge,verified=map(wf,['wealth-review','wealth-challenge','wealth-verified'])
orders=read('final','wealth-orders');order=orders[0];assessment=read('final','wealth-assessment')
ledger=read('final','ledger')['transactions'];previous=read('before-wealth','ledger')['transactions']
checks={**{'earlier_'+k:v for k,v in old['checks'].items()},
 'single_conversation_through_wealth':all(len(read(s,'conversations'))==1 and read(s,'conversations')[0]['conversation_id']==cid for s in stages),
 'same_title_through_wealth':all(c['title']=='BAVA 银行服务演示' for c in convs),
 'all_preexisting_messages_retained':all(ids(base)==ids(c)[:len(ids(base))] for c in convs),
 'all_new_message_ids_retained':all(ids(a)==ids(b)[:len(ids(a))] for a,b in zip(convs,convs[1:])),
 'same_report_retained_after_wealth':all(read(s,'reports')[0]['report_id']==old['report_id'] and len(read(s,'reports'))==1 for s in stages),
 'only_one_wealth_workflow':len(ws)==4 and sum(x['workflow_type']=='WEALTH_PURCHASE' for x in ws)==1,
 'all_workflows_same_conversation':all(x['conversation_id']==cid for x in ws),
 'prior_three_operations_preserved':all(any(x['workflow_id']==wid and x['status']=='SUCCEEDED' for x in ws) for wid in old['workflow_ids']),
 'assessment_valid_and_bound':assessment['grade_display']=='C2（Mock 测评）' and assessment['suitable'] and not assessment['expired'] and assessment['assessment_id']==w['state']['review']['assessment_id'],
 'r1_product_within_c2_limit':w['state']['review']['risk']=='R1' and w['state']['review']['customer_grade']=='C2',
 'exact_purchase_details':w['state']['draft']['product_id']=='mock-wealth-01' and w['state']['draft']['account_id']=='acc_salary' and D(w['state']['draft']['quantity'])==1000,
 'red_requires_confirmation_and_reauth':w['risk_level']=='RED' and w['wealth_risk_decision']['requires_confirmation'] and w['wealth_risk_decision']['requires_reauthentication'],
 'review_before_authorization':review['status']=='READY_FOR_REVIEW' and review['approval_summary'] is None and review['operation_summary'] is None,
 'confirmation_does_not_submit':challenge['status']=='REAUTH_REQUIRED' and challenge['approval_summary']['status']=='APPROVED' and challenge['operation_summary'] is None,
 'challenge_pending':challenge['reauth_summary']['status']=='PENDING' and challenge['reauth_summary']['method']=='MOCK_CODE',
 'verification_does_not_submit':verified['status']=='READY_FOR_COMMIT' and verified['reauth_summary']['status']=='VERIFIED' and verified['operation_summary'] is None,
 'one_bound_challenge':challenge['reauth_summary']['reauth_id']==verified['reauth_summary']['reauth_id']==w['reauth_summary']['reauth_id'],
 'funds_unchanged_before_submit':all(balance(s)==D('22564.52') for s in stages[:5]),
 'no_orders_before_submit':all(read(s,'wealth-orders')==[] for s in ['wealth-review','wealth-challenge','wealth-verified']),
 'one_order_same_conversation_and_workflow':len(orders)==1 and order['conversation_id']==cid and order['workflow_id']==w['workflow_id'] and order['operation_id']==w['operation_summary']['operation_id'],
 'honest_asynchronous_status':w['status']=='COMMITTING' and w['operation_summary']['status']=='SUBMITTED' and w['presentation']['wealth_state']['order_stage']=='ACCEPTED' and order['status_display']=='已受理，待成交',
 'not_claimed_as_final_success':not w['presentation']['business_success'] and order['actual'] is None and read('final','wealth-positions')==[],
 'hold_preserved_until_confirmation':order['hold_retained'] and balance('final')==D('21564.52')==balance('wealth-verified')-1000,
 'settlement_time_matches_review':order['confirm_at']=='2026-11-03T02:00:00Z' and order['next_processing_at']==order['confirm_at'],
 'approval_consumed_on_submission':w['approval_summary']['status']=='CONSUMED',
 'no_premature_wealth_posted_ledger':ledger==previous and not any(x['source']=='WEALTH' for x in ledger),
 'no_security_lock':read('final','security')['status']=='NORMAL',
}
users=[m['content'] for m in convs[-1]['messages'] if m['role']=='USER']
checks['progressive_prompts_and_retained_retry']=users[:6]==old['user_messages'] and users[6:]==['对比演示稳享日日和演示稳健优选，看看风险、费用和到账时间。','从工资卡申购1000元演示稳享日日。','从工资卡申购1000元演示稳享日日。']
audit=read('final',w['workflow_id']+'-audit')['write_evidence']
checks['single_authority_and_operation']=all(audit[k]==1 for k in ['workflow_count','approval_count','operation_count']) and not audit['business_success']
result=dict(all_passed=all(checks.values()),checks=checks,conversation_id=cid,user_messages=users,wealth_workflow_id=w['workflow_id'],order_id=order['order_id'],available_balance='21564.52',order_status='ACCEPTED, pending execution at published time',earlier_verification='../continuous-retake/business-verification.json',notes=['Failed purchase rehearsal retained in original history; no financial write was created by the failed request. Fixed obsolete PostgreSQL workflow enum names before retry.','No clock acceleration or synthetic completed wealth result.'])
(ROOT/'business-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({'all_passed':result['all_passed'],'passed':sum(checks.values()),'total':len(checks),'failed':[k for k,v in checks.items() if not v]},ensure_ascii=False))
assert result['all_passed']
