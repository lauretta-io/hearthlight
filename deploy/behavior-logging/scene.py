"""Frame-aligned person-track context and joint scene/behavior VLM output."""

import json
from object_semantics import is_fixed_fixture

from zone_explanations import zone_reports
from exit_observations import parse_exits
from activity import parse_activity
from interactions import parse_interactions
from interaction_areas import annotate_contact
from interaction_format import normalize_object_kind
from change_reports import change_inputs,empty_changes,RELEASES

SCENE_PROMPT = '''Analyze the ordered camera frames and supplied track catalog. Boxes identify local
track_id only; never infer identity, ownership, intent, or activity between samples.
Return exactly this JSON structure, one persons entry per supplied track_id:
{"scene_description":"concise chronological explanation including configured zones","persons":[{"track_id":1,"description":"one short sentence of visible behavior","new_interactions":[],"ended_interactions":[],"new_possessions":[],"ended_possessions":[],"exits":[]}]}
All four change arrays are mandatory. Use [] when no supported candidate exists.
These are proposed changes. The state reducer compares prior logs and merges repeats.
new_interactions: visible current object/person contact, including continuing contact
that might be a new start. ended_interactions: evidence of contact ending.
new_possessions: first-seen holding/carrying or visible acquisition of an object.
ended_possessions: visible put_down/give, or uncertain loss-of-sight candidates.
An object/person interaction entry requires target_kind (object or person),
interaction_type, actor_track_id (integer equal to THIS track_id), certainty (clear or unclear), evidence,
start_frame and end_frame. Use actor:"unclear" only when attribution is ambiguous. The numeric actor_track_id explicitly names the actor; never use actor:"person".
Object interactions also need item and appearance of the OBJECT, not clothing.
Their target_kind is always the literal "object", never "laptop", "table" or "shelf".
Object interaction types: touch, use, open, close, move.
For visible contact with merchandise or fixtures in a configured itemHoldingArea,
include interaction_area_id equal to that supplied zone ID and interaction_target_role
as displayed_item or item_holding_area. Tag only actual handling/touch/use of the
area or its displayed objects, never mere presence or personal-item use nearby.
These interactions can qualify for an exit review without a pickup or possession. The same area/role fields can be attached to a held/handled displayed item in new_possessions when the display association is visible; do not tag personal belongings merely used nearby.
Do not invent display zones or tag an object merely because it is near a person. Person interaction types:
talk, gesture, approach, follow, physical_contact, give, receive, help. Person targets
need target_track_id from the supplied catalog; never invent an off-camera counterpart.
For ended_interactions use the original interaction_type (such as touch or use).
Ended means visible withdrawal, stopping use or separation. A hand still on a keyboard
is ongoing contact in new_interactions, NEVER an ended interaction.
Each possession entry requires action, item, appearance, actor_track_id, certainty, evidence,
start_frame and end_frame. Start actions: hold, carry, pick_up, receive,
put_in_bag, take_out_of_bag. End actions: put_down, give. Use no_longer_visible with
certainty:unclear when an item is occluded or missing; this is NOT confirmed release.
All endpoints must be detected frames of this track. Clear endings and pickup,
release, handover or opening/closing/moving transitions require two distinct frames.
Holding alone is hold, never pickup. Laptop/computer operation on a table is use,
not hold. Tables and shelves are fixed fixtures: touch/use interactions, never possessions.
Visible hand-to-table/shelf contact belongs in new_interactions. Walking near furniture
or occupying its zone is not physical contact. People are never possessions.
Use prior_state, person_description and behavior_context as historical context, not
proof of current activity. For an existing object optionally copy its reference_key
exactly; use its existing item and appearance for endings. Do not invent references.
Possible changes must retain certainty:unclear. Never turn disappearance into release.
Include every configured zone by name in scene_description: purpose, relevant layout,
current activity or no observed activity, and outbound direction for exit zones.
Use supplied zone_reports for measured sampled occupancy and tracked crossings.
Zone descriptions are fixed context; counts are observations. Do not infer hand contact
from a tracked foot point in a zone. Black camera borders are not doors or exits.
Tracker zone crossings are included independently. Optional visual exits need exit_id
from building_exit, direction:outbound, certainty:clear, start_frame, end_frame and
evidence of the visible crossing. Standing near a door or disappearing is insufficient.
Keep descriptions/evidence short, avoid repeated sentences and technical frame names.
Return JSON only, without Markdown or legacy events/interactions fields.'''


