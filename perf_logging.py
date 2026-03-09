import os


def perf_logging_enabled():
    """Return whether PERF logs are enabled via PERF_LOG_ENABLED env var."""
    raw = str(os.getenv("PERF_LOG_ENABLED", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def perf_log(message):
    """Emit PERF log line only when enabled."""
    if perf_logging_enabled():
        print(message)
