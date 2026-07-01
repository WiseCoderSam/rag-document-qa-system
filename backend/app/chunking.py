"""
Log entry chunking — groups LogEntry rows into overlapping text windows
so that large log files can be indexed semantically at a coarser granularity
without hitting embedding token limits.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import LogEntry

CHUNK_SIZE = 10    # number of log lines per chunk
CHUNK_OVERLAP = 2  # lines shared between adjacent chunks


def _entry_to_line(entry) -> str:
    ts  = entry.timestamp.isoformat() if entry.timestamp else "N/A"
    sev = entry.severity or "INFO"
    msg = (entry.message or "").strip()
    return f"{ts} | {sev} | {msg}"


def chunk_entries(entries: list) -> list[dict]:
    """
    Slide a window of *CHUNK_SIZE* log lines over *entries*, producing dicts:
      {
        "text"      : str,          # joined log lines for embedding
        "entry_ids" : list[int],    # LogEntry.id values in this chunk
      }

    When there are fewer entries than CHUNK_SIZE, a single chunk is produced.
    """
    if not entries:
        return []

    chunks: list[dict] = []
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)

    i = 0
    while i < len(entries):
        window = entries[i : i + CHUNK_SIZE]
        lines  = [_entry_to_line(e) for e in window]
        chunks.append(
            {
                "text"      : "\n".join(lines),
                "entry_ids" : [e.id for e in window],
            }
        )
        if i + CHUNK_SIZE >= len(entries):
            break
        i += step

    return chunks
