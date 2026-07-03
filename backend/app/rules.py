import re
from collections import defaultdict
from datetime import timedelta
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


# --- Privilege escalation ---------------------------------------------

PRIVILEGE_ESCALATION_SIGNATURES = [
    (re.compile(r"\bsudo\b", re.IGNORECASE), "sudo invocation"),
    (re.compile(r"\brunas\b", re.IGNORECASE), "runas invocation"),
    (re.compile(r"added to (the )?administrators? group", re.IGNORECASE), "user added to admin group"),
    (re.compile(r"privilege escalation", re.IGNORECASE), "explicit privilege escalation mention"),
]

# Windows Security-log event IDs commonly associated with privilege changes:
# 4672 = special privileges assigned to new logon, 4728/4732 = member added
# to a security-enabled global/local group, 4756 = member added to a
# security-enabled universal group.
PRIVILEGE_ESCALATION_EVENT_IDS = {"4672", "4728", "4732", "4756"}


def detect_privilege_escalation(entries: Iterable[models.LogEntry]) -> List[dict]:
    """
    Flags log entries indicating a privilege change: sudo/runas usage, a
    user being added to an admin group, or a Windows privilege-related
    event ID (see PRIVILEGE_ESCALATION_EVENT_IDS).
    """
    findings = []
    for entry in entries:
        message = entry.message or ""
        matched_label = None

        if entry.event_id and str(entry.event_id) in PRIVILEGE_ESCALATION_EVENT_IDS:
            matched_label = f"Windows Event ID {entry.event_id}"
        else:
            for pattern, label in PRIVILEGE_ESCALATION_SIGNATURES:
                if pattern.search(message):
                    matched_label = label
                    break

        if matched_label:
            findings.append({
                "title": f"Possible privilege escalation ({matched_label})",
                "rule_name": "Privilege escalation",
                "severity": "HIGH",
                "description": (
                    f"Log entry matched privilege escalation signature \"{matched_label}\": {message[:300]}"
                ),
                "mitre_technique": "T1548",
                "mitre_tactic": "Privilege Escalation",
                "affected_user": entry.user_name,
                "affected_ip": entry.ip_address,
            })

    return findings


# --- Suspicious PowerShell ----------------------------------------------

POWERSHELL_SIGNATURES = [
    (re.compile(r"-enc(odedcommand)?\b", re.IGNORECASE), "encoded command flag"),
    (re.compile(r"invoke-expression|\biex\(", re.IGNORECASE), "Invoke-Expression"),
    (re.compile(r"downloadstring|downloadfile", re.IGNORECASE), "remote download cmdlet"),
    (re.compile(r"-nop\b.*-w(indowstyle)?\s+hidden", re.IGNORECASE), "hidden window flags"),
    (re.compile(r"frombase64string", re.IGNORECASE), "base64-decoded payload"),
]


def detect_suspicious_powershell(entries: Iterable[models.LogEntry]) -> List[dict]:
    """
    Flags PowerShell command lines using signatures commonly seen in
    fileless-malware / living-off-the-land techniques (encoded commands,
    Invoke-Expression, remote downloads, hidden windows, base64 payloads).
    Requires "powershell" to appear in the message to avoid false positives
    on unrelated log lines that happen to contain a matched keyword.
    """
    findings = []
    for entry in entries:
        message = entry.message or ""
        if "powershell" not in message.lower():
            continue

        for pattern, label in POWERSHELL_SIGNATURES:
            if pattern.search(message):
                findings.append({
                    "title": f"Suspicious PowerShell usage ({label})",
                    "rule_name": "Suspicious PowerShell",
                    "severity": "HIGH",
                    "description": (
                        f"Log entry matched suspicious PowerShell signature \"{label}\": {message[:300]}"
                    ),
                    "mitre_technique": "T1059.001",
                    "mitre_tactic": "Execution",
                    "affected_user": entry.user_name,
                    "affected_ip": entry.ip_address,
                })
                break

    return findings


# --- Credential dumping ---------------------------------------------------

CREDENTIAL_DUMPING_SIGNATURES = [
    (re.compile(r"mimikatz", re.IGNORECASE), "mimikatz"),
    (re.compile(r"sekurlsa", re.IGNORECASE), "sekurlsa module"),
    (re.compile(r"lsass\.exe", re.IGNORECASE), "lsass.exe access"),
    (re.compile(r"procdump.*lsass", re.IGNORECASE), "procdump against lsass"),
    (re.compile(r"ntds\.dit", re.IGNORECASE), "ntds.dit extraction"),
    (re.compile(r"reg(\.exe)?\s+save\s+hklm\\sam", re.IGNORECASE), "SAM hive dump"),
]


def detect_credential_dumping(entries: Iterable[models.LogEntry]) -> List[dict]:
    """
    Flags log entries matching known credential-dumping tooling/techniques
    (mimikatz, LSASS access/dumping, NTDS.dit extraction, SAM hive dumps).
    """
    findings = []
    for entry in entries:
        message = entry.message or ""
        for pattern, label in CREDENTIAL_DUMPING_SIGNATURES:
            if pattern.search(message):
                findings.append({
                    "title": f"Possible credential dumping ({label})",
                    "rule_name": "Credential dumping",
                    "severity": "CRITICAL",
                    "description": (
                        f"Log entry matched credential dumping signature \"{label}\": {message[:300]}"
                    ),
                    "mitre_technique": "T1003",
                    "mitre_tactic": "Credential Access",
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
    findings = (
        detect_brute_force(entries)
        + detect_injection_attacks(entries)
        + detect_privilege_escalation(entries)
        + detect_suspicious_powershell(entries)
        + detect_credential_dumping(entries)
    )

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
