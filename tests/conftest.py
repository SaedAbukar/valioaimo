import os

# The suite drives many agents quickly from one credential; the rate-limit test sets its own low limit.
os.environ.setdefault("AIMO_RATE_PER_MIN", "100000")
os.environ.setdefault("AIMO_RATE_BURST", "100000")
# Tests run on a frozen demo clock (13 Nov 2026 09:00 EET) so golden scenarios repeat; the server ticks.
os.environ.setdefault("AIMO_CLOCK_FROZEN", "1")
