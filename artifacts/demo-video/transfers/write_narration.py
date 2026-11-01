"""Export timecoded product explanation and optional subtitles for part four."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
START, END = 95, 165
CUES = [
    {"start": 95, "end": 99, "text": "一句话发起转账，先生成可核对的草稿。", "subtitle": "一句话发起转账，\n先生成可核对的草稿。", "purpose": "解释自然语言入口与先建立草稿的执行方式。", "picture": "输入从工资卡给张三转100元、备注聚餐AA；保留提问聚焦。"},
    {"start": 99, "end": 106, "text": "出现同名收款人时，银行和账号一起展示，由用户核对并选择。", "subtitle": "出现同名收款人时，银行和账号一起展示，\n由用户核对并选择。", "purpose": "说明歧义消解依赖用户核对，模型不会替用户猜测转账目标。", "picture": "两个张三候选，银行不同，尾号分别2231和9102；选择星河银行尾号2231。"},
    {"start": 106, "end": 113, "text": "后台按本人免密额度和日累计评估风险，小额转账也需要明确确认。", "subtitle": "后台按本人免密额度和日累计评估风险，\n小额转账也需要明确确认。", "purpose": "讲清风险判断由确定性规则执行，黄色操作需要独立确认。", "picture": "黄色风险卡、本笔100元、免密额度200元、累计100元；随后展示完整转账核对信息。"},
    {"start": 113, "end": 117, "text": "确认只代表授权，资金尚未转出。", "subtitle": "确认只代表授权，\n资金尚未转出。", "purpose": "区分用户授权与资金提交，避免把确认当作成功。", "picture": "用户确认已完成、无需强验证，同时明确显示尚未提交转账。"},
    {"start": 117, "end": 122, "text": "提交后核验实际结果，并保留对应回执。", "subtitle": "提交后核验实际结果，\n并保留对应回执。", "purpose": "说明最终结果来自执行服务，展示可复核的业务回执。", "picture": "实际100元成功回执、收款账户和备注、十步执行进度及确认已使用。"},
    {"start": 122, "end": 126, "text": "再看一笔1200元的转账。", "subtitle": "再看一笔1200元的转账。", "purpose": "用第二笔真实模拟操作引出更高风险的控制要求。", "picture": "输入从工资卡给李小雨转1200元、备注房租。"},
    {"start": 126, "end": 134, "text": "含本笔的当日累计达到1300元，系统评为红色，必须确认并强验证。", "subtitle": "含本笔的当日累计达到1300元，\n系统评为红色，必须确认并强验证。", "purpose": "解释累计风险如何改变执行权限，并让观众理解红色分级的依据。", "picture": "实际红色风险卡，已成功100元、本笔1200元、累计1300元；随后核对李小雨、工资卡和房租备注。"},
    {"start": 134, "end": 140, "text": "用户确认后，流程仍停在身份验证，不能直接提交资金操作。", "subtitle": "用户确认后，流程仍停在身份验证，\n不能直接提交资金操作。", "purpose": "说明确认意愿和验证身份是两条独立的安全控制。", "picture": "用户确认已完成，但强身份验证等待用户操作；展示开始身份验证。"},
    {"start": 140, "end": 146, "text": "本演示使用模拟验证码，验证结果会单独记录。", "subtitle": "本演示使用模拟验证码，\n验证结果会单独记录。", "purpose": "准确交代演示验证方式，避免暗示接通真实短信或其他身份渠道。", "picture": "实际待验证表单与执行进度；验证码数值不进入视频素材。"},
    {"start": 146, "end": 151, "text": "验证通过后重新核对，仍需显式提交这笔转账。", "subtitle": "验证通过后重新核对，\n仍需显式提交这笔转账。", "purpose": "解释验证通过只是允许继续，提交仍是独立动作。", "picture": "强身份验证已完成、转账信息已确认、尚未提交转账及完整转账详情。"},
    {"start": 151, "end": 159, "text": "确认、验证、业务成功分别记录；只有服务确认成功，才展示完成回执。", "subtitle": "确认、验证、业务成功分别记录；\n只有服务确认成功，才展示完成回执。", "purpose": "说明不同状态与最终结果的来源，突出可核验执行。", "picture": "实际1200元成功回执；十步进度、确认已使用、验证已通过、银行操作已成功及完成时间。"},
    {"start": 159, "end": 165, "text": "最后重新查询余额与交易明细，核对两笔转账已经入账。", "subtitle": "最后重新查询余额与交易明细，\n核对两笔转账已经入账。", "purpose": "用独立的账户和账单查询完成业务闭环，而非仅依赖对话回复。", "picture": "工资卡余额22564.52元，筛选后展示李小雨1200元与张三100元两条实际入账明细。"},
]


def timecode(seconds, comma=False):
    value = round(seconds * 1000)
    hour, value = divmod(value, 3600000)
    minute, value = divmod(value, 60000)
    second, ms = divmod(value, 1000)
    return f"{hour:02d}:{minute:02d}:{second:02d}{',' if comma else '.'}{ms:03d}"


def short(value):
    return f"{int(value // 60):02d}:{int(value % 60):02d}"


def srt(cues, offset=0):
    return "\n\n".join(f"{i}\n{timecode(c['start'] - offset, True)} --> {timecode(c['end'] - offset, True)}\n{c['subtitle']}" for i, c in enumerate(cues, 1)) + "\n"


def main():
    previous = json.loads((ROOT.parent / "subscriptions/narration-00-95.json").read_text())["cues"]
    combined = previous + CUES
    assert all(a["end"] == b["start"] for a, b in zip(combined, combined[1:]))
    assert combined[0]["start"] == 0 and combined[-1]["end"] == END
    base = {"part": 4, "style": "产品能力、用户价值、风险判断、授权与业务结果的区别", "voice_generated": False, "burned_in_subtitles": False, "bank_environment": "Mock", "reauthentication_environment": "MOCK_CODE"}
    (ROOT / "narration-95-165.json").write_text(json.dumps({**base, "start_seconds": START, "end_seconds": END, "cues": CUES}, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "narration-00-165.json").write_text(json.dumps({**base, "duration_seconds": END, "cues": combined}, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "BAVA-transfers.srt").write_text(srt(CUES, START))
    (ROOT / "BAVA-00-165.srt").write_text(srt(combined))
    rows = ["| 连续成片时间 | 第四部分内时间 | 建议讲解文案 | 对应画面与产品含义 |", "|---|---|---|---|"]
    rows += [f"| {short(c['start'])}–{short(c['end'])} | {short(c['start']-START)}–{short(c['end']-START)} | {c['text']} | {c['picture']} {c['purpose']} |" for c in CUES]
    text = """# BAVA 第四部分：智能转账与权限分级

