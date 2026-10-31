"""SEB-422: one live pull of the dolarapi_ar_blue tracker parses, the number is in range, and the row lands."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors import template_tracker as tt  # noqa: E402

r = tt.run_config_test('dolarapi_ar_blue')
assert r[7] is True, r
print('dolarapi_ar_blue: ok', r)
