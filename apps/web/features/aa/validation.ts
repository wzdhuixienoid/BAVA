export type DraftFields = {total:string; people:string; self:string; account:string; remark:string; deadline:string; manual:string};
export type FieldErrors = Partial<Record<keyof DraftFields,string>>;
export const participantNames = (text:string) => text.split(/[、,，]/).map(x=>x.trim()).filter(Boolean);
function moneyCents(text:string):bigint | null {
  if(!/^\d+(?:\.\d{1,2})?$/.test(text.trim()))return null;
  const [whole,fraction=""] = text.trim().split(".");
  const amount = BigInt(whole)*BigInt(100) + BigInt(fraction.padEnd(2,"0"));
  return amount>BigInt(0) && amount<=BigInt(1000000000) ? amount : null;
}
export function validateDraft(fields:DraftFields, accountIds:string[], now=Date.now()):FieldErrors {
  const errors:FieldErrors={};
  const total=moneyCents(fields.total);
  if(total===null)errors.total="请输入大于 0、不超过 1000 万元的金额，最多两位小数。";
  const names=participantNames(fields.people);
  if(!names.length)errors.people="请填写其他参与者的姓名。";
  else if(names.some(n=>["我","自己","本人"].includes(n)))errors.people="参与者只填写其他人，请移除“我”；自己的份额由“发起者是否参与”控制。";
  else if(new Set(names).size!==names.length)errors.people="参与者不能重复。";
  else if(names.length>20)errors.people="最多填写 20 位参与者。";
  else if(names.some(n=>!["张三","李四","王五"].includes(n)))errors.people="当前站内 Mock 支持张三、李四、王五，请选择已登记的参与者。";
  if(!["true","false"].includes(fields.self))errors.self="请选择你是否参与分摊。";
  if(!fields.account || !accountIds.includes(fields.account))errors.account="请选择可用的收款账户。";
  if(Array.from(fields.remark.trim()).length>100 || /[\p{Cc}]/u.test(fields.remark))errors.remark="主题备注最多 100 个字符，不能包含控制字符。";
  const text=fields.deadline.trim();
  const date=new Date(`${text.replace(" ","T")}+08:00`);
  const formatted=Number.isNaN(date.getTime())?"":new Date(date.getTime()+8*3600000).toISOString().slice(0,19).replace("T"," ");
  if(!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text) || formatted!==text)errors.deadline="请输入有效时间，格式为 YYYY-MM-DD HH:mm:ss。";
  else if(date.getTime()<=now)errors.deadline="截止时间必须晚于当前时间。";
  if(fields.manual.trim()) {
    const entries=participantNames(fields.manual).map(x=>x.split("=").map(y=>y.trim()));
    const expected=fields.self==="true"?[...names,"我"]:names;
    if(entries.some(e=>e.length!==2 || moneyCents(e[1])===null))errors.manual="请按“张三=40、李四=30、我=30”填写，每人金额必须大于 0，最多两位小数。";
    else if(new Set(entries.map(e=>e[0])).size!==entries.length)errors.manual="每位参与者的手动金额只能填写一次。";
    else if(entries.length!==expected.length || entries.some(e=>!expected.includes(e[0])))errors.manual="请为每位参与者填写金额；选择自己参与时，也要填写“我”的金额。";
    else if(total!==null && entries.reduce((sum,e)=>sum+moneyCents(e[1])!,BigInt(0))!==total)errors.manual="手动分摊金额之和必须等于总额。";
  } else if(total!==null && names.length && total<BigInt(names.length+(fields.self==="true"?1:0)))errors.total="总额不足以让每位参与者分摊至少 0.01 元。";
  return errors;
}
export function serverFieldError(code:string):FieldErrors {
  if(code.includes("AA_PARTICIPANT_NOT_REGISTERED_OR_SELF"))return {people:"参与者必须是其他已登记用户，不能填写自己。"};
  if(code.includes("AA_PARTICIPANTS_INVALID"))return {people:"请填写参与者，且不要重复。"};
  if(code.includes("AA_MANUAL"))return {manual:"请核对每人的手动金额，参与者应一致，金额之和应等于总额。"};
  if(code.includes("AA_AMOUNT"))return {total:"请核对金额及分摊金额，必须为正数且最多两位小数。"};
  if(code.includes("AA_COLLECTION_ACCOUNT"))return {account:"请选择可用的收款账户。"};
  if(code.includes("AA_DEADLINE"))return {deadline:"请填写有效且晚于当前时间的截止时间。"};
  return {};
}
