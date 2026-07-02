"""
AI incident summaries (prd.md feature #6: "AI incident summaries").

Builds a tightly-scoped context from an incident's own log file — entries
matching the incident's affected_ip/affected_user, rather than an
arbitrary slice of the whole file — and asks Gemini for a short,
human-readable summary of what happened.
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import ai, models

MAX_CONTEXT_ENTRIES = 20


def _entries_for_incident(db: Session, incident: models.Incident) -> list["models.LogEntry"]:
    """
    Pull the log entries most relevant to *incident*: those from its log
    file whose ip_address or user_name matches the incident's
    affected_ip/affected_user. Falls back to the file's earliest entries
    if the incident has neither set.
    """
    if not incident.log_file_id:
        return []

    query = db.query(models.LogEntry).filter(models.LogEntry.file_id == incident.log_file_id)

    conditions = []
    if incident.affected_ip:
        conditions.append(models.LogEntry.ip_address == incident.affected_ip)
    if incident.affected_user:
        conditions.append(models.LogEntry.user_name == incident.affected_user)
    if conditions:
        query = query.filter(or_(*conditions))

    return query.order_by(models.LogEntry.timestamp).limit(MAX_CONTEXT_ENTRIES).all()


def _build_context(entries: list["models.LogEntry"]) -> str:
    if not entries:
        return "(no related log entries found)"

    lines = []
    for i, entry in enumerate(entries, start=1):
        ts  = entry.timestamp.isoformat() if entry.timestamp else "N/A"
        msg = (entry.message or "").strip()
        lines.append(f"[{i}] {ts} | {msg}")
    return "\n".join(lines)


def _build_prompt(incident: models.Incident, context: str) -> str:
    return (
        f"Summarize the following security incident in 3-5 sentences for a SOC analyst.\n\n"
        f"Rule triggered : {incident.rule_name}\n"
        f"Severity       : {incident.severity}\n"
        f"MITRE Technique: {incident.mitre_technique or 'unknown'} ({incident.mitre_tactic or 'unknown'})\n"
        f"Affected IP    : {incident.affected_ip or 'unknown'}\n"
        f"Affected User  : {incident.affected_user or 'unknown'}\n"
        f"Description    : {incident.description}\n\n"
        f"Related log entries:\n{context}\n\n"
        f"Write a concise plain-English summary of what happened and why it "
        f"matters, ending with one recommended next step."
    )


def summarize_incident(db: Session, incident: models.Incident) -> str:
    """
    Build a short, incident-scoped context and ask Gemini to summarize it.
    Returns the summary text — callers decide when to persist it to
    Incident.summary and commit.
    """
    entries = _entries_for_incident(db, incident)
    context = _build_context(entries)
    prompt = _build_prompt(incident, context)
    return ai.generate_chat_response(prompt)
