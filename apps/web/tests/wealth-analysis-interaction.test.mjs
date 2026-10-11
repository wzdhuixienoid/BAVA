import assert from "node:assert/strict";
import test from "node:test";
import {createElement} from "react";
import {act,create} from "react-test-renderer";
import "./tsx-loader.mjs";
const {api}=await import("../lib/api/client.ts");
const {WealthAnalysisCard,WealthEvidencePanel,WealthReanalyze,safeEvidenceSource}=await import("../features/wealth/WealthAnalysisCard.tsx");
const {AssistantTurn}=await import("../features/conversation/AssistantTurn.tsx");
const {default:WealthPage}=await import("../app/wealth/page.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
globalThis.self=globalThis;
const evidence={evidence_id:"edu-nav",title:"净值型理财",scope:"EDUCATION",url:"https://www.boc.cn/pbservice/pb3/202409/t20240912_25152706.html",source_name:"中国银行官方投教",source_type:"BANK_EDUCATION",version:"v1",verified_at:"2026-10-10",content:"净值会波动，不保证本金。"};
const analysis={schema_version:"wealth-analysis-v1",snapshot_id:"s",source_task_id:"t",reference_time:"2026-10-09T09:00:00+08:00",status:"CONDITIONAL",result_kind:"RECOMMENDATION",conclusion:"按已知条件先比较，现金到账需要等待。",needs:{amount:null,liquidity_raw:null,clarification_questions:["投资多少元？","最早何时用钱？"],assumptions:[],changed_fields:[]},blocks:[{block_id:"conclusion",text:"不重复这段"}],candidates:[],evidence:[evidence],new_business_allowed:true};
const text=n=>typeof n==="string"?n:(n?.children??[]).map(text).join("");
const button=(r,name)=>r.root.findAllByType("button").find(n=>text(n)===name);
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve};};
async function render(Component,props,fn){let r;await act(async()=>{r=create(createElement(Component,props));});try{await fn(r);}finally{await act(async()=>r.unmount());}}

test("conversation displays typed analysis first, without raw reply or intermediate catalogue",async()=>{
 const turn={user:{content:"推荐理财"},tasks:[{task_id:"t",conversation_id:"c",status:"COMPLETED",output:{wealth_analysis:analysis,wealth_results:[{result_kind:"CATALOGUE",products:[{name:"中间目录"}]}]}}],plans:[],workflows:[],reports:[],replies:[{message_id:"m",role:"ASSISTANT",content:"工具返回 /api/v1/ mock-wealth-01"},{message_id:"notice",role:"SYSTEM_NOTICE",content:"保留系统通知"}]};
 await render(AssistantTurn,{turn,activityRevision:0,highlightedResult:null,onRefresh:async()=>{}},async r=>{
  const content=text(r.toJSON());assert.ok(content.includes(analysis.conclusion));assert.ok(content.includes("投资多少元"));assert.ok(content.includes("保留系统通知"));
  for(const bad of ["中间目录","工具返回","mock-wealth-01","/api/v1/","不重复这段"])assert.ok(!content.includes(bad),bad);
 });
});

test("education evidence previews and closes, with safe official original link",async()=>{
 await render(WealthEvidencePanel,{evidence:[evidence]},async r=>{
  await act(async()=>r.root.findByType("button").props.onClick());
  assert.ok(text(r.toJSON()).includes(evidence.content));
  assert.equal(r.root.findByProps({role:"dialog"}).props["aria-label"],"分析依据");
  const link=r.root.findByType("a");assert.equal(link.props.href,evidence.url);assert.equal(link.props.rel,"noopener noreferrer");
  await act(async()=>button(r,"关闭依据").props.onClick());assert.equal(r.root.findAllByProps({role:"dialog"}).length,0);
 });
 for(const url of ["javascript:alert(1)","data:text/html,x","https://evil.example","https://www.boc.cn@evil.example"]){assert.equal(safeEvidenceSource({...evidence,url}),false);}
});

