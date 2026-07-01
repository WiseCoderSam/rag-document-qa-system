from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True) # Maps to Supabase user UUID
    email = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    log_files = relationship("LogFile", back_populates="owner")

class LogFile(Base):
    __tablename__ = "log_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    file_url = Column(String, nullable=False) # Supabase Storage URL or local file path
    status = Column(String, default="processing") # processing, completed, failed
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=False)

    owner = relationship("User", back_populates="log_files")
    entries = relationship("LogEntry", back_populates="log_file", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="log_file")

class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("log_files.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=True)
    severity = Column(String, index=True, default="INFO") # INFO, WARNING, ERROR, CRITICAL, etc.
    ip_address = Column(String, index=True, nullable=True)
    user_name = Column(String, index=True, nullable=True)
    hostname = Column(String, index=True, nullable=True)
    event_id = Column(String, index=True, nullable=True)
    message = Column(Text, nullable=False)
    parsed_json = Column(JSON, nullable=True)

    log_file = relationship("LogFile", back_populates="entries")

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, server_default="") # short human-readable summary
    rule_name = Column(String, index=True, nullable=False) # e.g. "Brute force login"
    severity = Column(String, index=True, default="LOW") # LOW, MEDIUM, HIGH, CRITICAL
    description = Column(Text, nullable=False)
    mitre_technique = Column(String, index=True, nullable=True) # e.g. "T1110"
    mitre_tactic = Column(String, index=True, nullable=True) # e.g. "Credential Access"
    status = Column(String, default="open") # open, investigating, resolved
    summary = Column(Text, nullable=True) # AI generated incident summary
    affected_user = Column(String, index=True, nullable=True)
    affected_ip = Column(String, index=True, nullable=True)
    log_file_id = Column(Integer, ForeignKey("log_files.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    log_file = relationship("LogFile", back_populates="incidents")
