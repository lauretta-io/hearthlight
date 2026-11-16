"""Normalize explicit object-category serialization errors without adding evidence."""
OBJECT_ITEMS={'table','tables','desk','desks','shelf','shelves','shelving','shelving unit',
              'laptop','computer','keyboard','mouse','monitor','screen','pen','bottle','water bottle','cup','bag'}
OBJECT_ACTIONS={'touch','use','open','close','move'}


def normalize_object_kind(value):
    if not isinstance(value,dict):
        return value
    item=str(value.get('item','')).strip().lower()
    kind=str(value.get('target_kind','')).strip().lower()
    if (item in OBJECT_ITEMS and value.get('interaction_type') in OBJECT_ACTIONS
            and value.get('target_track_id') is None
            and (kind==item or kind=='person')):
        return {**value,'target_kind':'object'}
    return value
