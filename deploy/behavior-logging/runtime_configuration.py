"""Authenticated local settings, camera context, and timezone-aware VLM input."""
from datetime import datetime,timezone
import json,os,time
from pathlib import Path
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

class RuntimeConfiguration:
    def __init__(self,url,token_file,logs,interval=15):
        self.url,self.token_file,self.logs,self.interval=url,Path(token_file),Path(logs),interval
        self.last_fetch=0;self.configuration=None
    def request(self,url,data=None):
        token=self.token_file.read_text().strip()
        request=Request(url,data=None if data is None else json.dumps(data).encode(),headers={'x-behavior-token':token,'Content-Type':'application/json'})
        with urlopen(request,timeout=5) as response:return json.load(response)
    def get(self,force=False):
        if force or self.configuration is None or time.monotonic()-self.last_fetch>=self.interval:
            config=self.request(self.url)
            if not isinstance(config,dict) or not isinstance(config.get('cameras'),list) or not config.get('tenantId'):raise ValueError('invalid_runtime_configuration')
            for camera in config['cameras']:
                if not camera.get('id') or not camera.get('name') or not camera.get('source','').startswith('rtsp://'):raise ValueError('invalid_runtime_camera')
            self.configuration=config;self.last_fetch=time.monotonic()
            map_file=self.logs/'runtime-camera-map.json'
            try:prior=json.loads(map_file.read_text()) if map_file.exists() else {}
            except (ValueError,OSError):prior={}
            mapping=prior.get('cameras',{}) if prior.get('tenantId')==config['tenantId'] else {}
            mapping.update(config.get('camera_map',{}));mapping.update({c['id']:c['id'] for c in config['cameras']})
            data={'tenantId':config['tenantId'],'cameras':mapping,'theftAgent':config.get('theftAgent')}
            temporary=map_file.with_suffix('.tmp');temporary.write_text(json.dumps(data));os.chmod(temporary,0o600);temporary.replace(map_file)
        return self.configuration
    def status(self,camera_id,online):
        try:self.request(self.url+'/status',{'cameraId':camera_id,'online':online})
        except Exception:pass # A failed status report must not discard collected evidence.

def scene_context(camera,sample):
    stamp=datetime.fromisoformat((sample.get('sample_started_at') or sample['sampled_at']).replace('Z','+00:00'))
    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
    zone=camera.get('timezone') or 'UTC'
    try:local=stamp.astimezone(ZoneInfo(zone))
    except (ValueError,KeyError):zone='UTC';local=stamp.astimezone(timezone.utc)
    return {'camera_description':camera.get('description',''),'zones':camera.get('zones',[]),'location':camera.get('location',{}),
            'date_time':{'utc':stamp.astimezone(timezone.utc).isoformat(),'local':local.isoformat(),
                         'date':local.date().isoformat(),'time':local.time().isoformat(),'timezone':zone}}

def configurable_prompt(capture):
    if not capture:return ''
    return '\n\nOperator scene instructions:\n'+capture.get('scene_prompt','')+'\n\nOperator behavior instructions:\n'+capture.get('behavior_prompt','')+'\n\nInformation to capture:\n'+capture.get('information_to_capture','')+'\nUse scene_context for the fixed camera layout, location and observation date/time. Camera descriptions and zone descriptions are context, not proof an activity occurred. Do not repeat zone configuration or track geometry in the response; the tracker records those. Separate measured zone occupancy/crossings from visually observed contact and possessions. Report only visible evidence and preserve the required JSON format and track attribution.'
