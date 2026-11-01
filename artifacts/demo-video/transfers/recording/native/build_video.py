"""Edit the native ScreenCaptureKit video. No screenshot sequences are used."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFilter

ROOT=Path(__file__).resolve().parent
VIDEO_ROOT=ROOT.parents[2]
spec=importlib.util.spec_from_file_location('brand',VIDEO_ROOT/'opening/build_opening.py')
brand=importlib.util.module_from_spec(spec);spec.loader.exec_module(brand)
FF=brand.FFMPEG
RAW=ROOT/'BAVA-part4-native-raw.mp4'
FPS=30
BOX=(170,112,1580,856)
# Each interval contains native screen frames. Gaps remove static waits and
# the rehearsal of plan controls; confirmation, verification and commit stay ordered.
EDL=[
 ('01-request',22.05,27.0,'从工资卡给李小雨转100元，备注餐费',3.282),
 ('02-yellow-review',42.25,49.2,None,None),
 ('03-yellow-success',62.65,68.85,None,None),
 ('04-yellow-ledger',121.7,128.6,None,None),
 ('05-condition-request',143.8,151.8,'查工资卡余额，如果余额不少于3000元，给张三转1200元',4.412),
 ('06-condition-execution',158.0,163.0,None,None),
 ('07-complete-dag',213.0,217.1,None,None),
 ('08-manual-takeover',303.0,306.3,None,None),
 ('09-resume-plan',315.6,320.2,None,None),
 ('10-payee',335.6,339.6,None,None),
 ('11-red-review',352.0,363.5,None,None),
 ('12-mock-verification',381.0,387.5,None,None),
 ('13-red-success',431.4,439.8,None,None),
 ('14-final-ledger',451.4,461.0,None,None),
]
assert round(sum(b-a for _,a,b,_,_ in EDL),5)==90
FRAME_COUNTS={};frame_cursor=0;time_cursor=0
for name,a,b,_,_ in EDL:
 time_cursor+=b-a;target=round(time_cursor*FPS);FRAME_COUNTS[name]=target-frame_cursor;frame_cursor=target
CLIPS=ROOT/'clips';CLIPS.mkdir(exist_ok=True)
SHELL=ROOT/'brand-shell.png';brand.SHELL.save(SHELL)

def encoder(path):
 return ['-an','-r','30','-fps_mode','cfr','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-video_track_timescale','15360','-movflags','+faststart',str(path)]

def ease(t):
 t=max(0.,min(1.,t));return t*t*(3-2*t)

def question(shot):
 name,start,end,_,send=shot;nframes=FRAME_COUNTS[name]
 dec=subprocess.Popen([FF,'-hide_banner','-loglevel','error','-ss',str(start),'-i',str(RAW),'-vf','fps=fps=30:start_time=0,scale=1580:856:flags=lanczos','-frames:v',str(nframes),'-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE)
 enc=subprocess.Popen([FF,'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','pipe:0',*encoder(CLIPS/(name+'.mp4'))],stdin=subprocess.PIPE)
 for n in range(nframes):
  pixels=dec.stdout.read(1580*856*3)
  if len(pixels)!=1580*856*3:raise RuntimeError(f'Short native input: {name} {n}')
  ui=Image.frombytes('RGB',(1580,856),pixels)
  base=brand.SHELL.copy();base.paste(ui,(170,112))
  q=ease((n/FPS-.3)/.45)*(1-ease((n/FPS-(send-.5))/.45))
  if q>0:
   # The enlarged textbox is a crop of this same live frame, including each
   # actual keystroke. The camera eases once in and once out before sending.
   detail=ui.crop((round(270*1580/1504),round(741*856/815),round(1410*1580/1504),round(807*856/815)))
   dw=detail.width+(1470-detail.width)*q;dh=detail.height*dw/detail.width
   ox=170+270*1580/1504;oy=112+741*856/815
   x=ox+(225-ox)*q;y=oy+(635-oy)*q
   blurred=base.filter(ImageFilter.GaussianBlur(1.8*q))
   base=Image.blend(blurred,Image.new('RGB',(1920,1080),(7,16,29)),.25*q)
   base.paste(brand.SHELL.crop((0,0,1920,100)),(0,0))
   base.paste(brand.SHELL.crop((0,970,1920,1080)),(0,970))
   shadow=Image.new('RGBA',(1920,1080));ImageDraw.Draw(shadow).rounded_rectangle((x-8,y-8,x+dw+8,y+dh+8),radius=18,fill=(8,20,31,round(210*q)))
   shadow=shadow.filter(ImageFilter.GaussianBlur(15));base.paste(shadow,(0,0),shadow)
   detail=detail.resize((round(dw),round(dh)),Image.Resampling.LANCZOS)
   mask=Image.new('L',detail.size);ImageDraw.Draw(mask).rounded_rectangle((0,0,detail.width-1,detail.height-1),radius=13,fill=255)
   base.paste(detail,(round(x),round(y)),mask)
   base.paste(brand.SHELL.crop((0,970,1920,1080)),(0,970))
  enc.stdin.write(base.tobytes())
 enc.stdin.close();dec.stdout.close()
 if dec.wait()!=0 or enc.wait()!=0:raise RuntimeError(name)
 return name

def normal(shot):
 name,start,end,_,_=shot
 graph='[1:v]fps=fps=30:start_time=0,tpad=stop_mode=clone:stop_duration=2,scale=1580:856:flags=lanczos,setsar=1[ui];[0:v][ui]overlay=170:112:shortest=1,format=yuv420p[out]'
 subprocess.run([FF,'-hide_banner','-loglevel','error','-y','-loop','1','-framerate','30','-i',str(SHELL),'-ss',str(start),'-i',str(RAW),'-filter_complex',graph,'-map','[out]','-frames:v',str(FRAME_COUNTS[name]),*encoder(CLIPS/(name+'.mp4'))],check=True)
 return name

def main():
 # Two encoders keep memory bounded. All input operations were completed in
 # the single, uninterrupted raw movie before this edit starts.
 with ThreadPoolExecutor(max_workers=2) as pool:
  for name in pool.map(lambda shot:question(shot) if shot[3] else normal(shot),EDL):print('Rendered',name,flush=True)
 concat=ROOT/'concat.txt';concat.write_text(''.join("file '"+str(CLIPS/(s[0]+'.mp4'))+"'\n" for s in EDL))
 output=ROOT/'BAVA-part4-90s-native-recording.mp4'
 subprocess.run([FF,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(output)],check=True)
 combined=ROOT/'BAVA-preview-185s-native-recording.mp4'
 concat.write_text("file '"+str(VIDEO_ROOT/'subscriptions/BAVA-preview-95s-stable-v8.mp4')+"'\nfile '"+str(output)+"'\n")
 subprocess.run([FF,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(combined)],check=True)
 cursor=0;edl=[]
 for name,a,b,prompt,_ in EDL:
  edl.append({'name':name,'raw_start':a,'raw_end':b,'start':round(cursor,3),'end':round(cursor+b-a,3),'prompt':prompt});cursor+=b-a
 (ROOT/'edit-decision-list.json').write_text(json.dumps(edl,ensure_ascii=False,indent=2))
 print(output,flush=True)

if __name__=='__main__':main()
