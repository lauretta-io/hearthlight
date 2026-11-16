"""Focused object evidence using the existing Qwen model; no person identification."""
import json
from object_semantics import is_fixed_fixture
import re
from activity import activity_images, parse_activity
from interactions import parse_interactions
from interaction_format import normalize_object_kind
from change_reports import change_inputs,empty_changes,RELEASES

PROMPT = '''Inspect only the objects visibly held, carried or interacted with by the person
inside the red box. Do not identify the person. Do not infer ownership or intent.
Describe object color, shape and material; do not put clothing or personal traits
in object appearance. Do not guess a specific object type when its shape is unclear.
Shelving, desks, tables and other fixed fixtures are interaction targets, not possessions. Contact with shelving is touch/use, never a carried item.
Nearby objects alone are not an interaction. Typing on a laptop resting on a desk
is use, not hold. A pickup requires visible surface-to-hand change across two frames.
Return exactly JSON {"description":"brief visible object handling","new_interactions":[],"ended_interactions":[],"new_possessions":[],"ended_possessions":[]}.
All four arrays are mandatory and contain proposed changes; continuing visible contact
is a candidate in new_interactions and will be deduplicated. Put visible contact endings
in ended_interactions using the original touch/use type. A confirmed end needs two
distinct frames. In ended_possessions use put_down/give for visible release, or
no_longer_visible with certainty:unclear for loss of view. Do not infer release
from absence. Do not return legacy events/interactions fields.
For possession events action must be pick_up, hold, carry, put_down, put_in_bag,
take_out_of_bag, give or receive. Each event needs action,item,appearance,start_frame,
end_frame,actor (target or unclear),certainty (clear or unclear),evidence.
Every object interaction MUST include ALL these keys with exact allowed values:
{"target_kind":"object","interaction_type":"touch","item":"table","appearance":"white flat surface","start_frame":0,"end_frame":0,"actor":"target","certainty":"clear","evidence":"The visible hand contacts the table surface."}
This is a format example, NOT evidence that this object/action appears in the images.
Choose interaction_type from touch,use,open,close,move. actor must be target or unclear;
certainty must be clear or unclear. Do not omit actor or certainty. Include item,
appearance, evidence and both local frame indices. No person interactions.
Use local frame indices, beginning at zero. Unclear evidence must not be clear.
Return empty arrays when no object handling is visible. JSON only.'''


def needed(track, report):
    if not report.get('description') or not track.get('detections'):
        return False
    events = report.get('events', [])
    for event in events:
        item = str(event.get('item', '')).lower()
        appearance = str(event.get('appearance', '')).lower()
        if item in {'object', 'item', 'thing', 'white object', 'black object'} or re.search(r'\b(shirt|jacket|jeans|pants|mask)\b', appearance):
            return True
    if not events and re.search(r'\b(hold|holding|held|carry|carrying|pickup|pick up|picks up|picked up)\b', report['description'], re.I):
        return True
    return not any(row.get('target_kind') == 'object' for row in report.get('interactions', [])) and bool(re.search(r'\b(typ(?:e|es|ing)|touch(?:es|ing)?|using|uses|interacting with|working (?:on|at)|works? (?:on|at)|reaching (?:for|toward))\b', report['description'], re.I))


