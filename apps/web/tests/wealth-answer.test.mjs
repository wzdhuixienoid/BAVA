import assert from "node:assert/strict";
import test from "node:test";
import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import "./tsx-loader.mjs";
const {wealthAnswer,isWealthOnlyAnswer} = await import("../features/wealth/answer.ts");
const {AssistantTurn} = await import("../features/conversation/AssistantTurn.tsx");
const product = {product_id:"mock-wealth-01",name:"演示稳享日日",risk:"R1",minimum_display:"100.00 元",open_display:"每个模拟交易日15:00前",fees_display:"申购0.00% / 赎回0.00%",sources:["/api/v1/wealth/documents/mock-wealth-01:v1:1"],nav_display:"1.008387",nav_date:"2026-10-09"};
const output = {wealth_results:[{products:[product,{...product,product_id:"mock-wealth-02",name:"演示进取成长"}]},{products:[product],selected_reasons:{"mock-wealth-01":["符合用款时间及起购要求，已按风险偏好、开放安排与费用排序"]},reasons:["依据有效Mock测评和本次明确需求确定性筛选；模拟净值型产品不保本"]}]};
test("historical wealth reply shows final selection once, without model provenance or raw source paths",()=>{
 const turn={user:{content:"推荐理财"},tasks:[{task_id:"t",status:"COMPLETED",output}],plans:[],workflows:[],reports:[],replies:[{message_id:"m",role:"ASSISTANT",content:"工具返回，未做调整 mock-wealth-01 /api/v1/wealth/documents/123 工具原文"}]};
 const html=renderToStaticMarkup(createElement(AssistantTurn,{turn,activityRevision:0,highlightedResult:null,onRefresh:async()=>{}}));
 for(const text of ["100.00 元","R1","1.008387","2026-10-09","产品说明书","不保证本金或收益"]) assert.ok(html.includes(text),text);
 for(const text of ["工具返回","工具原文","mock-wealth-01","/api/v1/","确定性","排序","演示进取成长"]) assert.ok(!html.includes(text),text);
 assert.equal(html.split("演示稳享日日（模拟）").length-1,1);
});
test("empty constrained recommendation does not fall back to full catalogue",()=>{
 const result=wealthAnswer([{wealth_results:[{products:[product]},{products:[],constraints:{capital_guaranteed:true},reasons:["您要求保本，目前没有符合要求的产品"]}]}]);
 assert.deepEqual(result.products,[]); assert.match(result.reasons[0],/保本/);
});
test("mixed business replies are preserved and stored order/evidence facts are retained",()=>{
 assert.equal(isWealthOnlyAnswer([output,{account_results:[{}]}]),false);
 const result=wealthAnswer([{wealth_results:[{orders:[{order_id:"o",user_reason:"资金待到账"}],evidence:[{document_id:"d",content:"费用说明"}]}]}]);
 assert.equal(result.orders[0].user_reason,"资金待到账"); assert.equal(result.evidence[0].content,"费用说明");
});

test("named source button opens authenticated document without exposing API address",async()=>{
 const {act,create}=await import("react-test-renderer");
 const {WealthSources}=await import("../features/wealth/WealthCards.tsx");
 const {api}=await import("../lib/api/client.ts");
 const original=api.wealthDocument;const oldAct=globalThis.IS_REACT_ACT_ENVIRONMENT;
 globalThis.IS_REACT_ACT_ENVIRONMENT=true;let requested;let renderer;
 api.wealthDocument=async id=>{requested=id;return {document_id:id,section:"说明书",version:"v1",content:"净值可能上涨或下跌，不保证本金。",source:"/api/v1/wealth/documents/mock-wealth-01:v1:1"};};
 try {
  await act(async()=>{renderer=create(createElement(WealthSources,{sources:product.sources}));});
  await act(async()=>renderer.root.findByType("button").props.onClick());
  const rendered=JSON.stringify(renderer.toJSON());
  assert.equal(requested,"mock-wealth-01:v1:1");
  assert.ok(rendered.includes("净值可能上涨或下跌"));assert.ok(rendered.includes("第1版"));
  assert.ok(!rendered.includes("/api/v1/"));assert.ok(!rendered.includes("mock-wealth-01"));
  await act(async()=>renderer.root.findAllByType("button").find(button=>button.children.includes("关闭资料")).props.onClick());
  assert.equal(renderer.root.findAllByProps({role:"dialog"}).length,0);
 } finally {if(renderer)await act(async()=>renderer.unmount());api.wealthDocument=original;globalThis.IS_REACT_ACT_ENVIRONMENT=oldAct;}
});
