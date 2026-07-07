# Incident Response Playbook — Acme Corp Security Operations

## Purpose

This playbook defines the standard response procedures for the most common
incident classes detected by our monitoring platform: brute-force
authentication attacks, web application injection attempts, privilege
escalation, malicious PowerShell execution, and credential dumping.

## Severity Levels

- **CRITICAL** — active compromise or credential theft in progress. Page the
  on-call security engineer immediately; begin containment within 15 minutes.
- **HIGH** — strong indication of attacker activity (brute force success,
  privilege escalation). Respond within 1 hour during business hours, 2 hours
  otherwise.
- **WARNING/INFO** — suspicious but unconfirmed. Triage within one business day.

## Playbook 1 — Brute-Force Login Attacks (MITRE T1110)

1. Identify the source IP and targeted accounts from the incident detail.
2. Check whether any attempt from that IP subsequently **succeeded**. A
   successful login after repeated failures escalates this to CRITICAL.
3. Block the source IP at the firewall or WAF.
4. Force a password reset on every targeted account, and invalidate active
   sessions for any account the IP successfully accessed.
5. Enable or verify MFA on the targeted accounts.
6. Document the source IP in the threat-intel blocklist.

## Playbook 2 — SQL Injection / XSS Attempts (MITRE T1190)

1. Confirm whether the WAF blocked the request (look for `blocked by WAF` in
   the log line). Blocked probes from the internet are routine; unblocked ones
   are CRITICAL.
2. Review application logs for 200-status responses to similar payloads —
   evidence the injection may have succeeded.
3. If a payload reached the application, snapshot the database audit log and
   check for unexpected reads of the `users` table.
4. Rotate application database credentials if exfiltration is suspected.

## Playbook 3 — Privilege Escalation (MITRE T1548)

1. Verify whether the `sudo`/group-change activity was approved change
   management. Cross-reference the change calendar.
2. Pay special attention to service accounts (names starting `svc-`) invoking
   `sudo` — service accounts should never need interactive root access.
3. Remove unauthorized group memberships immediately and disable the account
   pending investigation.
4. Review everything else that account did in the same session.

## Playbook 4 — Suspicious PowerShell (MITRE T1059.001)

1. Decode any `-EncodedCommand` payload before judging intent.
2. Treat `DownloadString`/`IEX` retrieving code from an external IP as active
   compromise (CRITICAL) — isolate the host from the network.
3. Capture volatile memory before rebooting the host.
4. Search other hosts for the same command line — lateral movement is common.

## Playbook 5 — Credential Dumping (MITRE T1003)

1. `lsass.exe` access, `mimikatz`, or `procdump` against LSASS means every
   credential on that host is presumed stolen.
2. Isolate the host immediately. Do not shut it down before memory capture.
3. Reset passwords for **all** accounts that logged into the host in the last
   30 days, starting with domain admins and service accounts.
4. Revoke and reissue any Kerberos tickets (consider a double krbtgt reset if
   a domain controller is involved).
5. Engage the incident commander; credential dumping on a domain-joined host
   is automatically a major incident.

## Escalation Contacts

- On-call security engineer: PagerDuty rotation "secops-primary"
- Incident commander: PagerDuty rotation "secops-ic"
- Executive notification threshold: any CRITICAL incident open longer than 4 hours
