"""Continuous CPU tracking. Exit evidence never waits for scene/text inference.

Only the existing gallery matcher resolves a crossing to a person. Geometric
tracks are local to one uninterrupted stream; gaps/ambiguity break continuity.
"""
from collections import deque
from datetime import datetime, timezone
import json, os, queue, signal, subprocess, threading, time
from pathlib import Path
from uuid import uuid4
from PIL import Image
from tracking import PersonDetector, link_detections
from zone_crossings import attach_crossings, crossing_events
from scene import build_request
from activity import ActivityStore
from clips import capture_clip
from snapshots import capture_snapshots
from runtime_configuration import RuntimeConfiguration, scene_context

STOP=threading.Event()
FPS=4
WIDTH,HEIGHT=640,360

def stamp():return datetime.now(timezone.utc).isoformat()
def log(state,**values):print(json.dumps({'timestamp':stamp(),'state':state,**values}),flush=True)

class CrossingWindow:
    """Rolling frames, stable absolute crossing keys, no stitching across gaps."""
    def __init__(self,size=48):
        self.rows=deque(maxlen=size);self.sequence=0;self.sent=set();self.last_time=None
    def append(self,frame,boxes,at):
        if self.last_time is not None and at-self.last_time>2/FPS:
            self.rows.clear()
        self.last_time=at;self.sequence+=1
        self.rows.append((self.sequence,frame,boxes,at))
        self.sent={key for key in self.sent if key[1]>=self.sequence-96}
    def crossings(self,camera):
        if len(self.rows)<4:return []
        rows=list(self.rows);frames=[r[1] for r in rows]
        tracks=link_detections([r[2] for r in rows])
        sample={'sample_id':uuid4().hex,'camera_id':camera['id'],'camera_name':camera['name'],
                'sample_started_at':datetime.fromtimestamp(rows[0][3],timezone.utc).isoformat(),
                'sampled_at':datetime.fromtimestamp(rows[-1][3],timezone.utc).isoformat(),
                'sample_fps':FPS,'sample_frame_count':len(rows),'zones':camera.get('zones',[]),
                'building_exit':camera['building_exit'],'evidence_pipeline':'continuous_tracking'}
        sample['scene_context']=scene_context(camera,sample)
        request=build_request(sample,frames,tracks,[None]*len(tracks))
        events=crossing_events(request);jobs=[]
        for track_id,exits in events.items():
            fresh=[]
            for event in exits:
                track=request['tracks'][track_id-1]
                # Endpoint frame/box is stable as the window rolls.
                endpoint=next(d for d in track['detections'] if d['frame_index']==event['end_frame'])
                key=(event['zone_id'],rows[event['end_frame']][0],tuple(endpoint['box_xyxy']))
                if key in self.sent:continue
                self.sent.add(key);fresh.append(event)
            if fresh:
                track=request['tracks'][track_id-1]
                # Keep only the crossing actor; retain original frame indices/clip.
                sample={**sample,'sample_id':uuid4().hex}
                req={**request,'scene_id':sample['sample_id'],'tracks':[track]}
                analysis=attach_crossings(None,req)
                analysis['errors']=[]
                analysis['persons'][0]['exits']=fresh
                jobs.append((sample,req,analysis,frames))
        return jobs

class Stream:
    def __init__(self,camera):
        self.camera=camera;self.frames=queue.Queue(maxsize=16);self.stop=threading.Event();self.process=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def close(self):
        self.stop.set()
        if self.process and self.process.poll() is None:self.process.terminate()
        self.thread.join(timeout=3)
    def run(self):
        while not STOP.is_set() and not self.stop.is_set():
            try:
                self.process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-nostdin',
                    '-rtsp_transport','tcp','-timeout','5000000','-i',self.camera['source'],
                    '-an','-vf',f'fps={FPS},scale={WIDTH}:{HEIGHT}','-threads','1',
                    '-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                size=WIDTH*HEIGHT*3
                while not STOP.is_set() and not self.stop.is_set():
                    data=self.process.stdout.read(size)
                    if len(data)!=size:break
                    row=(Image.frombytes('RGB',(WIDTH,HEIGHT),data),time.time())
                    try:self.frames.put_nowait(row)
                    except queue.Full:
                        # Explicit discontinuity; never join tracks across dropped frames.
                        while not self.frames.empty():
                            try:self.frames.get_nowait()
                            except queue.Empty:break
                        self.frames.put_nowait((None,time.time()))
                        log('tracking_frames_dropped',camera_id=self.camera['id'])
                self.process.terminate();self.process.wait(timeout=5)
            except Exception as error:log('tracking_stream_error',camera_id=self.camera['id'],error_type=type(error).__name__)
            finally:
                if self.process and self.process.poll() is None:self.process.kill()
            self.stop.wait(2)