def build_request(sample, frames, tracks, person_ids, tracking_status="ready"):
    fps = sample.get("sample_fps", 1)
    catalog = []
    for track_id, (track, person_id) in enumerate(zip(tracks, person_ids, strict=True), start=1):
        catalog.append({
            "track_id": track_id,
            "person_id": person_id,
            "detections": [{"frame_index": index, "offset_seconds": index / fps,
                            "box_xyxy": list(box)} for index, box in track],
        })
    request = {
        "schema_version": 1, "scene_id": sample["sample_id"],
        "camera_id": sample["camera_id"], "camera_name": sample.get("camera_name"),
        "sample_started_at": sample.get("sample_started_at"), "sampled_at": sample["sampled_at"],
        "frame_count": len(frames), "sample_fps": fps,
        "frame_size": {"width": frames[0].width, "height": frames[0].height},
        "box_coordinate_system": "sampled_image_pixels_xyxy",
        "tracking_status": tracking_status, "tracks": catalog,
        "scene_context": sample.get("scene_context", {}), "zones": sample.get("zones", []),
        **({"building_exit": sample["building_exit"]} if sample.get("building_exit") else {}),
    }

    request["zone_reports"] = zone_reports(request)
    return request

def labeled_frames(frames, request):
    from PIL import ImageDraw, ImageFont

    images = [frame.copy() for frame in frames]
    font = ImageFont.truetype("DejaVuSans.ttf", 16)
    colors = ["yellow", "cyan", "magenta", "lime", "orange", "red"]
    for zone in request.get('zones', []):
        for image in images:
            draw = ImageDraw.Draw(image)
            l,t,r,b=zone['region']
            rect=(l*image.width,t*image.height,r*image.width,b*image.height)
            draw.rectangle(rect, outline='red' if zone['kind']=='exit' else 'cyan', width=3)
            draw.text((rect[0]+5,rect[1]+5),zone['name'],fill='red' if zone['kind']=='exit' else 'cyan',font=font)
    for track in request["tracks"]:
        color = colors[(track["track_id"] - 1) % len(colors)]
        for detection in track["detections"]:
            draw = ImageDraw.Draw(images[detection["frame_index"]])
            x1, y1, x2, y2 = detection["box_xyxy"]
            draw.rectangle((x1, y1, x2, y2), outline=color, width=2)
            label = str(track["track_id"])
            x, y = max(0, x1), max(0, y1 - 20)
            bounds = draw.textbbox((x, y), label, font=font)
            draw.rectangle(bounds, fill="black")
            draw.text((x, y), label, font=font, fill=color)
    return images


