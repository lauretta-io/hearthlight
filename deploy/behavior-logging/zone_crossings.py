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
                            'evidence': f"Tracked foot point entered {zone['name']} from the room side, occupied the zone in {inside} frames, and crossed its outbound {direction} edge.",
                            'evidence_method': 'tracked_zone_crossing', 'zone_id': zone['id'],
                            'zone_name': zone['name'], 'zone_region': zone['region'],
                            'outbound_direction': direction, 'inside_frame_count': inside,
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
