"""Validate model-labelled contact with configured displays; presence is not contact."""
def annotate_contact(rows, raw, request, track):
    area_id=raw.get('interaction_area_id')
    role=raw.get('interaction_target_role')
    if area_id is None and role is None:
        return rows
    area=next((zone for zone in request.get('zones',[]) if zone.get('id')==area_id and zone.get('itemHoldingArea')),None)
    if not area or role not in {'displayed_item','item_holding_area'}:
        raise ValueError('invalid_interaction_area_reference')
    width,height=request['frame_size']['width'],request['frame_size']['height']
    l,t,r,b=area['region'];detections={d['frame_index']:d['box_xyxy'] for d in track['detections']}
    for row in rows:
        if row['target_kind']!='object':raise ValueError('display_contact_requires_object_target')
        for index in [row['start_frame'],row['end_frame']]:
            x1,y1,x2,y2=detections[index]
            if x2/width<l or x1/width>r or y2/height<t or y1/height>b:
                raise ValueError('contact_track_outside_declared_area')
        row.update(interaction_area_id=area_id,interaction_target_role=role)
    return rows
