import assert from 'node:assert/strict';
import test from 'node:test';
import {validateDraft,serverFieldError} from '../features/aa/validation.ts';
const valid={total:'300',people:'王五',self:'true',account:'savings',remark:'出去玩',deadline:'2026-10-15 12:44:47',manual:''};
const validate=fields=>validateDraft(fields,['savings'],Date.parse('2026-10-08T00:00:00Z'));
test('self in people is actionable while self participation is valid',()=>{
 assert.deepEqual(Object.keys(validate({...valid,people:'我、王五'})),['people']);
 assert.match(validate({...valid,people:'我、王五'}).people,/移除“我”/);
 assert.deepEqual(validate(valid),{});
});
test('all missing fields and invalid input report their own errors',()=>{
 const errors=validate({...valid,total:'0',people:'',self:'',account:'',deadline:'2026-02-30 09:00:00',remark:'x'.repeat(101),manual:'王五=-1'});
 assert.deepEqual(Object.keys(errors).sort(),['account','deadline','manual','people','remark','self','total']);
 assert.ok(validate({...valid,deadline:'2026-10-01 09:00:00'}).deadline);
 assert.ok(validate({...valid,people:'王五、王五'}).people);
 assert.ok(validate({...valid,people:'陌生人'}).people);
});
test('manual amounts use exact cents, reject overwritten names and mismatches',()=>{
 assert.deepEqual(validate({...valid,total:'100',manual:'王五=33.33、我=66.67'}),{});
 for(const manual of ['王五=30、王五=30、我=40','王五=33.333、我=66.667','王五=30','王五=30、我=60'])assert.ok(validate({...valid,total:'100',manual}).manual);
 assert.ok(validate({...valid,total:'0.01'}).total);
 assert.ok(serverFieldError('AA_PARTICIPANT_NOT_REGISTERED_OR_SELF').people);
});