连续成片 **01:35–02:45**，独立片长 **70秒**。1920×1080、30fps，无音轨、无内嵌讲解字幕。产品原生文字、BAVA品牌和模拟环境标识保留；讲解文案与SRT供后期单独添加。

本段以两笔实际模拟转账解释：自然语言建草稿 → 同名收款人核对 → 黄色确认 → 回执核验 → 红色强验证 → 显式提交 → 余额与入账核对。

""" + "\n".join(rows) + """

## 录制事实与边界

- 第一笔为工资卡给张三100元，备注“聚餐AA”。同名候选分别为星河银行（虚构）尾号2231与蓝海银行（虚构）尾号9102，实际选择前者；没有演示手机号直接转账。
- 本人的单笔免密额度为200元，规则要求单笔严格小于该额度且含本笔日累计不超过1000元。第一笔本笔与累计均100元，为黄色，需要确认，无需强验证。不能讲成“所有不超过1000元的转账都免强验证”。
- 第二笔为工资卡给李小雨1200元，备注“房租”，尾号4815。本笔达到个人免密额度，且含本笔累计1300元超过1000元，实际判为红色，要求确认和身份验证。
- 已保存确认前、确认后、挑战待验证、验证通过但未提交、最终成功的独立业务快照。确认和验证阶段均没有生成资金操作，余额直到提交成功后才变化。
- 验证方式为本地Mock验证码，不是短信、人脸、U盾或真实银行的多因子认证。视频不出现验证码数值，不以模拟验证代替真实身份渠道的实现声明。
- 工资卡余额依次为23864.52、23764.52、22564.52元。两笔合计扣减1300元；账单中分别有一条与各自操作对应的入账记录，其他账户余额未变。
- 两笔授权均已消耗，关联工作流与资金操作均成功；审计各有一次服务提交与一条账本记录。这证明本次两笔各执行一次，没有额外进行重复点击或失败重试的幂等压力演示。
- 参考号及其标签从展示素材中移除，原始截图与审计证据保留。回执画面保留金额、账户、收款人、备注、十步执行进度、授权/验证/最终业务状态及时间；重复风险块在前一镜头已经完整展示。
- 画面从同一状态的重叠原生截图组装，浮动导航控件不进入卡片；未重绘任何金融文字。正文画面固定停留，提问保留聚焦动画，图片和投影在底部分隔线上方。
- 所有业务发生在已有的本地Mock银行演示环境，没有真实资金、真实银行清算或第三方支付。

## 交付文件

- `BAVA-transfers-70s-silent.mp4`：本段独立视频。
- `BAVA-preview-165s-silent.mp4`：前95秒使用第三部分v8连续成片，原样拼接第四部分，共2分45秒。
- `BAVA-transfers.srt`：本段00:00–01:10字幕时间轴。
- `BAVA-00-165.srt`：整段00:00–02:45字幕，前95秒沿用原稿。
- `产品讲解稿_00-165.md`：截至第四部分的完整时间码文案。
- `evidence/verification.json`：32项业务事实核验。
- `verification.json`：成片时长、音轨、解码、画面边界与前段保留核验。
- `source/`、`prepared/`：原始UI截图/DOM/位置记录、同状态组装卡片和来源映射。

视频没有内嵌讲解字幕；SRT为可编辑的后期素材。
"""
    (ROOT / "智能转账文案与时间轴.md").write_text(text)
    full = ["# BAVA 产品讲解稿 00:00–02:45", "", "前95秒文案保持原样；新增第四部分智能转账70秒。视频无旁白、无内嵌讲解字幕。", "", "| 时间 | 建议讲解文案 |", "|---|---|"]
    full += [f"| {short(c['start'])}–{short(c['end'])} | {c['text']} |" for c in combined]
    (ROOT / "产品讲解稿_00-165.md").write_text("\n".join(full) + "\n")
    for c in CUES:
        rate = len(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", c["text"])) / (c["end"] - c["start"])
        print(f"{short(c['start'])}–{short(c['end'])}: {rate:.2f} characters/s | {c['text']}")


if __name__ == "__main__":
    main()
