"""Capture-time zone context and measured occupancy, separate from inferred contact."""
from zone_crossings import crossing_events

DIRECTIONS={'right':'left to right','left':'right to left','down':'top to bottom','up':'bottom to top'}


def zone_reports(request):
    width,height=request['frame_size']['width'],request['frame_size']['height']
    crossings=crossing_events(request)
    result=[]
    for zone in request.get('zones',[]):
        left,top,right,bottom=zone['region']
        occupied=set()
        for track in request.get('tracks',[]):
            for detection in track['detections']:
                x1,y1,x2,y2=detection['box_xyxy']
                if left <= (x1+x2)/2/width <= right and top <= y2/height <= bottom:
                    occupied.add(detection['frame_index'])
        evidence=[{**event,'track_id':track_id} for track_id,events in crossings.items() for event in events if event['zone_id']==zone['id']]
        result.append({**zone,'tracking_status':request.get('tracking_status','unavailable'),
                       'frame_count':request.get('frame_count',0),'occupied_frames':len(occupied),
                       'outbound_crossings':len(evidence),'crossing_evidence':evidence})
    return result


def zone_explanation(reports):
    lines=[]
    for zone in reports:
        l,t,r,b=zone['region']
        geometry=f"bounds left {l:.0%}, top {t:.0%}, right {r:.0%}, bottom {b:.0%}"
        heading=f"{zone['name']} ({'exit' if zone['kind']=='exit' else 'scene area'}): {zone['description']}"
        if zone['kind']=='exit':
            heading+=f" Outbound: {DIRECTIONS[zone['outboundDirection']]}."
        observed=(f"Occupied in {zone['occupied_frames']}/{zone['frame_count']} sampled frames; {zone['outbound_crossings']} outbound crossings."
                  if zone['tracking_status']=='ready' else 'Zone tracking was unavailable for this sample.')
        lines.append(f"{heading} Area: {geometry}. {observed}")
    return '\n'.join(lines)
