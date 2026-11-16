"""Conservative visual exit reports, tied to the configured doorway and track."""

def parse_exits(values, track, request, frames):
    config = request.get('building_exit')
    if not config:
        return []
    if not isinstance(values, list) or len(values) > 2:
        raise ValueError('invalid_exit_reports')
    output = []
    detections = {d['frame_index']:d for d in track['detections']}
    width,height = request['frame_size']['width'],request['frame_size']['height']
    x1,y1,x2,y2 = config['region']
    def inside(d):
        box=d['box_xyxy']
        return x1 <= (box[0]+box[2])/2/width <= x2 and y1 <= box[3]/height <= y2
    for row in values:
        if not isinstance(row,dict) or row.get('exit_id') != config['id'] or row.get('direction') != 'outbound' or row.get('certainty') != 'clear':
            continue
        a,b = row.get('start_frame'),row.get('end_frame')
        if type(a) is not int or type(b) is not int or a>=b or a not in detections or b not in detections:
            continue
        if inside(detections[a]) or not inside(detections[b]) or frames[a].tobytes() == frames[b].tobytes():
            continue
        evidence=row.get('evidence')
        if not isinstance(evidence,str) or not evidence.strip() or len(evidence)>1000:
            continue
        output.append({'exit_id':config['id'],'direction':'outbound','certainty':'clear',
                       'start_frame':a,'end_frame':b,'evidence':evidence})
    return output
