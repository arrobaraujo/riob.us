"""Structured logging for GPS Bus Rio."""
import logging
import os


def _is_enabled():
    """Return whether PERF logs are enabled via PERF_LOG_ENABLED env var."""
    raw = str(os.getenv("PERF_LOG_ENABLED", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


# Configure root logger once.
_log_level = logging.DEBUG if _is_enabled() else logging.INFO
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=_log_level,
)

logger = logging.getLogger("gps_bus_rio")


def perf_logging_enabled():
    """Return whether PERF logs are enabled via PERF_LOG_ENABLED env var."""
    return _is_enabled()


def perf_log(message):
    """Emit PERF log line only when enabled."""
    if _is_enabled():
        logger.info(message)
