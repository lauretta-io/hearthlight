"""Custody concerns portable items, not contact with fixed surfaces."""
FIXED_FIXTURES = {'shelf', 'shelves', 'shelving', 'shelving unit', 'desk', 'desks', 'table', 'tables', 'wall', 'walls', 'floor', 'ceiling', 'doorframe', 'door frame'}

def is_fixed_fixture(item):
    return str(item or '').strip().lower() in FIXED_FIXTURES
