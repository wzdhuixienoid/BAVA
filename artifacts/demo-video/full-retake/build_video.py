"""Edit genuine ScreenCaptureKit window movies; never synthesize business UI."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('brand', ROOT.parent/'opening/build_opening.py')
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
FF = brand.FFMPEG
FPS = 30
CLIPS = ROOT/'clips'
CLIPS.mkdir(exist_ok=True)
SHELL = ROOT/'brand-shell.png'
brand.SHELL.save(SHELL)

# Source times are checked against the native movies, not just automation logs.
# Static model waits and discarded recording takes are omitted. No confirmations
# or financial commits are rearranged within a business operation.
SHOTS = [
 ('00-brand',None,0,5,None,None,'开场'),
 ('01-accounts','01-03-native',36,40,None,None,'开场'),
 ('02-bill-question','01-03-native',40.8,46.8,'分析2026年8月消费，生成报告',3.432,'开场'),
 ('03-bill-report','01-03-native',71,111,None,None,'账单分析'),
 ('04-sub-question','01-03-native',112.7,118,'我有哪些订阅？',2.797,'订阅管理'),
 ('05-sub-consent','01-03-native',130.5,134.5,None,None,'订阅管理'),
 ('06-sub-fees','01-03-native',149,154,None,None,'订阅管理'),
 ('07-sub-table','01-03-native',157,164,None,None,'订阅管理'),
 ('08-sub-cancel-question','01-03-native',164,168.5,'取消星幕视频',2.673,'订阅管理'),
 ('09-sub-approve','01-03-native',181,187,None,None,'订阅管理'),
 ('10-sub-commit','03-04-native',11.8,19,None,None,'订阅管理'),
 ('11-sub-requery','03-04-native',43,52,None,None,'订阅管理'),
 ('12-sub-cancelled','03-04-native',67.5,73.5,None,None,'订阅管理'),
 ('13-yellow-question','06-yellow-final',6.7,12.7,'从工资卡给李小雨转100元，备注餐费',2.605,'智能转账'),
 ('14-yellow-risk','06-yellow-final',41.8,47.8,None,None,'智能转账'),
 ('15-yellow-approve','06-yellow-final',64.5,71.5,None,None,'智能转账'),
 ('16-yellow-commit','06-yellow-final',80.9,90.9,None,None,'智能转账'),
 ('17-yellow-balance','06-yellow-final',99.6,106.6,None,None,'智能转账'),
 ('18-condition-question','07b-dag-final',7.7,14.7,'查工资卡余额，如果余额不少于3000元，给张三转1200元',4.052,'智能转账'),
 ('19-condition-dag','07b-dag-final',65.4,73.4,None,None,'智能转账'),
 ('20-pause','07b-dag-final',80.5,86.5,None,None,'智能转账'),
 ('21-resume','07b-dag-final',98.3,103.3,None,None,'智能转账'),
 ('22-payee','07b-dag-final',137.5,144,None,None,'智能转账'),
 ('23-red-risk','08-verify-final',0,10,None,None,'智能转账'),
 ('24-red-approve','08-verify-final',16.7,22.7,None,None,'智能转账'),
 ('25-verification-start','08-verify-final',24,29,None,None,'智能转账'),
 ('26-verification','08-verify-final',44.8,50.8,None,None,'智能转账'),
 ('27-verified-unsubmitted','08-verify-final',59,63,None,None,'智能转账'),
 ('28-red-commit','08-verify-final',63,73,None,None,'智能转账'),
 ('29-completed-dag','08-verify-final',90,96,None,None,'智能转账'),
 ('30-final-balance','08-verify-final',117,124,None,None,'智能转账'),
 ('31-final-ledger','08-verify-final',145,153,None,None,'智能转账'),
]
COUNTS={}; frames=0; seconds=0
EDL=[]
for name,raw,a,b,prompt,send,section in SHOTS:
 seconds+=b-a; target=round(seconds*FPS); n=target-frames
 COUNTS[name]=n
 EDL.append(dict(name=name,section=section,source=('raw/'+raw+'.mp4') if raw else 'procedural brand animation',raw_start=a,raw_end=b,start=frames/FPS,end=target/FPS,frames=n,prompt=prompt))
 frames=target
(ROOT/'edit-decision-list.json').write_text(json.dumps(EDL,ensure_ascii=False,indent=2))

def encoder(path):
 return ['-an','-r','30','-fps_mode','cfr','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-video_track_timescale','15360','-movflags','+faststart',str(path)]

def native_filter(a,b):
 # Decode from the movie start before trimming. Seeking to a sparse VFR update
 # can otherwise replace a pre-click hold with a future, post-click frame.
 return f'fps=fps=30:start_time=0,trim=start={a}:end={b},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=2,scale=1580:856:flags=lanczos,setsar=1'

def ease(t):
 t=max(0.,min(1.,t));return t*t*(3-2*t)

def animated(shot):
 name,raw,a,b,prompt,send,_=shot;nframes=COUNTS[name]
 enc=subprocess.Popen([FF,'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','pipe:0',*encoder(CLIPS/(name+'.mp4'))],stdin=subprocess.PIPE)
 dec=None
 if raw:
  dec=subprocess.Popen([FF,'-hide_banner','-loglevel','error','-i',str(ROOT/'raw'/(raw+'.mp4')),'-vf',native_filter(a,b),'-frames:v',str(nframes),'-r','30','-fps_mode','cfr','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE)
 for n in range(nframes):
  t=n/FPS
  if not raw:
   base=brand.hero(t)
   base.paste(brand.SHELL.crop((0,970,1920,1080)),(0,970))
  else:
   size=1580*856*3
   chunks=[];received=0
   while received<size:
    chunk=dec.stdout.read(size-received)
    if not chunk:break
    chunks.append(chunk);received+=len(chunk)
   pixels=b''.join(chunks)
   if len(pixels)!=size:raise RuntimeError(f'Short native movie: {name} frame {n}, bytes {len(pixels)}, decoder {dec.poll()}')
   ui=Image.frombytes('RGB',(1580,856),pixels)
   base=brand.SHELL.copy();base.paste(ui,(170,112))
   q=ease((t-.3)/.45)*(1-ease((t-(send-.5))/.45))
   if q>0:
    detail=ui.crop((round(270*1580/1504),round(741*856/815),round(1410*1580/1504),round(807*856/815)))
    dw=detail.width+(1470-detail.width)*q;dh=detail.height*dw/detail.width
    ox=170+270*1580/1504;oy=112+741*856/815
    x=ox+(225-ox)*q;y=oy+(635-oy)*q
    base=Image.blend(base.filter(ImageFilter.GaussianBlur(1.8*q)),Image.new('RGB',(1920,1080),(7,16,29)),.25*q)
    base.paste(brand.SHELL.crop((0,0,1920,100)),(0,0))
    shadow=Image.new('RGBA',(1920,1080))
    ImageDraw.Draw(shadow).rounded_rectangle((x-8,y-8,x+dw+8,y+dh+8),radius=18,fill=(8,20,31,round(210*q)))
    shadow=shadow.filter(ImageFilter.GaussianBlur(15));base.paste(shadow,(0,0),shadow)
    detail=detail.resize((round(dw),round(dh)),Image.Resampling.LANCZOS)
    mask=Image.new('L',detail.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,detail.width-1,detail.height-1),radius=13,fill=255)
    base.paste(detail,(round(x),round(y)),mask)
    base.paste(brand.SHELL.crop((0,970,1920,1080)),(0,970))
  enc.stdin.write(base.tobytes())
 enc.stdin.close()
 if dec:
  dec.stdout.close()
  if dec.wait()!=0:raise RuntimeError(name+' decode failed')
 if enc.wait()!=0:raise RuntimeError(name+' encode failed')
 return name

def normal(shot):
 name,raw,a,b,_,_,_=shot
 graph=f'[1:v]{native_filter(a,b)}[ui];[0:v][ui]overlay=170:112:shortest=1,format=yuv420p[out]'
 subprocess.run([FF,'-hide_banner','-loglevel','error','-y','-loop','1','-framerate','30','-i',str(SHELL),'-i',str(ROOT/'raw'/(raw+'.mp4')),'-filter_complex',graph,'-map','[out]','-frames:v',str(COUNTS[name]),*encoder(CLIPS/(name+'.mp4'))],check=True)
 return name

def main():
 import cv2
 def render(shot):
  path=CLIPS/(shot[0]+'.mp4')
  if path.exists():
   cap=cv2.VideoCapture(str(path))
   good=cap.get(cv2.CAP_PROP_FPS)==FPS and cap.get(cv2.CAP_PROP_FRAME_COUNT)==COUNTS[shot[0]]
   cap.release()
   if good:return shot[0]+' (verified existing render)'
  return animated(shot) if shot[0]=='00-brand' or shot[4] else normal(shot)
 with ThreadPoolExecutor(max_workers=2) as pool:
  for result in pool.map(render,SHOTS):print('Rendered',result,flush=True)
 for shot in SHOTS:
  cap=cv2.VideoCapture(str(CLIPS/(shot[0]+'.mp4')))
  assert cap.get(cv2.CAP_PROP_FPS)==FPS and cap.get(cv2.CAP_PROP_FRAME_COUNT)==COUNTS[shot[0]],shot[0]
  cap.release()
 concat=ROOT/'concat.txt'
 concat.write_text(''.join("file '"+str(CLIPS/(s[0]+'.mp4'))+"'\n" for s in SHOTS))
 output=ROOT/'BAVA-demo-full-retake-silent.mp4'
 subprocess.run([FF,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(output)],check=True)
 print(json.dumps({'output':str(output),'seconds':frames/FPS,'frames':frames}),flush=True)

if __name__=='__main__':main()
