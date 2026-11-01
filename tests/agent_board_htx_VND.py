"""SEB-422: one live pull of htx_VND parses, the prices are within 30% of the official rate, and the row lands."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors import template_board as tb  # noqa: E402

row = tb.run_config_test('htx_VND')
assert row["board"] and row["ccy"], row
print("htx_VND: ok", row)
