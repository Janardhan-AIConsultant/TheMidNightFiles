"""Summaries with provenance; stale when source or dependencies change."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Summary


class SummaryService:
    def __init__(self, session: Session):
        self.session = session

    def record(self, source_type: str, source_id: str, source_version: int, source_hash: str, kind: str,
               text: str, prompt_version: str, model: str, dependencies: Optional[dict] = None) -> Summary:
        # a new summary of the same source/kind replaces older valid ones
        for old in self.session.scalars(select(Summary).where(
                Summary.source_type == source_type, Summary.source_id == source_id, Summary.kind == kind,
                Summary.is_valid.is_(True))):
            old.is_valid, old.invalidated_reason = False, "superseded"
        row = Summary(source_type=source_type, source_id=source_id, source_version=source_version,
                      source_hash=source_hash, kind=kind, text=text, prompt_version=prompt_version,
                      model=model, dependencies=dict(dependencies or {}))
        self.session.add(row)
        self.session.commit()
        return row

    def get_current(self, source_type: str, source_id: str, kind: str, source_hash: str,
                    dependencies: Optional[dict] = None, prompt_version: Optional[str] = None) -> Optional[Summary]:
        """Return a valid summary only if source hash, dependencies and prompt version all match."""
        row = self.session.scalar(select(Summary).where(
            Summary.source_type == source_type, Summary.source_id == source_id, Summary.kind == kind,
            Summary.is_valid.is_(True)).order_by(Summary.id.desc()))
        if row is None or row.source_hash != source_hash:
            return None
        if dependencies is not None and row.dependencies != dict(dependencies):
            return None
        if prompt_version is not None and row.prompt_version != prompt_version:
            return None
        return row

    def invalidate_for_source(self, source_type: str, source_id: str, reason: str = "source changed") -> int:
        return self._invalidate(select(Summary).where(
            Summary.source_type == source_type, Summary.source_id == source_id, Summary.is_valid.is_(True)), reason)

    def invalidate_for_dependency(self, dep_key: str, new_hash: str) -> int:
        n = 0
        for row in self.session.scalars(select(Summary).where(Summary.is_valid.is_(True))):
            if dep_key in row.dependencies and row.dependencies[dep_key] != new_hash:
                row.is_valid, row.invalidated_reason = False, f"dependency {dep_key} changed"
                n += 1
        self.session.commit()
        return n

    def _invalidate(self, query, reason: str) -> int:
        rows = list(self.session.scalars(query))
        for r in rows:
            r.is_valid, r.invalidated_reason = False, reason
        self.session.commit()
        return len(rows)
