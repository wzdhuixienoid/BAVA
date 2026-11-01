import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
EDL=json.loads((ROOT/'edit-decision-list.json').read_text())
byname={s['name']:s for s in EDL}
ROWS=[]
def cue(first,last,text):ROWS.append(dict(start=byname[first]['start'],end=byname[last]['end'],text=text))
cue('00-brand','00-brand','BAVA，让银行操作从自然语言走向可信执行。')
cue('01-accounts','01-accounts','账户余额来自银行服务，查询时点清晰可见。')
cue('02-bill-question','03-bill-send','先说出月份和需求，发起一份消费报告。')
cue('04-bill-card','04-bill-card','只读分析自动完成，生成报告卡片。')
cue('05-report-top','05-report-top','报告展示本期收支、45笔消费，以及相较上月的变化。')
cue('06-categories','06-categories','分类构成让支出去向一目了然。住房支出6200元，是最大的消费类别。')
cue('07-transactions','07-transactions','主要交易保留商户、金额和日期，让分析能够回到实际账单核对。')
cue('08-report-history','10-bill-context','报告保存到历史，也留在当前对话中，之后可以接着办理其他业务。')
cue('11-sub-query','12-sub-send','接着盘点当前订阅，前面的报告记录继续保留。')
cue('13-read-consent','13-read-consent','先确认读取，查询授权有效期为五分钟。')
cue('14-sub-table','14-sub-table','系统区分可以直接管理的订阅，以及需要前往商户处理的周期扣费。')
cue('15-sub-fees','15-sub-fees','月度费用、价格变化和续费时间一并呈现。')
cue('16-cancel-question','17-cancel-send','在同一对话里说“取消星幕视频”，进入黄色权限操作。')
cue('18-cancel-review','18-cancel-review','先核对商户、套餐、金额和下次扣费日期。')
cue('19-cancel-approve','19-cancel-approve','确认代表批准这次取消，此时业务仍未生效。')
cue('20-cancel-commit','20-cancel-commit','再单独提交。服务返回已取消回执，业务才算完成。')
cue('21-open-subscriptions','22-requery-costs','重新授权回查，月度成本变为230元，预计年度成本变为2760元。')
cue('23-cancelled-contract','23-cancelled-contract','合约与下次扣款同步更新；预计节省不代表退款。')
cue('24-back-to-history','25-cancel-receipt-context','回到原对话，前面的报告和取消回执都还在。接下来办理转账。')
cue('26-yellow-question','27-yellow-send','说出工资卡、李小雨、100元和餐费备注，系统整理成转账信息。')
cue('28-yellow-risk','28-yellow-risk','100元低于本人的200元免密额度，日累计也未超过1000元，进入黄色权限。')
cue('29-yellow-details-scroll','30-yellow-approve','核对付款账户、收款人尾号和备注，再明确确认。此时只是批准业务内容，资金尚未提交。')
cue('31-yellow-commit','31-yellow-commit','点击提交转账，由模拟银行实际执行，并返回100元成功回执。')
cue('32-yellow-balance','34-yellow-receipt-context','独立查到工资卡余额23764.52元，再回到刚才的回执，继续办理复杂任务。')
cue('35-condition-question','36-condition-send','从小额操作进入条件任务：先查工资卡余额，不少于3000元时，再向张三转1200元。')
cue('37-dag','37-dag','系统拆出查询、条件判断和转账三个依赖步骤，使用查询到的余额作确定性判断。')
cue('38-pause','38-pause','用户可以随时接管任务，暂停自动编排。')
cue('39-resume','39-resume','继续执行会恢复同一计划，保留已经完成的步骤和条件。')
cue('40-payee-scroll','41-payee-choice','遇到同名收款人，系统等待用户核对银行与账号尾号，明确选择具体对象。')
cue('42-red-risk','43-red-details-scroll','条件成立不等于付款授权。本笔1200元使当日累计达到1300元，必须确认并强验证。')
cue('44-red-approve','44-red-approve','再次核对这笔转账，明确确认后进入身份验证，仍不会直接扣款。')
cue('45-verification-start','45-verification-start','这里使用Mock验证码演示身份验证门禁。')
cue('46-masked-code','47-verify','验证码以掩码输入，系统校验与本次业务绑定的验证挑战。')
cue('48-verified-unsubmitted','48-verified-unsubmitted','验证已通过，资金仍未提交。')
cue('49-red-commit','49-red-commit','最后单独提交。模拟银行确认执行成功，才生成1200元转账回执。')
cue('50-completed-plan','50-completed-plan','回到计划，查询、判断和受控转账三个步骤全部完成。')
cue('51-final-balance','51-final-balance','再次独立查账，工资卡余额为22564.52元。')
cue('52-final-ledger','52-final-ledger','两笔转账分别入账，金额与回执一致。')
cue('53-final-conversation','53-final-conversation','历史结果都留在原对话，完成可核验的业务闭环。')
def tc(t):
 ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
