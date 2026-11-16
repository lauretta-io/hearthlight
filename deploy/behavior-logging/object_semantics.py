"""Custody concerns portable items, not contact with fixed surfaces."""
FIXED_FIXTURES = {'shelf', 'shelves', 'shelving', 'shelving unit', 'desk', 'desks', 'table', 'tables', 'wall', 'walls', 'floor', 'ceiling', 'doorframe', 'door frame','rack','display rack','display stand','display table','display shelf','display shelves','display case','showcase','counter','cabinet','cupboard','merchandise display','product display'}

def is_fixed_fixture(item):
    return str(item or '').strip().lower() in FIXED_FIXTURES
