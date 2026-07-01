import os
import google.generativeai as genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Initialize the Gemini API client if the key is provided
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> list[float]:
    """
    Generate a 768-dimensional text embedding using text-embedding-004.
    Falls back to a zero-vector when no API key is configured.
    """
    if not GEMINI_API_KEY:
        return [0.0] * 768

    try:
        response = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type="retrieval_document",
        )
        return response["embedding"]
    except Exception as e:
        print(f"[ai] Error generating embedding: {e}")
        return [0.0] * 768


# ---------------------------------------------------------------------------
# Chat / RAG answer generation
# ---------------------------------------------------------------------------

def generate_chat_response(prompt: str, context: str = "") -> str:
    """
    Generate a response from gemini-1.5-flash acting as a SOC analyst.
    """
    if not GEMINI_API_KEY:
        return (
            "Gemini API Key is not configured. "
            "Please set the GEMINI_API_KEY environment variable to enable AI investigations."
        )

    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=(
                "You are an expert Security Operations Center (SOC) analyst. "
                "Your task is to investigate logs, summarize threats, map suspicious "
                "behavior to MITRE ATT&CK techniques, and answer user investigation "
                "queries based on the provided log context."
            ),
        )

        full_content = prompt
        if context:
            full_content = (
                f"Log context for investigation:\n---\n{context}\n---\n\n"
                f"User Question: {prompt}"
            )

        response = model.generate_content(
            full_content,
            generation_config={"temperature": 0.2},
        )
        return response.text
    except Exception as e:
        return f"Error communicating with Gemini API: {e}"


# ---------------------------------------------------------------------------
# RAG answer helper
# ---------------------------------------------------------------------------

def answer_query(question: str, context_entries: list) -> str:
    """
    Format *context_entries* (LogEntry objects) into a numbered excerpt block
    and ask Gemini to answer *question* grounded in that context.
    """
    if not context_entries:
        return (
            "No logs have been ingested yet. "
            "Please upload a log file first."
        )

    lines = []
    for i, entry in enumerate(context_entries, start=1):
        ts  = entry.timestamp.isoformat() if entry.timestamp else "N/A"
        sev = entry.severity or "INFO"
        msg = (entry.message or "").strip()
        lines.append(f"[{i}] {ts} | {sev} | {msg}")

    context_block = "\n".join(lines)
    return generate_chat_response(question, context_block)


# ---------------------------------------------------------------------------
# Incident summarization helper
# ---------------------------------------------------------------------------

def summarize_incident(incident, related_entries: list) -> str:
    """
    Build a structured prompt from an Incident and its related LogEntry rows
    and ask Gemini for a concise threat summary.
    """
    # Build entry excerpt (cap at 20 lines to stay within token budget)
    log_lines = []
    for i, entry in enumerate(related_entries[:20], start=1):
        ts  = entry.timestamp.isoformat() if entry.timestamp else "N/A"
        msg = (entry.message or "").strip()
        log_lines.append(f"  [{i}] {ts} | {msg}")

    log_block = "\n".join(log_lines) if log_lines else "  (no related log entries found)"

    prompt = (
        f"You are analyzing a security incident detected by an automated rule.\n\n"
        f"## Incident Metadata\n"
        f"- Rule triggered : {incident.rule_name}\n"
        f"- Severity       : {incident.severity}\n"
        f"- MITRE Technique: {incident.mitre_technique} ({incident.mitre_tactic})\n"
        f"- Affected IP    : {incident.affected_ip or 'unknown'}\n"
        f"- Affected User  : {incident.affected_user or 'unknown'}\n"
        f"- Description    : {incident.description}\n\n"
        f"## Related Log Entries\n"
        f"{log_block}\n\n"
        f"Please provide:\n"
        f"1. A one-paragraph threat narrative describing what happened.\n"
        f"2. The attacker's likely goal.\n"
        f"3. Affected assets.\n"
        f"4. Recommended immediate response actions."
    )

    return generate_chat_response(prompt)
