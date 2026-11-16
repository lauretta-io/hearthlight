import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
from runtime_configuration import RuntimeConfiguration,scene_context
from activity import ActivityStore
from runner import analyze_sample

class RuntimeTests(unittest.TestCase):
 def test_local_date_timezone_and_location_are_part_of_actual_model_input(self):
  sample={'sample_id':'sample','sampled_at':'2026-11-14T00:31:00+00:00','sample_started_at':'2026-11-14T00:30:00+00:00','sample_fps':2,'camera_id':'camera','camera_name':'Office'}
  camera={'description':'Desk and bright exit','timezone':'America/Chicago','location':{'site':'Office','floor':'First','detail':'Workroom'},'source':'rtsp://secret:password@camera/stream'}
  sample['scene_context']=scene_context(camera,sample)
  sample['capture_settings']={'scene_prompt':'Explain visible objects','behavior_prompt':'Report pickup transitions','information_to_capture':'Blue bags and people interactions'}
  models=Mock();models.vlm_id='test';models.revisions={'test':'revision'};models.visual_matches.return_value=[];models.describe.return_value=json.dumps({'scene_description':'Empty workroom','persons':[]})
  with tempfile.TemporaryDirectory() as root:
   store=ActivityStore(Path(root)/'activities.sqlite3')
   result=analyze_sample(None,models,[Image.new('RGB',(100,100)),Image.new('RGB',(100,100))],sample,store,Mock())
   context=result['scene']['input_request']['scene_context'];self.assertEqual(context['date_time']['date'],'2026-11-13');self.assertEqual(context['date_time']['time'],'18:30:00');self.assertEqual(context['date_time']['timezone'],'America/Chicago');self.assertEqual(context['location']['detail'],'Workroom')
   prompt=models.describe.call_args.args[1];self.assertIn('Explain visible objects',prompt);self.assertIn('Report pickup transitions',prompt);self.assertIn('Blue bags and people interactions',prompt);self.assertIn('Desk and bright exit',prompt);self.assertNotIn('secret:password',prompt)
 def test_runtime_refresh_removes_cameras_and_never_saves_credentials_to_mapping(self):
  with tempfile.TemporaryDirectory() as root:
   path=Path(root);(path/'token').write_text('a'*64)
   client=RuntimeConfiguration('http://local/runtime',path/'token',path,interval=15)
   config={'tenantId':'tenant','cameras':[{'id':'camera','name':'Office','source':'rtsp://secret:password@host/path'}],'camera_map':{'camera':'camera'},'theftAgent':None}
   with patch('runtime_configuration.urlopen',return_value=io.BytesIO(json.dumps(config).encode())) as call:
    self.assertEqual(len(client.get()['cameras']),1);self.assertEqual(len(client.get()['cameras']),1);self.assertEqual(call.call_count,1)
    request=call.call_args.args[0];self.assertEqual(request.get_header('X-behavior-token'),'a'*64)
   saved=(path/'runtime-camera-map.json').read_text();self.assertNotIn('password',saved);self.assertNotIn('rtsp',saved)
   config['cameras']=[]
   with patch('runtime_configuration.urlopen',return_value=io.BytesIO(json.dumps(config).encode())):self.assertEqual(client.get(force=True)['cameras'],[])
   self.assertEqual(json.loads((path/'runtime-camera-map.json').read_text())['cameras'],{'camera':'camera'})
 def test_unavailable_runtime_does_not_silently_reuse_an_expired_camera_list(self):
  with tempfile.TemporaryDirectory() as root:
   path=Path(root);(path/'token').write_text('a'*64);client=RuntimeConfiguration('http://local/runtime',path/'token',path)
   client.configuration={'cameras':[{'id':'removed'}]};client.last_fetch=-100
   with patch('runtime_configuration.urlopen',side_effect=OSError('unavailable')):
    with self.assertRaises(OSError):client.get()
    with self.assertRaises(OSError):client.get()