def refine(models, frames, track, report, scene_description=''):
    detections = sorted(track['detections'], key=lambda row: row['frame_index'])
    # Bound visual cost while retaining both endpoints of the observed interval.
    positions = sorted({round(i * (len(detections) - 1) / min(5, len(detections) - 1)) for i in range(min(6, len(detections)))}) if len(detections) > 1 else [0]
    selected = [(detections[i]['frame_index'], detections[i]['box_xyxy']) for i in positions]
    crops = activity_images(frames, selected)
    prompt = PROMPT + '\nScene context (not evidence of handling):\n' + scene_description[:2000]
    raw = models.describe(crops, prompt, max_new_tokens=768)
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    value = json.loads(text)
    inputs,input_issues=change_inputs(value,track)
    event_values = inputs['new_possessions']+inputs['ended_possessions']
    interaction_values = inputs['new_interactions']
    if isinstance(event_values, list) and isinstance(interaction_values, list):
        kept = []
        for event in event_values:
            if isinstance(event, dict) and is_fixed_fixture(event.get('item')) and event.get('action') in {'hold', 'carry'}:
                if event['action'] == 'hold':
                    interaction_values.append({**event, 'target_kind': 'object', 'interaction_type': 'touch'})
            else:
                kept.append(event)
        event_values = kept
    activity = parse_activity(json.dumps({'description': value.get('description'), 'events': []}), len(crops), crops)
    if not isinstance(event_values, list) or not isinstance(interaction_values, list):
        raise ValueError('invalid_object_review_arrays')
    catalog = {1: {'person_id': None, 'detections': [{'frame_index': i} for i in range(len(crops))]}}
    interactions, endings, rejected = [], [], [{'kind':'envelope','reason':issue} for issue in input_issues]
    for event in event_values[:8]:
        try:
            activity['events'].extend(parse_activity(json.dumps({'description': activity['description'], 'events': [event]}), len(crops), crops)['events'])
        except ValueError as error:
            rejected.append({'kind': 'event', 'reason': str(error)})
    for interaction in interaction_values[:8]:
        interaction = normalize_object_kind(interaction)
        try:
            if not isinstance(interaction, dict) or interaction.get('target_kind') != 'object':
                raise ValueError('object_review_cannot_assign_person_interactions')
            interactions.extend(parse_interactions([interaction], 1, catalog, crops))
        except ValueError as error:
            rejected.append({'kind': 'interaction', 'reason': str(error)})
    for interaction in inputs['ended_interactions']:
        try:
            interaction=normalize_object_kind(interaction)
            if interaction.get('target_kind')!='object':raise ValueError('object_review_cannot_assign_person_interactions')
            accepted=parse_interactions([interaction],1,catalog,crops)
            for row in accepted:
                if row['certainty']=='clear' and (row['start_frame']==row['end_frame'] or crops[row['start_frame']].tobytes()==crops[row['end_frame']].tobytes()):raise ValueError('confirmed_interaction_end_requires_distinct_evidence')
            endings.extend(accepted)
        except ValueError as error:rejected.append({'kind':'ending','reason':str(error)})
    state_changes=empty_changes()
    state_changes['new_interactions']=interactions
    state_changes['ended_interactions']=endings
    for event in activity['events']:
        ended=event['action'] in RELEASES or any(row.get('action')=='unclear' and row.get('item')==event['item'] and row.get('appearance')==event['appearance'] for row in inputs['ended_possessions'])
        state_changes['ended_possessions' if ended else 'new_possessions'].append(event)
    for row in [*activity['events'], *interactions, *endings]:
        row['start_frame'] = selected[row['start_frame']][0]
        row['end_frame'] = selected[row['end_frame']][0]
    return {'description': activity['description'], 'events': activity['events'], 'interactions': interactions,
            'state_changes':state_changes,'model_id': models.vlm_id, 'frame_indices': [index for index, _ in selected], 'raw_model_output': raw[:8000], 'rejected_entries': rejected}


def refine_reports(models, frames, request, analysis):
    catalog = {track['track_id']: track for track in request['tracks']}
    results = []
    candidates = [report for report in analysis['persons'] if needed(catalog[report['track_id']], report)]
    candidates.sort(key=lambda report: max((d['box_xyxy'][2]-d['box_xyxy'][0])*(d['box_xyxy'][3]-d['box_xyxy'][1]) for d in catalog[report['track_id']]['detections']), reverse=True)
    for report in candidates[:2]:
        track = catalog[report['track_id']]
        try:
            result = refine(models, frames, track, report, analysis['scene_description'])
            if not result['events'] and not result['interactions'] and not result['state_changes']['ended_interactions']:
                report['object_refinement'] = {'status': 'invalid_entries' if result.get('rejected_entries') else 'no_additional_evidence', **result}
                results.append(report['object_refinement'])
                continue
            preserved=[row for row in report.get('events',[]) if row.get('action') in RELEASES]
            report['events'] = list({json.dumps(row,sort_keys=True):row for row in preserved+result['events']}.values())
            report['interactions'] = [row for row in report.get('interactions', []) if row.get('target_kind') == 'person'] + result['interactions']
            changes=report.setdefault('state_changes',empty_changes())
            for category in ('ended_interactions','ended_possessions'):
                changes[category]=list({json.dumps(row,sort_keys=True):row for row in changes.get(category,[])+result['state_changes'][category]}.values())
            changes['new_interactions']=report['interactions']
            changes['new_possessions']=result['state_changes']['new_possessions']
            if result['description']:
                report['description'] = (report['description'] + ' ' + result['description'])[:4000]
            report['object_refinement'] = {'status': 'evaluated', **result}
        except Exception as error:
            report['object_refinement'] = {'status': 'failed', 'error_code': type(error).__name__}
        results.append(report['object_refinement'])
    return results
