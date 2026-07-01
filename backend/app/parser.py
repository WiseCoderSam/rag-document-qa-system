import json
import re
from datetime import datetime
from typing import Any, Optional

# --- Regexes -----------------------------------------------------------

# RFC3164-style syslog: "Jul  1 10:00:23 webserver01 sshd[1421]: message text"
SYSLOG_REGEX = re.compile(
    r"^(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<hostname>\S+)\s+"
    r"(?P<app>[\w./\-]+?)(?:\[\d+\])?:\s*"
    r"(?P<message>.*)$"
)

# Leading ISO-ish timestamp on an otherwise free-form log line, e.g.
# "2026-07-01 10:00:00 ERROR Failed login attempt for user admin from 10.0.0.5"
TIMESTAMP_PREFIX_REGEX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

LEVEL_REGEX = re.compile(r"^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b[:\s]*", re.IGNORECASE)

IP_REGEX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

USER_REGEX = re.compile(
    r"(?:invalid user|authenticated user|for user|user)[:=]?\s+([\w.\-@]+)",
    re.IGNORECASE,
)
USER_FALLBACK_REGEX = re.compile(r"for\s+([\w.\-@]+)\s+from\b", re.IGNORECASE)

EVENT_ID_REGEX = re.compile(r"(?:event[_ ]?id|eventid)[:=]?\s*([\w\-]+)", re.IGNORECASE)

EVENT_ID_KEYWORDS = [
    (re.compile(r"invalid user", re.IGNORECASE), "INVALID_USER"),
    (re.compile(r"failed (password|login)", re.IGNORECASE), "AUTH_FAILURE"),
    (re.compile(r"authentication failure", re.IGNORECASE), "AUTH_FAILURE"),
    (re.compile(r"accepted (password|login)", re.IGNORECASE), "AUTH_SUCCESS"),
    (re.compile(r"session opened", re.IGNORECASE), "SESSION_OPENED"),
    (re.compile(r"session closed", re.IGNORECASE), "SESSION_CLOSED"),
]

SEVERITY_KEYWORDS = [
    ("CRITICAL", ("critical", "fatal", "panic")),
    ("ERROR", ("error", "fail", "denied")),
    ("WARNING", ("warn",)),
]

TIMESTAMP_KEYS = ("timestamp", "time", "ts", "@timestamp", "date")
SEVERITY_KEYS = ("severity", "level", "log_level", "loglevel")
MESSAGE_KEYS = ("message", "msg", "log")
IP_KEYS = ("ip", "ip_address", "src_ip", "source_ip", "client_ip")
USER_KEYS = ("user", "username", "user_name", "account")
HOST_KEYS = ("host", "hostname", "server")
EVENT_ID_KEYS = ("event_id", "eventId", "eventID", "id")


# --- Small helpers -------------------------------------------------------

def _first_present(data: dict, keys: tuple) -> Optional[Any]:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_severity_token(token: str) -> str:
    token = token.strip().upper()
    if token == "WARN":
        return "WARNING"
    if token == "FATAL":
        return "CRITICAL"
    return token


def _infer_severity(text: str) -> str:
    lower = text.lower()
    for severity, keywords in SEVERITY_KEYWORDS:
        if any(keyword in lower for keyword in keywords):
            return severity
    return "INFO"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None

    if not isinstance(value, str):
        return None

    value = value.strip()

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass

    try:
        parsed = datetime.strptime(value, "%b %d %H:%M:%S")
        return parsed.replace(year=datetime.utcnow().year)
    except ValueError:
        pass

    return None


def _extract_ip(text: str) -> Optional[str]:
    match = IP_REGEX.search(text)
    return match.group(0) if match else None


def _extract_user(text: str) -> Optional[str]:
    match = USER_REGEX.search(text)
    if match:
        return match.group(1)
    match = USER_FALLBACK_REGEX.search(text)
    return match.group(1) if match else None


def _extract_event_id(text: str) -> Optional[str]:
    match = EVENT_ID_REGEX.search(text)
    if match:
        return match.group(1)
    for pattern, event_id in EVENT_ID_KEYWORDS:
        if pattern.search(text):
            return event_id
    return None


# --- Format-specific normalizers -----------------------------------------

def _try_parse_json(line: str) -> Optional[dict]:
    stripped = line.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _normalize_json_entry(data: dict, raw_line: str) -> dict:
    severity_raw = _first_present(data, SEVERITY_KEYS)
    severity = _normalize_severity_token(str(severity_raw)) if severity_raw else _infer_severity(raw_line)
    message = _first_present(data, MESSAGE_KEYS)
    event_id = _first_present(data, EVENT_ID_KEYS)

    return {
        "timestamp": _parse_timestamp(_first_present(data, TIMESTAMP_KEYS)),
        "severity": severity,
        "ip_address": _first_present(data, IP_KEYS) or _extract_ip(raw_line),
        "user_name": _first_present(data, USER_KEYS) or _extract_user(raw_line),
        "hostname": _first_present(data, HOST_KEYS),
        "event_id": str(event_id) if event_id is not None else None,
        "message": str(message) if message is not None else raw_line,
        "parsed_json": data,
    }


def _normalize_syslog_entry(match: re.Match, raw_line: str) -> dict:
    hostname = match.group("hostname")
    app = match.group("app")
    message = match.group("message")
    full_message = f"{app}: {message}" if app else message

    level_match = LEVEL_REGEX.match(message)
    if level_match:
        severity = _normalize_severity_token(level_match.group(1))
    else:
        severity = _infer_severity(message)

    return {
        "timestamp": _parse_timestamp(match.group("timestamp")),
        "severity": severity,
        "ip_address": _extract_ip(raw_line),
        "user_name": _extract_user(raw_line),
        "hostname": hostname,
        "event_id": _extract_event_id(raw_line),
        "message": full_message,
        "parsed_json": None,
    }


def _normalize_auth_entry(line: str) -> dict:
    ts_match = TIMESTAMP_PREFIX_REGEX.match(line)
    timestamp = None
    remainder = line
    if ts_match:
        timestamp = _parse_timestamp(ts_match.group("ts"))
        remainder = line[ts_match.end():].strip()

    level_match = LEVEL_REGEX.match(remainder)
    if level_match:
        severity = _normalize_severity_token(level_match.group(1))
        remainder = remainder[level_match.end():].strip()
    else:
        severity = _infer_severity(remainder or line)

    return {
        "timestamp": timestamp,
        "severity": severity,
        "ip_address": _extract_ip(line),
        "user_name": _extract_user(line),
        "hostname": None,
        "event_id": _extract_event_id(line),
        "message": remainder or line,
        "parsed_json": None,
    }


# --- Public API ------------------------------------------------------------

def parse_log_line(line: str) -> dict:
    """
    Parses a single log line into normalized LogEntry fields:
    timestamp, severity, ip_address, user_name, hostname, event_id,
    message, and parsed_json.

    Supports, in order of precedence:
      1. Standard JSON log lines (e.g. {"time": ..., "level": ..., "msg": ...})
      2. RFC3164-style syslog lines ("Mon dd HH:MM:SS host app[pid]: message")
      3. Free-form auth/firewall log lines, from which IP addresses, usernames,
         and event identifiers are extracted heuristically.
    """
    line = line.rstrip("\r\n")

    json_data = _try_parse_json(line)
    if json_data is not None:
        return _normalize_json_entry(json_data, line)

    syslog_match = SYSLOG_REGEX.match(line)
    if syslog_match:
        return _normalize_syslog_entry(syslog_match, line)

    return _normalize_auth_entry(line)
