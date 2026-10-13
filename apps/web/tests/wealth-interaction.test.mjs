import assert from "node:assert/strict";
import test from "node:test";
import {createElement} from "react";
import {act, create} from "react-test-renderer";
import "./tsx-loader.mjs";
const {api} = await import("../lib/api/client.ts");
const {default:WealthPage} = await import("../app/wealth/page.tsx");
const {WealthWorkflowCard, WealthOrderExplanation} = await import("../features/wealth/WealthCards.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.self = globalThis;
const product = {product_id:"p",version_id:"p:v1",name:"演示稳健优选",risk:"R2",minimum_display:"1,000.00 元",open_display:"每个模拟交易日",fees_display:"申购0.10%",sources:[],tradable:true,purchase_allowed:true,terms:{}};
const position = {position_id:"pos",product_id:"p",account_id:"a",name:product.name,shares_display:"123.456789",frozen_display:"1.000000",available_display:"122.456789",available_quantity:"122.456789",value_display:"123.00 元",pending_display:"0.00 元"};
const workflow = {workflow_id:"w",source_task_id:"t",conversation_id:"c",workflow_type:"WEALTH_REDEEM",version:2,status:"READY_FOR_REVIEW",presentation:{stages:[],wealth_state:{draft:{direction:"REDEEM",product_id:"p",account_id:"a",quantity:"122.456789"},review:{name:product.name,quantity_display:"122.456789 份",notice:"估算，未来成交",sources:[]}}}};
const resources = {products:[product],accounts:[{account_id:"a",display_name:"工资卡",balance_display:"1000.00 元"}],positions:[position],newBusinessAllowed:true};
function text(node) {return typeof node === "string" ? node : (node?.children ?? []).map(text).join("");}
function button(r,name) {return r.root.findAllByType("button").find(n=>text(n)===name);}
function input(r) {return r.root.findAllByType("input").find(n=>n.props["aria-label"]==="交易数量");}
const deferred = () => {let resolve; const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
async function environment(fn) {
 const original={...api}, oldDocument=globalThis.document, oldSet=globalThis.setInterval, oldClear=globalThis.clearInterval;
 let poll, visibility; const doc={visibilityState:"visible",addEventListener:(name,cb)=>{visibility=cb;},removeEventListener:()=>{}};
 globalThis.document=doc; globalThis.setInterval=cb=>{poll=cb;return 1;};globalThis.clearInterval=()=>{};
 Object.assign(api,{
  wealthStatus:async()=>({new_business_allowed:true,reason:"已启用",catalog_version:"v1",questionnaire_version:"mock-v1"}),
  wealthProducts:async()=>[product], wealthPositions:async()=>[position], wealthOrders:async()=>[],
  wealthAssessment:async()=>({assessment_id:"a1",grade_display:"C5",expired:false,suitable:true,reasons:[],expires_at:"2027-01-01"}),
  wealthAccounts:async()=>resources.accounts, wealthWorkflows:async()=>[],
  wealthQuestionnaire:async()=>({version:"mock-v1",notice:"Mock",questions:Array.from({length:8},(_,i)=>({label:`题${i}`,options:["一","二"]}))}),
 });
 let r; try {await fn({mount:async props=>{await act(async()=>{r=create(createElement(WealthPage,props));});return r;},poll:()=>poll(),hide:()=>{doc.visibilityState="hidden";visibility();},show:()=>{doc.visibilityState="visible";visibility();}});}
 finally {if(r) await act(async()=>r.unmount());Object.assign(api,original);globalThis.document=oldDocument;globalThis.setInterval=oldSet;globalThis.clearInterval=oldClear;}
}

test("paused business keeps positions/orders and disables new transaction and questionnaire events",async()=>environment(async({mount})=>{
 api.wealthStatus=async()=>({new_business_allowed:false,reason:"已暂停新理财交易，已受理订单继续处理"});
 api.wealthOrders=async()=>[{order_id:"o",workflow_id:"w",name:"历史订单",direction_display:"赎回",status_display:"已成交，待到账",quantity_display:"10份",sources:[],user_reason:"赎回已成交，资金尚未到账",next_step:"等待原订单到账"}];
 const r=await mount();assert.ok(text(r.toJSON()).includes("历史订单"));assert.ok(text(r.toJSON()).includes("123.456789"));
 for(const name of ["提交测评","全部赎回","部分赎回并核对","购买演示稳健优选"])assert.equal(button(r,name).props.disabled,true,name);
}));

test("all redemption copies server Decimal string and duplicate clicks create one atomic draft",async()=>environment(async({mount})=>{
 const pending=deferred();let calls=[];
 api.wealthCreate=body=>{calls.push(body);return pending.promise;};
 const r=await mount();
 await act(async()=>{const handler=button(r,"全部赎回").props.onClick;handler();handler();});
 assert.equal(calls.length,1);assert.equal(calls[0].quantity,"122.456789");assert.equal(calls[0].redeem_all,true);assert.equal(calls[0].conversation_id,undefined);
 await act(async()=>pending.resolve(workflow));
 await act(async()=>button(r,"全部赎回").props.onClick());assert.equal(calls.length,1);
}));

test("product comparison sends selected names to the workbench and retries reuse the conversation",async()=>environment(async({mount})=>{
 const oldWindow=globalThis.window;let destination;globalThis.window={location:{assign:url=>{destination=url;}}};
 let created=0,calls=[];
 api.wealthProducts=async()=>[product,{...product,product_id:"p2",name:"演示稳享周周"}];
 api.createConversation=async()=>{created++;return {conversation_id:"compare/c"};};
 api.postMessage=async(...args)=>{calls.push(args);if(calls.length===1)throw Error("发送失败，请重试");return {task_id:"t-compare"};};
 api.wealthAnalyze=()=>assert.fail("comparison should run in the conversation");
 try{
  const r=await mount();
  for(const checkbox of r.root.findAllByType("input").filter(n=>n.props.type==="checkbox"))await act(async()=>checkbox.props.onChange({target:{checked:true}}));
  await act(async()=>button(r,"对比所选产品（最多4个）").props.onClick());
  assert.equal(destination,undefined);assert.ok(text(r.toJSON()).includes("发送失败"));
  await act(async()=>button(r,"对比所选产品（最多4个）").props.onClick());
  assert.equal(created,1);assert.equal(calls.length,2);assert.equal(calls[1][0],"compare/c");
  assert.equal(calls[0][1],calls[1][1]);
  for(const value of ["对比",product.name,"演示稳享周周","只读分析"])assert.ok(calls[1][1].includes(value));
  assert.equal(destination,"/?conversation=compare%2Fc");
 }finally{globalThis.window=oldWindow;}
}));

test("refresh failures retain old data, static resources load once, polling hides and never overlaps",async()=>environment(async({mount,poll,hide,show})=>{
 let calls=0, statics=0;let blocked;
 api.wealthPositions=()=>{calls++;return blocked ? blocked.promise : Promise.resolve([position]);};
 api.wealthProducts=async()=>{statics++;return [product];};
 const r=await mount();assert.equal(statics,1);
 blocked=deferred();await act(async()=>{poll();poll();});assert.equal(calls,2);
 await act(async()=>{hide();poll();});assert.equal(calls,2);
 await act(async()=>{blocked.resolve([position]);});blocked=null;
 api.wealthOrders=async()=>{throw Error("network");};await act(async()=>show());
 assert.ok(text(r.toJSON()).includes("刷新失败"));assert.ok(text(r.toJSON()).includes("123.456789"));assert.equal(statics,1);
}));

test("failed atomic draft does not create empty conversations and retries reuse same creation key",async()=>environment(async({mount})=>{
 let keys=[]; api.createConversation=async()=>{throw Error("should never run");};
 api.wealthCreate=async body=>{keys.push(body.creation_key);throw Error("创建失败");};
 const r=await mount();await act(async()=>button(r,"购买演示稳健优选").props.onClick());
 await act(async()=>r.root.findByProps({"aria-label":"购买演示稳健优选的账户"}).props.onChange({target:{value:"a"}}));
 await act(async()=>r.root.findByProps({"aria-label":"购买演示稳健优选的金额"}).props.onChange({target:{value:"1000"}}));
 await act(async()=>button(r,"下一步：核对申购").props.onClick());await act(async()=>button(r,"下一步：核对申购").props.onClick());
 assert.equal(keys.length,2);assert.equal(keys[0],keys[1]);assert.ok(text(r.toJSON()).includes("创建失败"));
}));

test("real transaction input keeps unsaved edits during polling, synchronizes backend changes after conflict",async()=>{
 let r;const originalEdit=api.wealthEdit;let sent;
 try{
  await act(async()=>{r=create(createElement(WealthWorkflowCard,{workflow,onRefresh:async()=>{},resources}));});
  await act(async()=>input(r).props.onChange({target:{value:"100.123456"}}));
  const newer={...workflow,version:3,presentation:{...workflow.presentation,wealth_state:{...workflow.presentation.wealth_state,draft:{...workflow.presentation.wealth_state.draft,quantity:"90.000000"}}}};
  await act(async()=>r.update(createElement(WealthWorkflowCard,{workflow:newer,onRefresh:async()=>{},resources})));
  assert.equal(input(r).props.value,"100.123456");
  api.wealthEdit=async(id,body)=>{sent=body;throw Error("请求失败（409）：版本冲突");};
  await act(async()=>button(r,"保存并核对").props.onClick());
  assert.equal(sent.expected_version,3);assert.equal(sent.quantity,"100.123456");assert.equal(input(r).props.value,"90.000000");assert.ok(text(r.toJSON()).includes("请重新核对"));
 }finally{api.wealthEdit=originalEdit;if(r)await act(async()=>r.unmount());}
});

test("authorization expiry is explained and financial commit never retries automatically",async()=>{
 let r,calls=0;const original=api.commitTransfer;
 try{api.commitTransfer=async()=>{calls++;throw Error("请求失败（422）：强验证已失效");};
  await act(async()=>{r=create(createElement(WealthWorkflowCard,{workflow:{...workflow,status:"READY_FOR_COMMIT",reauth_summary:{status:"VERIFIED"}},onRefresh:async()=>{},resources}));});
  await act(async()=>button(r,"提交赎回").props.onClick());assert.equal(calls,1);assert.ok(text(r.toJSON()).includes("请重新核对、确认和强验证"));
 }finally{api.commitTransfer=original;if(r)await act(async()=>r.unmount());}
});

test("failure and unknown share typed explanation, unknown offers no resubmit action",async()=>{
 let r;await act(async()=>{r=create(createElement(WealthOrderExplanation,{order:{unknown:true,status_display:"待成交",user_reason:"结果仍在确认，占用保留",next_step:"等待查询原订单，无需重新下单",last_known_stage:"已受理，待成交"}}));});
 assert.ok(text(r.toJSON()).includes("占用保留"));assert.equal(r.root.findAllByType("button").length,0);await act(async()=>r.unmount());
});

test("an individual static endpoint failure cannot hide dynamic orders or positions",async()=>environment(async({mount})=>{
 api.wealthProducts=async()=>{throw Error("offline");};
 api.wealthQuestionnaire=async()=>{throw Error("offline");};
 api.wealthOrders=async()=>[{order_id:"o",workflow_id:"w",name:"保留的失败订单",status_display:"明确失败",sources:[],error_code:"INSUFFICIENT_FUNDS",user_reason:"账户可用余额不足，无占用",next_step:"重新核对"}];
 const r=await mount(); assert.ok(text(r.toJSON()).includes("保留的失败订单"));assert.ok(text(r.toJSON()).includes("账户可用余额不足"));assert.ok(text(r.toJSON()).includes("123.456789"));assert.ok(text(r.toJSON()).includes("刷新失败"));
}));