test("product evidence fetches bound document and reports loading failure without losing answer",async()=>{
 const original=api.wealthDocument;let called;
 api.wealthDocument=async id=>{called=id;throw Error("network");};
 try{await render(WealthAnalysisCard,{analysis:{...analysis,evidence:[{...evidence,scope:"PRODUCT",url:"/api/v1/wealth/documents/p:v1:1",document_id:"p:v1:1"}]}},async r=>{
  await act(async()=>r.root.findAllByType("button")[0].props.onClick());
  assert.equal(called,"p:v1:1");assert.ok(text(r.toJSON()).includes("资料暂时无法打开"));assert.ok(text(r.toJSON()).includes(analysis.conclusion));
  api.wealthDocument=async()=>({content:"原版本说明书"});await act(async()=>r.root.findAllByType("button")[0].props.onClick());
  assert.ok(text(r.toJSON()).includes("原版本说明书"));
 });}finally{api.wealthDocument=original;}
});

test("historical reanalysis only submits on user click, suppresses rapid duplicates and never edits history",async()=>{
 const original=api.postMessage;const pending=deferred();let calls=[];let refresh=0;
 api.postMessage=(...args)=>{calls.push(args);return pending.promise;};
 try{await render(WealthReanalyze,{conversationId:"c",request:"推荐稳健理财",onRefresh:async()=>{refresh++;}},async r=>{
  assert.equal(calls.length,0);
  await act(async()=>{button(r,"按当前条件重新分析").props.onClick();button(r,"按当前条件重新分析").props.onClick();});
  assert.equal(calls.length,1);assert.equal(calls[0][0],"c");assert.match(calls[0][1],/只读/);
  await act(async()=>pending.resolve({task_id:"new-task"}));assert.equal(refresh,1);assert.equal(button(r,"已发起新的只读分析").props.disabled,true);
 });}finally{api.postMessage=original;}
});

test("page updates shared analysis from budget events, without polling model generation or overlap",async()=>{
 const original={...api};const oldDocument=globalThis.document,oldSet=globalThis.setInterval,oldClear=globalThis.clearInterval;
 globalThis.document={visibilityState:"visible",addEventListener:()=>{},removeEventListener:()=>{}};
 let poll;globalThis.setInterval=fn=>{poll=fn;return 1;};globalThis.clearInterval=()=>{};
 let calls=[];const pending=deferred();
 Object.assign(api,{wealthStatus:async()=>({new_business_allowed:true}),wealthProducts:async()=>[],wealthPositions:async()=>[],wealthOrders:async()=>[],wealthAssessment:async()=>({grade_display:"C5",expired:false,suitable:true,reasons:[]}),wealthAccounts:async()=>[],wealthWorkflows:async()=>[],wealthQuestionnaire:async()=>({version:"mock-v1",questions:[]}),wealthAnalyze:body=>{calls.push(body);return pending.promise;}});
 try{await render(WealthPage,{},async r=>{
  assert.equal(calls.length,0);
  await act(async()=>r.root.findByProps({"aria-label":"推荐金额"}).props.onChange({target:{value:"5000"}}));
  await act(async()=>{button(r,"个性化推荐").props.onClick();button(r,"个性化推荐").props.onClick();});
  assert.equal(calls.length,1);assert.equal(calls[0].amount,"5000");
  await act(async()=>pending.resolve({...analysis,needs:{...analysis.needs,amount:"5000"}}));
  assert.ok(text(r.toJSON()).includes(analysis.conclusion));
  await act(async()=>poll());assert.equal(calls.length,1);
 });}finally{Object.assign(api,original);globalThis.document=oldDocument;globalThis.setInterval=oldSet;globalThis.clearInterval=oldClear;}
});


