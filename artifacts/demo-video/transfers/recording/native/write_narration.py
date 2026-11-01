import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ROWS=[
 (0,4.95,'说出转账需求，系统整理账户、收款人、金额和备注。'),
 (4.95,11.9,'小额转账也要明确授权。本笔低于个人免密额度，确认后可免强验证。'),
 (11.9,18.1,'确认只代表授权；显式提交后，才由银行模拟服务返回实际结果。'),
 (18.1,25,'回到账户页面核对余额，查询结果与转账回执相互印证。'),
 (25,33,'更复杂的需求，可以把条件和转账一起说出：先查余额，再决定是否进入办理流程。'),
 (33,38,'BAVA将需求拆为查询、条件判断和转账三个有依赖的步骤。'),
 (38,42.1,'余额来自查询结果，再按3000元阈值确定性判断。'),
 (42.1,45.4,'用户可以接管任务，暂停自动编排。'),
 (45.4,50,'继续执行会恢复同一计划，已完成的步骤和条件仍然保留。'),
 (50,54,'出现同名收款人时，核对银行和账号后再继续。'),
 (54,65.5,'条件成立不等于付款授权。系统按本笔金额和日累计评估风险；红色操作仍需确认和强验证。'),
 (65.5,69.4,'此处使用Mock验证码演示身份验证门禁。'),
 (69.4,72,'验证通过，资金仍未提交。'),
 (72,80.4,'再单独提交这笔转账，最终以银行模拟服务确认的回执为准。'),
 (80.4,90,'最后重新查账：工资卡余额22,564.52元，两笔转账分别入账，完成可核验的业务闭环。'),
]
def tc(v):
 ms=round(v*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
def clock(v):return f'{int(v)//60:02}:{v%60:05.2f}'
rows=[{'start':a,'end':b,'text':t} for a,b,t in ROWS]
(ROOT/'narration-part4.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(ROOT/'BAVA-part4-native.srt').write_text('\n'.join(f'{n}\n{tc(a)} --> {tc(b)}\n{t}\n' for n,(a,b,t) in enumerate(ROWS,1)))
lines=['# BAVA 第四部分：原生操作实录','', '视频90秒，整片位置01:35–03:05。无音轨、无内嵌讲解字幕。以下文案可用于后期配音和字幕。','',
'原定提问原文：','', '1. 从工资卡给李小雨转100元，备注餐费','2. 查工资卡余额，如果余额不少于3000元，给张三转1200元','',
'| 本段时间 | 整片时间 | 建议讲解文案 |','|---|---|---|']
lines += [f'| {clock(a)}–{clock(b)} | {clock(a+95)}–{clock(b+95)} | {t} |' for a,b,t in ROWS]
lines += ['', '## 录制说明','',
'- 使用 Apple ScreenCaptureKit 原生窗口录制，原始 MP4 保存了完整连续画面；成片仅使用此录像中的动态片段。未使用逐张截图组装业务过程。',
'- 保留实际文字输入、鼠标、滚动、计划更新、暂停与恢复、收款人选择、确认、模拟验证、提交、回执和账单查询。剪去静止等待及重复取景；不改变业务先后顺序。',
'- 提问聚焦来自同一时刻录屏中的实时输入框。业务界面统一固定在1580×856的区域内，底边968，低于底部分隔线987。',
'- 录制副本只隐藏参考号的显示样式，未修改银行返回值、工作流状态、金额或审计数据。业务运行于独立的 Mock 演示环境；身份验证为 Mock 验证码，不代表已接入真实短信、人脸或生产多因子认证。',
'- 原始录像包含同一计划的两次暂停与恢复取景，成片保留一次。两笔资金操作各提交一次，关联审计均只有一笔 Provider 入账。',
'- 前95秒沿用已确认的第3部分稳定v8合辑，原文件未修改。',
'- `edit-decision-list.json`提供原始录像与成片时间对应，`business-verification.json`提供业务核验。']
(ROOT/'第四部分文案与时间轴.md').write_text('\n'.join(lines)+'\n')
previous=json.loads((ROOT.parents[2]/'subscriptions/narration-00-95.json').read_text())
prior=previous['cues'] if isinstance(previous,dict) else previous
full=[{'start':r['start'],'end':r['end'],'text':r['text']} for r in prior]+[{'start':a+95,'end':b+95,'text':t} for a,b,t in ROWS]
(ROOT/'BAVA-00-185.srt').write_text('\n'.join(f"{n}\n{tc(r['start'])} --> {tc(r['end'])}\n{r['text']}\n" for n,r in enumerate(full,1)))
(ROOT/'完整讲解稿_00-185.md').write_text('# BAVA 产品讲解稿 00:00–03:05\n\n| 时间 | 建议文案 |\n|---|---|\n'+'\n'.join(f"| {clock(r['start'])}–{clock(r['end'])} | {r['text']} |" for r in full)+'\n')
