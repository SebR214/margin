"""SEB-422: one live pull of the nairatoday_ngn tracker parses, the number is in range, and the row lands."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors import template_tracker as tt  # noqa: E402

r = tt.run_config_test('nairatoday_ngn')
assert r[7] is True, r
print('nairatoday_ngn: ok', r)
