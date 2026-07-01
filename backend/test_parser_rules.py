import pytest
from datetime import datetime, timedelta
from app.parser import parse_log_line
from app.rules import detect_brute_force, detect_injection_attacks
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
