import cv2
import hashlib
import json
import numpy as np
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
FF='/private/tmp/banking-video-tools/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
VIDEO=ROOT/'BAVA-part4-90s-native-recording.mp4'
QA=ROOT/'qa';QA.mkdir(exist_ok=True)
checks={};details={}
for name,nframes in [('BAVA-part4-90s-native-recording.mp4',2700),('BAVA-preview-185s-native-recording.mp4',5550)]:
 cap=cv2.VideoCapture(str(ROOT/name))
 checks[name+'_format']=cap.get(cv2.CAP_PROP_FPS)==30 and cap.get(cv2.CAP_PROP_FRAME_COUNT)==nframes and cap.get(cv2.CAP_PROP_FRAME_WIDTH)==1920 and cap.get(cv2.CAP_PROP_FRAME_HEIGHT)==1080
 cap.release()
 result=subprocess.run([FF,'-hide_banner','-loglevel','error','-i',str(ROOT/name),'-f','null','-'],capture_output=True)
 checks[name+'_full_decode']=result.returncode==0 and not result.stderr.strip()
 info=subprocess.run([FF,'-hide_banner','-i',str(ROOT/name)],capture_output=True).stderr.decode()
 checks[name+'_silent']='Audio:' not in info
cap=cv2.VideoCapture(str(VIDEO));footer=None;max_footer_delta=0;hashes=set();index=0;scan=[]
while True:
 ok,frame=cap.read()
 if not ok:break
 if footer is None:footer=frame[984:]
 max_footer_delta=max(max_footer_delta,float(np.abs(frame[984:].astype('float32')-footer.astype('float32')).mean()))
 hashes.add(hashlib.sha256(frame[112:968,170:1750].tobytes()).hexdigest())
 if index%15==0:
  path=QA/f'ocr-{index:04d}.jpg';cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,96]);scan.append(str(path))
 index+=1
cap.release()
checks['all_2700_frames_decoded']=index==2700
checks['footer_separator_stable']=max_footer_delta<2
checks['native_ui_has_continuous_changes']=len(hashes)>400
checks['ui_above_separator']=112+856==968 and 968<987
ocr=subprocess.run(['/private/tmp/bava-visible-text-check',*scan],capture_output=True,text=True)
checks['no_reference_number_or_clear_code_in_180_samples']=ocr.returncode==0
details.update({'decoded_frames':index,'distinct_ui_frames':len(hashes),'max_footer_mean_delta':max_footer_delta,'ocr_result':ocr.stdout,'ocr_error':ocr.stderr,'ui_rectangle':[170,112,1580,856],'separator_y':987})
result={'all_passed':all(checks.values()),'checks':checks,'details':details}
(ROOT/'media-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2));assert result['all_passed']