def parse_scene(raw, request, frames):
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("scene_response_must_be_an_object")
    scene_description = payload.get("scene_description")
    if not isinstance(scene_description, str) or not scene_description.strip():
        raise ValueError("scene_description_missing")
    persons = payload.get("persons")
    person_section_invalid = not isinstance(persons, list)
    if person_section_invalid:
        persons = []
    catalog = {track["track_id"]: track for track in request["tracks"]}
    reports = {track_id: {"track_id": track_id, "description": None, "events": [],
                          "analysis_status": "omitted", "error_code": "person_report_missing"}
               for track_id in catalog}
    errors = ["scene_persons_missing"] if person_section_invalid else []
    seen = set()
    for report in persons:
        if not isinstance(report, dict):
            errors.append("invalid_person_report")
            continue
        track_id = report.get("track_id")
        if isinstance(track_id, str) and track_id.isdecimal():
            track_id = int(track_id)
        if type(track_id) is not int or track_id not in catalog:
            errors.append("unknown_track_id")
            continue
        if track_id in seen:
            reports[track_id] = {"track_id": track_id, "description": None, "events": [],
                                 "analysis_status": "invalid_response", "error_code": "duplicate_track_id"}
            errors.append("duplicate_track_id")
            continue
        seen.add(track_id)
        try:
            if not isinstance(report.get("description"), str) or not report["description"].strip():
                raise ValueError("person_description_missing")
            inputs, input_issues = change_inputs(report, catalog[track_id])
            state_changes = empty_changes()
            events = inputs["new_possessions"] + inputs["ended_possessions"]
            person_id = catalog[track_id]["person_id"]
            if isinstance(events, list) and person_id is not None:
                events = [{**event, "actor": "target"} if isinstance(event, dict)
                          and event.get("actor") == person_id else event for event in events]
            issues, valid_events = list(input_issues), []
            pending_interactions = inputs["new_interactions"]
            if not isinstance(pending_interactions, list) or len(pending_interactions) > 8:
                pending_interactions = []
                issues.append("invalid_interactions")
            else:
                pending_interactions = list(pending_interactions)
            if not isinstance(events, list) or len(events) > 16:
                issues.append("invalid_activity_events")
                events = []
            indices = {detection["frame_index"] for detection in catalog[track_id]["detections"]}
            for event in events:
                if isinstance(event, dict) and event.get("action") in {"sit", "sitting", "stand", "standing", "walk", "walking", "look", "looking"}:
                    continue  # General behavior is retained in description, never custody.
                if isinstance(event, dict) and is_fixed_fixture(event.get("item")) and event.get("action") in {"hold", "carry"}:
                    if event['action'] == 'hold':
                        pending_interactions.append({**event, 'target_kind': 'object', 'interaction_type': 'touch'})
                    else:
                        issues.append('fixed_fixture_is_not_a_carried_item')
                    continue
                if isinstance(event, dict) and event.get("action") in {"touch", "use", "open", "close", "move"}:
                    pending_interactions.append({**event, "target_kind": "object", "interaction_type": event["action"]})
                    continue
                try:
                    parsed = parse_activity(json.dumps({"description": report["description"], "events": [event]}), len(frames), frames)
                    if any(item["start_frame"] not in indices or item["end_frame"] not in indices for item in parsed["events"]):
                        raise ValueError("event_outside_person_track")
                    if event.get('interaction_area_id') is not None:
                        try:
                            scoped=annotate_contact([{**row,'target_kind':'object'} for row in parsed['events']],event,request,catalog[track_id])
                            for row,location in zip(parsed['events'],scoped):
                                row['interaction_area_id']=location['interaction_area_id'];row['interaction_target_role']=location['interaction_target_role']
                        except ValueError as error:issues.append(str(error))
                    valid_events.extend(parsed["events"])
                    for item in parsed["events"]:
                        category="ended_possessions" if item["action"] in RELEASES or event in inputs["ended_possessions"] else "new_possessions"
                        state_changes[category].append(item)
                except (ValueError, TypeError) as error:
                    issues.append(str(error))
            valid_interactions = []
            if len(pending_interactions) > 16:
                issues.append("invalid_interactions")
                pending_interactions = []
            for interaction in pending_interactions:
                interaction = normalize_object_kind(interaction)
                try:
                    accepted=parse_interactions([interaction], track_id, catalog, frames)
                    try:accepted=annotate_contact(accepted,interaction,request,catalog[track_id])
                    except ValueError as error:issues.append(str(error))
                    valid_interactions.extend(accepted)
                    state_changes["new_interactions"].extend(accepted)
                except (ValueError, TypeError) as error:
                    issues.append(str(error))
            for interaction in inputs['ended_interactions']:
                try:
                    interaction=normalize_object_kind(interaction)
                    accepted=parse_interactions([interaction],track_id,catalog,frames)
                    for item in accepted:
                        if item['certainty']=='clear' and (item['start_frame']==item['end_frame'] or frames[item['start_frame']].tobytes()==frames[item['end_frame']].tobytes()):
                            raise ValueError('confirmed_interaction_end_requires_distinct_evidence')
                    state_changes['ended_interactions'].extend(accepted)
                except (ValueError,TypeError) as error:
                    issues.append(str(error))
            try:
                exits = parse_exits(report.get("exits", []), catalog[track_id], request, frames)
            except (ValueError, TypeError) as error:
                exits = []
                issues.append(str(error))
            activity = {"description": report["description"][:2000],
                        "events": sorted(valid_events, key=lambda item: (item["end_frame"], item["start_frame"])),
                        "interactions": valid_interactions, "exits": exits, "state_changes": state_changes}
        except (ValueError, TypeError) as error:
            description = report.get("description")
            usable_description = isinstance(description, str) and bool(description.strip())
            reports[track_id] = {"track_id": track_id,
                                 "description": description[:2000] if usable_description else None,
                                 "events": [], "analysis_status": "partial" if usable_description else "invalid_response",
                                 "error_code": str(error)[:120]}
            errors.append("invalid_person_report")
            continue
        if issues:
            errors.append("invalid_person_report")
        reports[track_id] = {"track_id": track_id, **activity,
                             "analysis_status": "partial" if issues else "analyzed",
                             "error_code": issues[0][:120] if issues else None}
    return {"scene_description": scene_description[:8000], "persons": list(reports.values()),
            "errors": errors}
