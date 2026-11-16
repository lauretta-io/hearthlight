"""Small model-facing temporal context; full geometry remains in stored evidence."""
from datetime import datetime,timedelta


def temporal_track(track,request):
    detections=track['detections'];fps=request['sample_fps']
    first,last=detections[0]['frame_index'],detections[-1]['frame_index']
    base=datetime.fromisoformat(request['sample_started_at'] or request['sampled_at'])
    width,height=request['frame_size']['width'],request['frame_size']['height']
    zones=[]
    for zone in request.get('zones',[]):
        l,t,r,b=zone['region'];inside=[]
        for d in detections:
            x1,y1,x2,y2=d['box_xyxy'];x,y=(x1+x2)/2/width,y2/height
            inside.append(l<=x<=r and t<=y<=b)
        if not any(inside):continue
        entered=[];exited=[]
        for i in range(1,len(inside)):
            if detections[i]['frame_index']-detections[i-1]['frame_index']>2:continue
            if inside[i] and not inside[i-1]:entered.append(detections[i]['frame_index']/fps)
            if not inside[i] and inside[i-1]:exited.append(detections[i]['frame_index']/fps)
        zones.append({'id':zone['id'],'name':zone['name'],'starts_inside':inside[0],
                      'ends_inside':inside[-1],'entered_at_seconds':entered,'exited_at_seconds':exited})
    return {'track_id':track['track_id'],'start_time':(base+timedelta(seconds=first/fps)).isoformat(),
            'end_time':(base+timedelta(seconds=last/fps)).isoformat(),
            'duration_seconds':round((last-first)/fps,3),'start_frame':first,'end_frame':last,
            'zones':zones}


def compact_context(context):
    if not context:return {}
    logs=[]
    for row in context.get('recent_logs',[])[-3:]:
        # events/interactions duplicate the four state-change arrays.
        changes={key:[{k:v for k,v in change.items() if k not in {'evidence','scene_id','camera_id'}}
                      for change in values] for key,values in row.get('state_changes',{}).items() if isinstance(values,list)}
        logs.append({'timestamp':row.get('timestamp'),'description':str(row.get('description') or '')[:240],
                     'changes':changes,'exits':row.get('exits',[])})
    return {'description':str(context.get('existing_person_description') or '')[:500],
            'interaction_states':context.get('interaction_states',{}),'possessions':context.get('possessions',{}),
            'recent_changes':logs}


def model_input(request,indices):
    tracks=[];catalog=[]
    for track in request['tracks']:
        selected=[d for d in track['detections'] if d['frame_index'] in indices]
        # Single-frame fragments cannot support a temporal behavior change.
        if len(selected)<2:continue
        short=temporal_track(track,request)
        if track.get('person_description'):short['person_description']=track['person_description']
        if track.get('behavior_context'):short['context']=compact_context(track['behavior_context'])
        if track.get('prior_state'):short['prior_state']=track['prior_state']
        tracks.append(short);catalog.append({**track,'detections':selected})
    payload={k:request[k] for k in ('camera_name','sample_started_at','sampled_at','sample_fps','scene_context','zones') if k in request}
    if 'scene_context' in payload:payload['scene_context']={k:v for k,v in payload['scene_context'].items() if k!='zones'}
    if 'zones' in payload:payload['zones']=[{k:v for k,v in z.items() if k not in {'region','entryGate','exitGate'}} for z in payload['zones']]
    payload.update(frame_indices=indices,tracks=tracks)
    return payload,{**request,'tracks':catalog}
