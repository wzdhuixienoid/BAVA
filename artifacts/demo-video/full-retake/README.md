# BAVA 全片原生重录

成片：`BAVA-demo-full-retake-silent.mp4`，03:59.5，1080p / 30 fps，静音，无内嵌讲解字幕。

包括目前完成的开场、账单分析、订阅管理、智能转账。产品画面均由本轮原生窗口录像剪辑而成，提问聚焦取自同一录像中的实时输入框。保留确认、强验证、提交、回执、暂停恢复和回查动作，剪去静止等待与未采用的取景。界面底边968，底部分隔线987。

- `产品讲解稿与时间轴.md`：逐段讲解文案、原始提问及录制说明。
- `BAVA-demo-full-retake.srt`：后期字幕文件。
- `edit-decision-list.json`：成片与原生录像映射。
- `business-verification.json`：31项模拟业务事实核验。
- `media-verification.json`：7185帧解码、格式、动态与边界检查；479帧离线OCR未发现参考号或明文验证码。
- `qa/full-video-contact.png`：关键画面总览。
- `raw/`、`evidence/`、`transfers-evidence/`：原生录像、业务与审计证据；包括保留的未采用取景。

复核与重建：使用已安装 Pillow、NumPy、OpenCV 的 Python，依次运行 `build_video.py`、`write_narration.py`、`verify_business.py`、`verify_media.py`。FFmpeg、中文字体和离线Vision检查器路径在脚本中；录制器源码为 `native_recorder.m`。

这是独立Mock环境演示，未进入真实银行清算网络；身份验证为Mock门禁。录制与重录的已知情况见讲解稿“剪辑与核验说明”。原 localhost:3000 服务和此前交付文件未修改。