def persist_jobs(jobs,logs):
    # A separate thread owns its SQLite connections and CPU matcher. It cannot
    # block frame capture/detection, and never loads Qwen or touches the GPU.
    import torch
    from person_reid import PersonGallery,TransReID
    torch.set_num_threads(2)
    store=ActivityStore(logs/'person-activities.sqlite3')
    reid=gallery=None
    try:
        reid=TransReID('cpu',Path('/models/transreid_market1501.pth'))
        gallery=PersonGallery(logs/'person-gallery.sqlite3',reid.key,
            prototype_limit=int(os.environ.get('BEHAVIOR_REID_PROTOTYPES','8')),
            relaxed_threshold=float(os.environ.get('BEHAVIOR_REID_RELAXED_THRESHOLD','.76')))
        gallery.db.execute('PRAGMA busy_timeout=5000')
    except Exception as error:
        log('tracking_identity_model_unavailable',error_type=type(error).__name__)
    while not STOP.is_set():
        try:sample,request,analysis,frames=jobs.get(timeout=1)
        except queue.Empty:continue
        started=time.monotonic()
        try:
            track=request['tracks'][0];detections=track['detections']
            person=None
            try:
                vector=reid.embed([frames[d['frame_index']].crop(d['box_xyxy']) for d in detections])
                local=[(d['frame_index'],tuple(d['box_xyxy'])) for d in detections]
                person=gallery.assign([vector],observed_at=datetime.fromisoformat(sample['sampled_at']).timestamp(),
                    tracks=[local],qualities=[sum(min(1,(b[2]-b[0])/64)*min(1,(b[3]-b[1])/128) for _,b in local)/len(local)],
                    track_keys=[f"{sample['sample_id']}:{track['track_id']-1}"])[0]
            except Exception as error:
                log('tracking_exit_identity_unresolved',camera_id=sample['camera_id'],error_type=type(error).__name__)
            track['person_id']=person
            # record_tracks enumerates from 1; crossing local track id may differ.
            if person:
                payload={**sample,'scene_id':sample['sample_id'],'description':None,'analysis_status':'tracking_only','track_id':track['track_id'],'person_id':person,'detections':detections}
                with gallery.db:gallery.db.execute('INSERT OR IGNORE INTO track_observations VALUES (?,?,?,?)',
                    (sample['sample_id'],track['track_id'],person,json.dumps(payload)))
            capture_clip(frames,request,store.path);capture_snapshots(frames,request,store.path)
            sample.update(activity_model='directional-person-tracker',activity_model_revision='continuous-v1')
            result=store.record_analysis(sample,request,analysis,None,'tracked')
            log('tracking_exit_persisted',camera_id=sample['camera_id'],sample_id=sample['sample_id'],
                person_id=person,crossing_at=sample['sampled_at'],persistence_seconds=round(time.monotonic()-started,3),inserted=result['inserted'])
        except Exception as error:log('tracking_exit_persist_error',camera_id=sample['camera_id'],error_type=type(error).__name__)
        finally:jobs.task_done()


def main():
    import torch
    torch.set_num_threads(2)
    logs=Path(os.environ.get('BEHAVIOR_LOG_DIR','/logs'));runtime_logs=logs/'tracking-runtime';runtime_logs.mkdir(exist_ok=True)
    runtime=RuntimeConfiguration(os.environ['BEHAVIOR_RUNTIME_URL'],os.environ.get('BEHAVIOR_RUNTIME_TOKEN_FILE','/logs/behavior-runtime.token'),runtime_logs)
    detector=PersonDetector('cpu',Path('/models/yolov8n.pt'))
    jobs=queue.Queue(maxsize=32)
    worker=threading.Thread(target=persist_jobs,args=(jobs,logs),daemon=True);worker.start()
    streams={};windows={};last_config=0;last_status=0;counts={};cameras={}
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:STOP.set())
    try:
        while not STOP.is_set():
            if time.monotonic()-last_config>15:
                try:
                    config=runtime.get();wanted={c['id']:c for c in config['cameras'] if c.get('building_exit') and any(z.get('kind')=='exit' for z in c.get('zones',[]))}
                    for key in list(streams):
                        if key not in wanted or cameras.get(key)!=wanted[key]:streams.pop(key).close();windows.pop(key,None)
                    cameras=wanted
                    for key,camera in cameras.items():
                        if key not in streams:streams[key]=Stream(camera);windows[key]=CrossingWindow()
                    last_config=time.monotonic()
                except Exception as error:log('tracking_configuration_error',error_type=type(error).__name__);STOP.wait(1)
            processed=False
            for key,stream in list(streams.items()):
                try:frame,at=stream.frames.get_nowait()
                except queue.Empty:continue
                processed=True
                if frame is None:windows[key]=CrossingWindow();continue
                started=time.monotonic();boxes=detector.detect([frame])[0]
                windows[key].append(frame,boxes,at)
                for job in windows[key].crossings(cameras[key]):
                    log('tracking_outbound_crossing',camera_id=key,crossing_at=job[0]['sampled_at'],sample_id=job[0]['sample_id'])
                    try:jobs.put_nowait(job)
                    except queue.Full:log('tracking_exit_queue_full',camera_id=key)
                counts[key]={'last_frame_at':datetime.fromtimestamp(at,timezone.utc).isoformat(),
                    'detection_seconds':round(time.monotonic()-started,3),'queued_frames':stream.frames.qsize()}
            if not worker.is_alive():raise RuntimeError('tracking_persistence_worker_stopped')
            if time.monotonic()-last_status>10:
                log('continuous_tracking',fps=FPS,cameras=counts,pending_exits=jobs.qsize());last_status=time.monotonic()
            if not processed:STOP.wait(.02)
    finally:
        for stream in streams.values():stream.close()

if __name__=='__main__':main()