def clock(t):return f'{int(t)//60:02}:{t%60:04.1f}'
(ROOT/'narration.json').write_text(json.dumps(ROWS,ensure_ascii=False,indent=2))
(ROOT/'BAVA-demo-continuous.srt').write_text('\n'.join(f"{i}\n{tc(r['start'])} --> {tc(r['end'])}\n{r['text']}\n" for i,r in enumerate(ROWS,1)))
lines=['# BAVA 连续演示版：产品讲解稿与时间轴','',
'成片04:44.2，1920×1080、30 fps，静音，无内嵌讲解字幕。以下文案可供后期配音与字幕使用，配套SRT已对齐成片。','',
'## 演示主线','',
'同一个“BAVA 银行服务演示”对话、同一套Mock数据，依次完成账单分析、订阅管理、小额转账和带条件的大额转账。每段办理后返回原对话继续下一项，不新建对话、不重置数据；所有早期消息和业务结果均保留。','',
'| 时间 | 场景 |','|---|---|','| 00:00–00:09 | 品牌与账户事实 |','| 00:09–00:50 | 账单分析与报告保存 |','| 00:50–01:58 | 沿用报告对话，查询、取消并回查订阅 |','| 01:58–02:43.5 | 沿用取消回执，发起100元转账并查余额 |','| 02:43.5–04:24 | 条件DAG、暂停恢复、收款人消歧、强验证与提交 |','| 04:24–04:44.2 | 最终查账并回到保留完整历史的原对话 |','',
'## 逐段讲解文案','', '| 时间 | 文案 |','|---|---|']
lines += [f"| {clock(r['start'])}–{clock(r['end'])} | {r['text']} |" for r in ROWS]
lines += ['', '## 提问原文','',
'1. 分析2026年8月消费，生成报告','2. 我有哪些订阅？','3. 取消星幕视频','4. 从工资卡给李小雨转100元，备注餐费','5. 查工资卡余额，如果余额不少于3000元，给张三转1200元','',
'## 本版修复与录制说明','',
'- 全部业务使用同一会话与同一数据副本。转账开始前仍可见取消回执，条件任务开始前仍可见100元转账回执，最后返回原会话收尾。',
'- 从头重新录制，原生画面中已无之前插件的悬浮图标。没有沿用旧版业务镜头，没有用截图拼出操作过程。',
'- 保留每次关键导航、必要滚动、确认、验证、提交、状态变化及回执。剪去长时间静止等待，保持业务顺序。',
'- 网页画面四角统一为24px抗锯齿圆角。提问时平滑聚焦同一时刻录屏中的真实输入框，其余画面使用固定构图。',
'- 产品区域x=170、y=112、宽1580、高856，底边968，始终位于y=987的底部分隔线上方。',
'- 参考号只隐藏显示，原始结果与审计数据保留；验证码以密码掩码输入。所有金融数据、商户、收款人与交易均为Mock演示，身份验证未接入真实短信、人脸或生产多因子认证。',
'- 查询订阅的确认按钮会在同一会话中重新提交原查询，因此后台保留两条“我有哪些订阅？”用户消息；并非新建会话。',
'- business-verification.json核验同一会话、全部早期消息ID保留、同一报告、订阅费用变化、权限门禁及两笔转账唯一执行。edit-decision-list.json保存每个镜头的原始录像与时间。','',
'## 原生录像映射','', '| 成片时间 | 原生录像 | 源时间 |','|---|---|---|']
lines += [f"| {clock(s['start'])}–{clock(s['end'])} | {s['source']} | {s['raw_start']:.3f}–{s['raw_end']:.3f} |" for s in EDL]
(ROOT/'产品讲解稿与时间轴.md').write_text('\n'.join(lines)+'\n')
print('Wrote',len(ROWS),'aligned cues; end',ROWS[-1]['end'])
