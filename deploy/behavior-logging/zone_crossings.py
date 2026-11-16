"""Directional zone crossings from one continuous local track; no identity matching."""

def crossing_events(request):
    width, height = request['frame_size']['width'], request['frame_size']['height']
    configured = request.get('building_exit')
    if not configured or width <= 0 or height <= 0:
        return {}
    result = {}
    for track in request['tracks']:
        for zone in request.get('zones', []):
            if zone.get('kind') != 'exit':
                continue
            left, top, right, bottom = zone['region']
            direction = zone.get('outboundDirection', 'right')
            if direction == 'right': low, high, cross_low, cross_high = left, right, top, bottom
            elif direction == 'left': low, high, cross_low, cross_high = -right, -left, top, bottom
            elif direction == 'down': low, high, cross_low, cross_high = top, bottom, left, right
            elif direction == 'up': low, high, cross_low, cross_high = -bottom, -top, left, right
            else: continue
            span=high-low
            low,high=low+span*zone.get('entryGate',0),low+span*zone.get('exitGate',1)
            start = previous = None
            inside = 0
            for detection in sorted(track['detections'], key=lambda row: row['frame_index']):
                frame = detection['frame_index']
                x1, y1, x2, y2 = detection['box_xyxy']
                # Ground contact: the center of the bottom of the detected box.
                x, y = (x1+x2)/2/width, y2/height
                progress, cross = (x,y) if direction == 'right' else (-x,y) if direction == 'left' else (y,x) if direction == 'down' else (-y,x)
                if previous is not None and frame-previous > 2:
                    start, inside = None, 0
                previous = frame
                if not cross_low <= cross <= cross_high:
                    start, inside = None, 0
                    continue
                if progress < low-.005:
                    start, inside = detection, 0
                elif low+.005 <= progress <= high-.005 and start is not None:
                    inside += 1
                elif progress > high+.005:
                    if start is not None and inside >= 2:
                        result.setdefault(track['track_id'], []).append({
                            'exit_id': configured['id'], 'direction': 'outbound', 'certainty': 'clear',
                            'start_frame': start['frame_index'], 'end_frame': frame,
                            'evidence': f"Tracked foot point entered {zone['name']} from the room side, occupied the zone in {inside} frames, and crossed its outbound {direction} line.",
                            'evidence_method': 'tracked_zone_crossing', 'zone_id': zone['id'],
                            'zone_name': zone['name'], 'zone_region': zone['region'],
                            'outbound_direction': direction, 'inside_frame_count': inside,'entry_gate':zone.get('entryGate',0),'exit_gate':zone.get('exitGate',1),
                        })
                    start, inside = None, 0
    return result


def attach_crossings(analysis, request):
    events = crossing_events(request)
    if not events:
        return analysis
    if analysis is None:
        analysis = {'scene_description': 'Directional movement through the configured exit zone was recorded by the tracker.', 'persons': [], 'errors': ['scene_model_unavailable']}
    reports = {row['track_id']: row for row in analysis['persons']}
    for track_id, exits in events.items():
        report = reports.get(track_id)
        if report is None:
            report = {'track_id': track_id, 'description': None, 'events': [], 'interactions': [], 'exits': [], 'analysis_status': 'tracked', 'error_code': None}
            analysis['persons'].append(report)
        if not report.get('description'):
            report['description'] = exits[-1]['evidence']
        else:
            report['description'] = (report['description']+' '+exits[-1]['evidence'])[:4000]
        # One event per zone crossing; use geometric evidence over a duplicate model proposal.
        prior = [row for row in report.get('exits', []) if row.get('exit_id') != exits[0]['exit_id']]
        report['exits'] = prior+exits
    return analysis


def track_zone_motion(request):
    width,height=request['frame_size']['width'],request['frame_size']['height']
    result={}
    for track in request.get('tracks',[]):
        detections=sorted(track['detections'],key=lambda row:row['frame_index'])
        if len(detections)<2:continue
        for zone in request.get('zones',[]):
            if zone.get('kind')!='exit':continue
            l,t,r,b=zone['region']
            points=[((d['box_xyxy'][0]+d['box_xyxy'][2])/2/width,d['box_xyxy'][3]/height) for d in detections]
            if not any(l<=x<=r and t<=y<=b for x,y in points):continue
            direction=zone.get('outboundDirection','right')
            dx,dy=points[-1][0]-points[0][0],points[-1][1]-points[0][1]
            progress=dx if direction=='right' else -dx if direction=='left' else dy if direction=='down' else -dy
            motion='toward_exit' if progress>.03 else 'toward_room' if progress<-.03 else 'stationary'
            result.setdefault(track['track_id'],[]).append({'zone_id':zone['id'],'zone_name':zone['name'],'motion':motion,'outbound_direction':direction,'start_frame':detections[0]['frame_index'],'end_frame':detections[-1]['frame_index']})
    return result


def ground_exit_descriptions(analysis,request):
    """Keep prose consistent with measured motion; raw model output remains intact."""
    if analysis is None:return analysis
    import re
    motions=track_zone_motion(request)
    arrows={'right':('left to right','right to left'),'left':('right to left','left to right'),'down':('top to bottom','bottom to top'),'up':('bottom to top','top to bottom')}
    for report in analysis['persons']:
        report['zone_motion']=motions.get(report['track_id'],[])
        if report.get('exits') or not report.get('description'):continue
        roomward=[row for row in report['zone_motion'] if row['motion']=='toward_room']
        no_exit_config=not request.get('building_exit')
        if not roomward and not no_exit_config:continue
        sentences=re.split(r'(?<=[.!?])\s+',report['description'])
        def claim(sentence):
            return bool(re.search(r"(?:exit|leave)\s+zone|(?:exit|leav\w*)\s+(?:the\s+)?(?:building|premises)",sentence,re.I) and re.search(r'walk|mov|pass|exit|leav',sentence,re.I))
        kept=[sentence for sentence in sentences if not claim(sentence)]
        if len(kept)==len(sentences):continue
        report['model_description_before_zone_check']=report['description']
        if roomward:
            motion=roomward[-1];direction=arrows[motion['outbound_direction']][1]
            kept.append(f"Tracked movement at {motion['zone_name']} is {direction}, toward the room; no outbound crossing was recorded.")
        else:kept.append('No configured exit-zone crossing was recorded for this camera.')
        report['description']=' '.join(kept)[:4000]
        report['zone_grounding']='unsupported_outbound_prose_removed'
    return analysis