test("unassessed purchase reply shows assessment link without purchase workflow",async()=>{
 const turn={user:{content:"我想购买理财产品"},tasks:[{task_id:"entry",conversation_id:"c",status:"COMPLETED",output:{route:"WEALTH_ANALYSIS",requested_output:"ANSWER"}}],plans:[],workflows:[],reports:[],replies:[{message_id:"guide",role:"ASSISTANT",content:"购买理财前，请先完成有效的风险测评。\n\n[前往理财中心查看并完成风险测评](/wealth)"}]};
 await render(AssistantTurn,{turn,activityRevision:0,highlightedResult:null,onRefresh:async()=>{}},async r=>{
  assert.ok(text(r.toJSON()).includes("购买理财前"));
  assert.ok(r.root.findAllByType("a").some(a=>a.props.href==="/wealth"));
  assert.ok(!text(r.toJSON()).includes("补全或修改交易"));
 });
});

for(const state of ["missing","expired"]){test(`${state} assessment blocks purchase entry and preserves browsing`,async()=>{
 const original={...api};const oldDocument=globalThis.document;
 globalThis.document={visibilityState:"hidden",addEventListener:()=>{},removeEventListener:()=>{}};
 let writes=0;
 Object.assign(api,{wealthStatus:async()=>({new_business_allowed:true}),wealthProducts:async()=>[{product_id:"p",name:"演示产品",risk:"R1",sources:[],tradable:true,purchase_allowed:true,minimum_display:"100.00元",open_display:"每日开放"}],wealthPositions:async()=>[],wealthOrders:async()=>[],wealthAssessment:async()=>state==="missing"?null:{grade_display:"C1",expired:true,suitable:true,reasons:[]},wealthAccounts:async()=>[],wealthWorkflows:async()=>[],wealthQuestionnaire:async()=>({version:"mock-v1",questions:[]}),wealthCreate:async()=>{writes++;return {};}});
 try{await render(WealthPage,{},async r=>{
  const purchase=button(r,"购买演示产品");assert.equal(purchase.props.disabled,true);
  assert.ok(text(r.toJSON()).includes("演示产品"));
  assert.ok(text(r.toJSON()).includes(state==="missing"?"请先由本人完成风险测评":"已失效，请重测"));
  await act(async()=>purchase.props.onClick());assert.equal(writes,0);
 });}finally{Object.assign(api,original);globalThis.document=oldDocument;}
});}

test("legacy unsubmitted purchase hides fields when current assessment is missing, but keeps cancel",async()=>{
 const {WealthWorkflowCard}=await import("../features/wealth/WealthCards.tsx");
 const original={...api};let cancelled=0;
 api.cancelWorkflow=async(id,version)=>{assert.equal(id,"legacy");assert.equal(version,3);cancelled++;};
 const resources={products:[],accounts:[],positions:[],newBusinessAllowed:true};
 const workflow={workflow_id:"legacy",conversation_id:"c",version:3,status:"WAITING_FOR_INPUT",presentation:{wealth_state:{draft:{direction:"PURCHASE"},purchase_entry_allowed:false,purchase_entry_block_reason:"请先完成风险测评"}}};
 try{await render(WealthWorkflowCard,{workflow,resources,onRefresh:async()=>{}},async r=>{
  assert.ok(text(r.toJSON()).includes("购买理财前"));
  assert.equal(r.root.findAllByType("input").length,0);assert.equal(r.root.findAllByType("select").length,0);
  assert.ok(r.root.findAllByProps({href:"/wealth#risk-assessment"}).length);
  await act(async()=>button(r,"取消草稿").props.onClick());assert.equal(cancelled,1);
 });}finally{Object.assign(api,original);}
});

