import os

# The suite drives many agents quickly from one credential; the rate-limit test sets its own low limit.
os.environ.setdefault("AIMO_RATE_PER_MIN", "100000")
os.environ.setdefault("AIMO_RATE_BURST", "100000")
# Tests run on a frozen demo clock (13 Nov 2026 09:00 EET) so golden scenarios repeat; the server ticks.
os.environ.setdefault("AIMO_CLOCK_FROZEN", "1")
# Tests never call a real model: the analyst and the chat agent see no Anthropic key (load_dotenv never overrides
# a variable that is already set). The agent tests inject a scripted client instead.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
