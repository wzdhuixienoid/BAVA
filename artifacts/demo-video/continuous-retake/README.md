# BAVA 连续演示版

成片：`BAVA-demo-continuous-silent.mp4`。04:44.2，1920×1080，30 fps，静音，无内嵌讲解字幕。

本版从头重新录制，账单分析、订阅管理、100元转账、带条件的1200元转账均在同一个“BAVA 银行服务演示”对话、同一套Mock数据中依次完成。报告、历史消息、取消回执和转账回执逐步累积，全程没有新建业务对话或重置数据。

产品画面保留四角24px圆角。提问聚焦来自同一时刻的真实输入框，其他镜头固定构图。保留导航、滚动、确认、验证、提交、回执和独立查账，剪去静止等待；插件浮层已在新录制画面中移除。

- `产品讲解稿与时间轴.md`：逐段文案、场景衔接及录制说明。
- `BAVA-demo-continuous.srt`：后期字幕文件。
- `business-verification.json`：同一对话、历史消息ID完整保留、数据连续、权限门禁、唯一执行等34项事实核验。
- `media-verification.json`：成片格式、完整解码、动态动作、圆角、插件图标及参考号检查。
- `edit-decision-list.json`：成片与四段原生录像的映射；四段录像在同一个实时会话内顺序录制。
- `raw/`、`evidence/`、`events.json`、`recordings.json`：原生录像、逐阶段API证据和实际动作时间。

重建：在具备Pillow、NumPy、OpenCV的Python环境中运行make_shots.py、build_video.py、write_narration.py、verify_business.py、verify_media.py。FFmpeg、中文字体和本机离线Vision检查器路径见脚本。

所有账户、商户与资金操作属于独立Mock环境，身份验证为Mock门禁；原localhost:3000服务及此前交付录像未修改。