test("purchase interest opens account and amount editor, then creates one review draft",async()=>{
 const {WealthPurchaseEntry}=await import("../features/wealth/WealthPurchaseEntry.tsx");
 const original={...api};const pending=deferred();let calls=[],loads=0,refreshes=0;
 api.wealthAccounts=async()=>{loads++;return [{account_id:"salary",display_name:"工资卡",balance_display:"8,000.00 元"}];};
 api.wealthCreate=body=>{calls.push(body);return pending.promise;};
 const product={product_id:"p",name:"演示进取周享",purchase_allowed:true,minimum_display:"5,000.00 元"};
 try {await render(WealthPurchaseEntry,{product,allowed:true,conversationId:"c",creationKey:"saved-key",onRefresh:async()=>{refreshes++;}},async r=>{
  assert.equal(calls.length,0);
  await act(async()=>button(r,"购买演示进取周享").props.onClick());
  assert.equal(loads,1);assert.equal(calls.length,0);
  assert.equal(button(r,"下一步：核对申购").props.disabled,true);
  await act(async()=>r.root.findByType("select").props.onChange({target:{value:"salary"}}));
  await act(async()=>r.root.findByType("input").props.onChange({target:{value:"5000.01"}}));
  await act(async()=>{button(r,"下一步：核对申购").props.onClick();button(r,"下一步：核对申购").props.onClick();});
  assert.equal(calls.length,1);assert.equal(calls[0].quantity,"5000.01");assert.equal(calls[0].account_id,"salary");assert.equal(calls[0].conversation_id,"c");assert.equal(calls[0].creation_key,"saved-key");
  await act(async()=>pending.resolve({conversation_id:"c",workflow_id:"w"}));
  assert.equal(refreshes,1);assert.equal(r.root.findByType("a").props.href,"/?conversation=c");
  assert.equal(r.root.findAllByType("input").length,0);
 });}finally{Object.assign(api,original);}
});

test("product introductions cannot bypass missing assessment or paused business",async()=>{
 const {WealthPurchaseEntry}=await import("../features/wealth/WealthPurchaseEntry.tsx");
 for(const props of [{allowed:false,product:{name:"演示稳享日日",purchase_allowed:true}},{allowed:true,product:{name:"演示稳享日日",purchase_allowed:false,purchase_block_reason:"请先完成风险测评"}}]){
  await render(WealthPurchaseEntry,props,async r=>{assert.equal(r.root.findByType("button").props.disabled,true);assert.equal(r.root.findAllByType("input").length,0);});
 }
});

test("analysis stays in prose, while product card reuses centre facts without numbering",async()=>{
 const original=api.wealthDocument;
 api.wealthDocument=async()=>({section:"产品说明书",version:"v1",content:"模拟产品条款正文"});
 const product={product_id:"p",name:"演示进取周享",risk:"R4",minimum_display:"5,000.00 元",open_display:"每周五 15:00前",fees_display:"申购0.30% / 赎回0.30%",nav_display:"1.001234",nav_date:"2026-10-09",sources:["/api/v1/wealth/documents/p:v1:1"],purchase_allowed:true};
 const schedule={trade_date:"2026-10-16",confirm_at:"2026-10-19T10:00:00+08:00",settle_at:"2026-10-20T10:00:00+08:00"};
 const candidate={fact_id:"f",purchase_entry_key:"key",product,advantages:["申请窗口比每日开放产品少。"],limitations:["赎回后要等待现金到账。"],unsuitable_when:["需要立即用钱"],unknowns:["尚未选择付款账户"],matched_conditions:["问卷进取目标仅供参考"],timing:{purchase:schedule,earliest_redeem_new:schedule,redeem_existing:schedule,earliest_cash_at:schedule.settle_at,notice:"模拟规则"},history:{notice:"模拟历史",data_as_of:analysis.reference_time}};
 try{await render(WealthAnalysisCard,{analysis:{...analysis,result_kind:"PRODUCT_INTRO",candidates:[candidate],evidence:[]}},async r=>{
  const article=r.root.findByType("article");assert.equal(article.props.className,"rounded-xl border bg-white p-5");
  assert.equal(text(article.findByType("h3")),"演示进取周享（模拟）");
  assert.ok(text(article).includes("1.001234"));assert.ok(text(article).includes("购买演示进取周享"));
  assert.ok(!text(article).includes(candidate.limitations[0]));assert.ok(!text(article).includes("相对优势"));
  const prose=r.root.findByProps({"aria-label":"产品分析正文"});assert.ok(text(prose).includes(candidate.limitations[0]));assert.ok(text(prose).includes(candidate.advantages[0]));
  await act(async()=>button(r,"产品说明书").props.onClick());assert.ok(text(r.toJSON()).includes("模拟产品条款正文"));
  await act(async()=>button(r,"关闭资料").props.onClick());assert.equal(r.root.findAllByProps({role:"dialog"}).length,0);
 });}finally{api.wealthDocument=original;}
});

