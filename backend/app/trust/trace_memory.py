"""Persistent TraceMemory for CovenantOps Agent.

Durable storage of agent runs and trace events. Uses SQLAlchemy so it runs on
SQLite locally (zero setup) and PostgreSQL in production (DATABASE_URL). Falls
back to in-memory if the DB is unavailable, so the demo never breaks.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from sqlalchemy import create_engine, Column, String, DateTime, Text
    from sqlalchemy.orm import declarative_base, sessionmaker
    _SA = True
except Exception:  # pragma: no cover
    _SA = False

_DB_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/covenantops.db")


if _SA:
    Base = declarative_base()

    class AgentRunRow(Base):
        __tablename__ = "agent_runs"
        run_id = Column(String, primary_key=True)
        borrower = Column(String)
        severity = Column(String)
        confidence = Column(String)
        created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
        payload = Column(Text)

    class TraceEventRow(Base):
        __tablename__ = "trace_events"
        id = Column(String, primary_key=True)
        event_type = Column(String)
        run_id = Column(String)
        created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
        payload = Column(Text)


class TraceMemory:
    """Persistent execution memory. Falls back to in-memory on any DB error."""
    def __init__(self, db_url: str = _DB_URL):
        self._mem_runs: Dict[str, dict] = {}
        self._mem_events: List[dict] = []
        self.persistent = False
        if _SA:
            try:
                # ensure sqlite dir exists
                if db_url.startswith("sqlite:///./"):
                    os.makedirs("data", exist_ok=True)
                self._engine = create_engine(db_url, future=True)
                Base.metadata.create_all(self._engine)
                self._Session = sessionmaker(bind=self._engine, future=True)
                self.persistent = True
            except Exception:
                self.persistent = False

    def save_run(self, trace) -> None:
        rec = {
            "run_id": trace.id,
            "borrower": trace.metadata.get("borrower"),
            "severity": trace.metadata.get("severity"),
            "confidence": str(trace.metadata.get("confidence")),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": trace.model_dump(mode="json", by_alias=True),
        }
        if self.persistent:
            try:
                with self._Session() as s:
                    s.merge(AgentRunRow(
                        run_id=rec["run_id"], borrower=rec["borrower"],
                        severity=rec["severity"], confidence=rec["confidence"],
                        payload=json.dumps(rec["payload"]),
                    ))
                    s.commit()
                self.save_event({"event_type": "agent_run_saved", "run_id": trace.id,
                                 "severity": rec["severity"]})
                return
            except Exception:
                pass
        self._mem_runs[trace.id] = rec

    def get_run(self, run_id: str) -> Optional[dict]:
        rec = self.get_run_record(run_id)
        return rec["payload"] if rec else None

    def get_run_record(self, run_id: str) -> Optional[dict]:
        """Full saved record for a run: {payload, created_at}."""
        if self.persistent:
            try:
                with self._Session() as s:
                    row = s.get(AgentRunRow, run_id)
                    if not row:
                        return None
                    return {"payload": json.loads(row.payload),
                            "created_at": row.created_at.isoformat() if row.created_at else None}
            except Exception:
                pass
        rec = self._mem_runs.get(run_id)
        return {"payload": rec["payload"], "created_at": rec.get("created_at")} if rec else None

    def list_runs(self, limit: int = 50) -> List[dict]:
        if self.persistent:
            try:
                with self._Session() as s:
                    rows = s.query(AgentRunRow).order_by(AgentRunRow.created_at.desc()).limit(limit).all()
                    return [{"run_id": r.run_id, "borrower": r.borrower,
                             "severity": r.severity, "confidence": r.confidence,
                             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
            except Exception:
                pass
        return [{"run_id": k, "borrower": v["borrower"], "severity": v["severity"],
                 "confidence": v["confidence"], "created_at": v.get("created_at")}
                for k, v in self._mem_runs.items()][:limit]

    def save_event(self, event: dict) -> None:
        from app.models import new_id
        payload = {"created_at": datetime.now(timezone.utc).isoformat(), **event}
        if self.persistent:
            try:
                with self._Session() as s:
                    s.add(TraceEventRow(id=new_id("evt"),
                                        event_type=str(event.get("event_type", "unknown")),
                                        run_id=event.get("run_id"), payload=json.dumps(payload)))
                    s.commit()
                return
            except Exception:
                pass
        self._mem_events.append(payload)

    def list_events(self, limit: int = 200) -> List[dict]:
        if self.persistent:
            try:
                with self._Session() as s:
                    rows = s.query(TraceEventRow).order_by(TraceEventRow.created_at.desc()).limit(limit).all()
                    return [json.loads(r.payload) for r in rows]
            except Exception:
                pass
        return self._mem_events[-limit:]
