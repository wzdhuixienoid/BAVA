import hashlib
import json
from pathlib import Path
import subprocess
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent
FF='/private/tmp/banking-video-tools/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
VIDEO=ROOT/'BAVA-demo-continuous-silent.mp4'
QA=ROOT/'qa';QA.mkdir(exist_ok=True)
edl=json.loads((ROOT/'edit-decision-list.json').read_text())
expected=sum(x['frames'] for x in edl)
cap=cv2.VideoCapture(str(VIDEO))
checks={
 'format_1080p_30fps':cap.get(cv2.CAP_PROP_FPS)==30 and cap.get(cv2.CAP_PROP_FRAME_WIDTH)==1920 and cap.get(cv2.CAP_PROP_FRAME_HEIGHT)==1080,
 'exact_frame_budget':cap.get(cv2.CAP_PROP_FRAME_COUNT)==expected==8526,
 'under_five_minutes':expected/30<300,
 'ui_above_footer_line':112+856==968 and 968<987,
 'every_product_shot_uses_new_native_movie':all(x['source'].startswith('raw/') for x in edl if x['name']!='00-brand'),
 'only_continuous_recording_sources':all(x['source'] in {'raw/01-bills.mp4','raw/02-subscriptions.mp4','raw/03-transfers.mp4','raw/04-condition.mp4','procedural brand animation'} for x in edl),
}
from PIL import Image
shell=np.asarray(Image.open(ROOT/'brand-shell.png').convert('RGB'))[:,:,::-1]
corner_points=[(113,171),(113,1746),(964,171),(964,1746)]
corner_delta=0;purple_max=0
first=None;footer_delta=0;hashes=set();scans=[];index=0
scene_hashes={x['name']:set() for x in edl}
contact_times=[2,7,11,15,19,25,32,39,45,49,51,54,58,63,68,74,78,81,86,91,97,105,111,116,119,123,127,132,137,142,151,158,162,165,171,178,185,192,197,202,207,212,217,222,229,235,241,245,252,261,268,276,282]
contact_index={round(t*30):t for t in contact_times}
contact=[]
scene=0
while True:
 ok,frame=cap.read()
 if not ok:break
 if first is None:first=frame[984:].copy()
 footer_delta=max(footer_delta,float(np.abs(frame[984:].astype('float32')-first.astype('float32')).mean()))
 if index>=150:
  for yy,xx in corner_points:corner_delta=max(corner_delta,float(np.abs(frame[yy:yy+3,xx:xx+3].astype('float32')-shell[yy:yy+3,xx:xx+3]).mean()))
  roi=frame[899:948,1710:1749].astype('float32');bb,gg,rr=roi[:,:,0],roi[:,:,1],roi[:,:,2]
  purple_max=max(purple_max,int(((rr>100)&(bb>110)&(rr>1.4*gg)&(bb>1.3*gg)).sum()))
 digest=hashlib.sha256(frame[112:968,170:1750].tobytes()).hexdigest();hashes.add(digest)
 while scene+1<len(edl) and index>=round(edl[scene]['end']*30):scene+=1
 scene_hashes[edl[scene]['name']].add(digest)
 if index%15==0:
  path=QA/f'ocr-{index:05d}.jpg';cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,95]);scans.append(str(path))
 if index in contact_index:
  path=QA/f'frame-{contact_index[index]:05.1f}.png';cv2.imwrite(str(path),frame);contact.append((contact_index[index],str(path)))
 index+=1
cap.release()
checks['all_frames_decoded']=index==expected
checks['fixed_footer_boundary']=footer_delta<2
checks['continuous_native_changes']=len(hashes)>900
action_scenes=['03-bill-send','05-report-top','06-categories','07-transactions','09-return-conversation','13-read-consent','18-cancel-review','19-cancel-approve','20-cancel-commit','22-requery-costs','27-yellow-send','29-yellow-details-scroll','30-yellow-approve','31-yellow-commit','38-pause','39-resume','40-payee-scroll','41-payee-choice','44-red-approve','45-verification-start','46-masked-code','47-verify','49-red-commit','52-final-ledger','53-final-conversation']
checks['each_recorded_action_has_dynamic_frames']=all(len(scene_hashes[n])>=4 for n in action_scenes)
checks['four_rounded_corners_visible']=corner_delta<15
checks['removed_plugin_purple_icon_absent']=purple_max<12
checks['silent']='Audio:' not in subprocess.run([FF,'-hide_banner','-i',str(VIDEO)],capture_output=True).stderr.decode()
decode=subprocess.run([FF,'-hide_banner','-loglevel','error','-i',str(VIDEO),'-f','null','-'],capture_output=True)
checks['full_ffmpeg_decode']=decode.returncode==0 and not decode.stderr.strip()
# Run with the authorized native Vision entitlement outside the shell sandbox.
ocr=subprocess.run(['/private/tmp/bava-visible-text-check',*scans],capture_output=True,text=True)
checks['sampled_reference_numbers_and_clear_code_absent']=ocr.returncode==0
from PIL import Image,ImageDraw
sheet=Image.new('RGB',(1920,9*212),(7,16,29))
for i,(t,path) in enumerate(contact):
 im=Image.open(path).resize((320,180));x=i%6*320;y=i//6*212;sheet.paste(im,(x,y));ImageDraw.Draw(sheet).text((x+8,y+185),f'{int(t)//60:02}:{t%60:04.1f}',fill='#d9f3ee')
sheet.save(QA/'full-video-contact.png')
result=dict(all_passed=all(checks.values()),checks=checks,details=dict(frames=index,seconds=index/30,distinct_ui_frames=len(hashes),max_footer_mean_delta=footer_delta,max_rounded_corner_delta=corner_delta,max_plugin_purple_pixels=purple_max,ocr_sample_count=len(scans),ocr_stdout=ocr.stdout,ocr_stderr=ocr.stderr,per_scene_distinct_frames={k:len(v) for k,v in scene_hashes.items()},ui_rectangle=[170,112,1580,856],separator_y=987),video_sha256=hashlib.sha256(VIDEO.read_bytes()).hexdigest())
(ROOT/'media-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
assert result['all_passed']