test("accepted response has checkmark and expandable process, without spinner or financial success",async()=>{
 const {ResponseProcess}=await import("../features/conversation/ResponseProcess.tsx");
 const original=api.listTaskEvents;api.listTaskEvents=async()=>[];
 const turn={tasks:[{task_id:"t",status:"WAITING_EXTERNAL"}],plans:[],workflows:[{workflow_type:"WEALTH_PURCHASE",source_task_id:"t",status:"COMMITTING",presentation:{business_success:false,wealth_state:{order_received:true,order_stage:"ACCEPTED"}}}]};
 try{await render(ResponseProcess,{turn,activityRevision:0,onRefresh:async()=>{}},async r=>{
  assert.ok(text(r.toJSON()).includes("✓申请已提交，成交后会通知你"));
  assert.equal(r.root.findAll(n=>n.props.className?.includes("animate-spin")).length,0);
  assert.equal(r.root.findByType("details").props.open,false);
  await act(async()=>r.root.findByType("details").props.onToggle({currentTarget:{open:true}}));
  assert.equal(r.root.findByType("details").props.open,true);assert.equal(turn.workflows[0].presentation.business_success,false);
 });}finally{api.listTaskEvents=original;}
});

test("customer response shows supplied budget and prose without internal analysis panels",async()=>{
 const response={headline:"先看每日开放的产品，申请时间比较灵活。",budget_display:"100,000,000.00 元",paragraphs:[{block_id:"p",text:"周开放产品只有固定申请日，需要提前安排。"}],questions:["这笔钱最早什么时候要用？"]};
 await render(WealthAnalysisCard,{analysis:{...analysis,needs:{...analysis.needs,amount:"100000000",raw:"我的预算10000万",assumptions:["内部假设"]},customer_response:response}},async r=>{
  const content=text(r.toJSON());assert.ok(content.includes("100,000,000.00 元"));assert.ok(content.includes(response.paragraphs[0].text));
  for(const hidden of ["尚未提供","已知条件与资料缺失","未确认信息与分析前提","内部假设","如何筛选这些产品"])assert.ok(!content.includes(hidden),hidden);
  assert.equal(r.root.findByProps({"aria-label":"理财分析"}).props.className.includes("border"),false);
 });
});

test("old missed budget is quoted as supplied, without rewriting snapshot or guessing fees",async()=>{
 const old={...analysis,needs:{...analysis.needs,raw:"我的预算10000万，我希望购买的产品能赚的比较多，可以接受部分亏损",clarification_questions:["这次计划投资多少元？","最早何时用钱？"]}};
 await render(WealthAnalysisCard,{analysis:old},async r=>{
  const content=text(r.toJSON());assert.ok(content.includes("预算10000万"));assert.ok(!content.includes("投资多少元"));assert.ok(!content.includes("尚未提供"));
  assert.ok(content.includes("历史回复没有按该预算计算费用"));assert.equal(old.needs.amount,null);
 });
});

