import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, List

from sqlalchemy.orm import Session

from . import models

# --- Brute force ------------------------------------------------------

BRUTE_FORCE_THRESHOLD = 5
BRUTE_FORCE_WINDOW = timedelta(minutes=5)

FAILED_LOGIN_EVENT_IDS = {"4625", "AUTH_FAILURE"}
FAILED_LOGIN_KEYWORD = re.compile(r"failed login|failed password|authentication failure", re.IGNORECASE)


def _is_failed_login(entry: models.LogEntry) -> bool:
    if entry.event_id and str(entry.event_id) in FAILED_LOGIN_EVENT_IDS:
        return True
    return bool(FAILED_LOGIN_KEYWORD.search(entry.message or ""))


def detect_brute_force(entries: Iterable[models.LogEntry]) -> List[dict]:
    """
    Flags source IPs with 5+ failed login attempts within a 5 minute window.
    """
    by_ip: dict[str, List[models.LogEntry]] = defaultdict(list)
    for entry in entries:
        if entry.ip_address and _is_failed_login(entry):
            by_ip[entry.ip_address].append(entry)

    findings = []
    for ip, attempts in by_ip.items():
        timestamped = sorted((e for e in attempts if e.timestamp), key=lambda e: e.timestamp)
        undated = [e for e in attempts if not e.timestamp]

        window: List[models.LogEntry] = []
        flagged = False
        for entry in timestamped:
            window.append(entry)
            window = [e for e in window if entry.timestamp - e.timestamp <= BRUTE_FORCE_WINDOW]
            if len(window) >= BRUTE_FORCE_THRESHOLD:
                flagged = True
                break

        # Entries without a parsed timestamp can't be windowed reliably; treat the
        # whole batch for that IP as a single window if there are enough of them.
        if not flagged and len(undated) >= BRUTE_FORCE_THRESHOLD:
            flagged = True
            window = undated

        if flagged:
            affected_user = next((e.user_name for e in attempts if e.user_name), None)
            findings.append({
                "title": f"Brute force login attempts from {ip}",
                "rule_name": "Brute force login",
                "severity": "HIGH",
                "description": (
                    f"Detected {len(window)} failed login attempts from source IP {ip} "
                    f"within a {int(BRUTE_FORCE_WINDOW.total_seconds() // 60)}-minute window."
                ),
                "mitre_technique": "T1110",
                "mitre_tactic": "Credential Access",
                "affected_user": affected_user,
                "affected_ip": ip,
            })

    return findings


# --- SQL injection / XSS signature matching -------------------------------

INJECTION_SIGNATURES = [
    (re.compile(r"union\s+select", re.IGNORECASE), "UNION SELECT"),
    (re.compile(r"or\s+1\s*=\s*1", re.IGNORECASE), "OR 1=1"),
    (re.compile(r"<script\b", re.IGNORECASE), "<script>"),
]


def detect_injection_attacks(entries: Iterable[models.LogEntry]) -> List[dict]:
    """
    Flags log entries whose message contains a known SQL injection or XSS
    signature (UNION SELECT, OR 1=1, <script>).
    """
    findings = []
    for entry in entries:
        message = entry.message or ""
        for pattern, label in INJECTION_SIGNATURES:
            if pattern.search(message):
                findings.append({
                    "title": f"Possible injection attack detected ({label})",
                    "rule_name": "SQL/XSS injection signature",
                    "severity": "CRITICAL",
                    "description": (
                        f"Log entry matched injection signature \"{label}\": {message[:300]}"
                    ),
                    "mitre_technique": "T1190",
                    "mitre_tactic": "Initial Access",
                    "affected_user": entry.user_name,
                    "affected_ip": entry.ip_address,
                })
                break

    return findings


# --- Entry point -----------------------------------------------------------

def run_detection_rules(db: Session, entries: List[models.LogEntry], log_file: models.LogFile) -> List[models.Incident]:
    """
    Runs all detection rules over the given (already persisted) LogEntry
    records and inserts an Incident for each match, linked to log_file.
    Returns the created Incident objects.
    """
    findings = detect_brute_force(entries) + detect_injection_attacks(entries)

    incidents = [
        models.Incident(
            title=f["title"],
            rule_name=f["rule_name"],
            severity=f["severity"],
            description=f["description"],
            mitre_technique=f.get("mitre_technique"),
            mitre_tactic=f.get("mitre_tactic"),
            affected_user=f.get("affected_user"),
            affected_ip=f.get("affected_ip"),
            log_file_id=log_file.id,
        )
        for f in findings
    ]

    if incidents:
        db.add_all(incidents)

    return incidents
