import time

from sqlalchemy.orm import Session

from . import models


def process_log_file_task(file_id: int, db: Session) -> None:
    """
    Simulates log parsing/normalization for an uploaded log file.
    Runs in the background after the upload response has already been sent.
    """
    time.sleep(5)

    log_file = db.query(models.LogFile).filter(models.LogFile.id == file_id).first()
    if log_file:
        log_file.status = "completed"
        db.commit()

    db.close()