test("legacy missed budget reanalysis is user initiated and deduplicated",async()=>{
 const original=api.postMessage;const pending=deferred();let calls=0,refreshes=0;
 api.postMessage=()=>{calls++;return pending.promise;};
 try{await render(WealthAnalysisCard,{analysis:{...analysis,needs:{...analysis.needs,raw:"我的预算10000万"}},conversationId:"c",onRefresh:async()=>{refreshes++;}},async r=>{
  assert.equal(calls,0);
  await act(async()=>{button(r,"按当前条件重新分析").props.onClick();button(r,"按当前条件重新分析").props.onClick();});
  assert.equal(calls,1);await act(async()=>pending.resolve({}));assert.equal(refreshes,1);
  assert.equal(button(r,"已发起新的只读分析").props.disabled,true);
 });}finally{api.postMessage=original;}
});

test("deleted accepted chat retains order and audit without broken conversation links",async()=>{
 const original={...api};const oldDocument=globalThis.document;
 globalThis.document={visibilityState:"hidden",addEventListener:()=>{},removeEventListener:()=>{}};let audited;
 Object.assign(api,{wealthStatus:async()=>({new_business_allowed:true}),wealthProducts:async()=>[],wealthPositions:async()=>[],wealthOrders:async()=>[{order_id:"o",workflow_id:"w",conversation_id:null,conversation_deleted:true,source_task_id:"t",name:"演示稳享日日",direction_display:"申购",status_display:"待成交",quantity_display:"1,000.00 元",sources:[]}],wealthAssessment:async()=>null,wealthAccounts:async()=>[],wealthWorkflows:async()=>[{workflow_id:"w",conversation_id:"deleted",status:"COMMITTING",workflow_type:"WEALTH_PURCHASE"}],wealthQuestionnaire:async()=>({version:"v1",questions:[]}),getTaskAudit:async id=>{audited=id;return {write_evidence:{business_success:false,skipped_write_step_ids:[]},entries:[],resources:[]};}});
 try{await render(WealthPage,{},async r=>{
  assert.ok(text(r.toJSON()).includes("原对话已删除，订单与办理记录仍保留"));assert.ok(text(r.toJSON()).includes("待成交"));
  assert.ok(!r.root.findAllByType("a").some(a=>a.props.href?.includes("conversation=")));
  await act(async()=>button(r,"查看审计事件").props.onClick());assert.equal(audited,"t");
 });}finally{Object.assign(api,original);globalThis.document=oldDocument;}
});

test("catalogue displays objective introduction and shared product cards without recommendation panels",async()=>{
 const product={product_id:"p",name:"演示稳享日日",risk:"R1",minimum_display:"100.00 元",open_display:"每个模拟交易日15:00前",fees_display:"申购0% / 赎回0%",nav_display:"1.001000",nav_date:"2026-10-09",sources:[],purchase_allowed:true};
 const catalogue={...analysis,result_kind:"CATALOGUE",status:"EDUCATION",conclusion:"目前有8款模拟净值型理财，两类都不是随时提现。",needs:{...analysis.needs,assumptions:["未确认信息与分析前提"],clarification_questions:[]},customer_response:{headline:"目前有8款模拟净值型理财，两类都不是随时提现。",questions:[],paragraphs:[{block_id:"risk",text:"净值可能下跌，本金和收益都没有保证。"}]},candidates:[{fact_id:"f1",product,purchase_entry_key:"k1",unknowns:["已知条件与资料缺失"]},{fact_id:"f2",product:{...product,product_id:"p2",name:"演示稳享周周"},purchase_entry_key:"k2"}]};
 await render(WealthAnalysisCard,{analysis:catalogue},async r=>{
  const content=text(r.toJSON());assert.ok(content.includes("产品介绍"));assert.ok(content.includes("8款"));assert.ok(content.includes("本金和收益都没有保证"));
  assert.equal(r.root.findAllByType("article").length,2);assert.equal(r.root.findAllByType("table").length,0);
  for(const hidden of ["这次也","未确认信息与分析前提","已知条件与资料缺失","如何筛选","投资多少元","先供你参考"])assert.ok(!content.includes(hidden),hidden);
 });
});
