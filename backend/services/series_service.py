"""Series management with an immutable, versioned series bible."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import SeriesContinuity, Story, StorySeries

BIBLE_SECTIONS = ("characters", "relationships", "locations", "timeline", "objects",
                  "supernatural_rules", "past_events", "unresolved_mysteries", "established_facts")


class SeriesError(Exception):
    pass


class SeriesService:
    def __init__(self, session: Session):
        self.session = session

    def create_series(self, name: str, description: str = "") -> StorySeries:
        if self.session.scalar(select(StorySeries).where(StorySeries.name == name)):
            raise SeriesError(f"series {name!r} exists")
        s = StorySeries(name=name, description=description)
        self.session.add(s)
        self.session.commit()
        return s

    def get_series(self, series_id: int) -> StorySeries:
        s = self.session.get(StorySeries, series_id)
        if s is None:
            raise SeriesError(f"unknown series {series_id}")
        return s

    def attach_story(self, story_id: str, series_id: int, episode_number: Optional[int] = None) -> Story:
        self.get_series(series_id)
        story = self.session.get(Story, story_id)
        if story is None:
            raise SeriesError(f"unknown story {story_id}")
        story.series_id, story.episode_number, story.story_type = series_id, episode_number, "series"
        self.session.commit()
        return story

    def save_bible(self, series_id: int, bible: dict, author: str = "system") -> SeriesContinuity:
        """Create a NEW bible version (never mutates an existing one)."""
        series = self.get_series(series_id)
        unknown = set(bible) - set(BIBLE_SECTIONS)
        if unknown:
            raise SeriesError(f"unknown bible sections: {sorted(unknown)}")
        payload = copy.deepcopy(bible)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        row = SeriesContinuity(series_id=series_id, version=series.current_bible_version + 1, bible=payload,
                               content_hash=digest, author=author)
        series.current_bible_version = row.version
        self.session.add(row)
        self.session.commit()
        return row

    def get_bible(self, series_id: int, version: Optional[int] = None) -> SeriesContinuity:
        q = select(SeriesContinuity).where(SeriesContinuity.series_id == series_id)
        q = q.where(SeriesContinuity.version == version) if version else q.order_by(SeriesContinuity.version.desc())
        row = self.session.scalars(q).first()
        if row is None:
            raise SeriesError(f"no bible for series {series_id} version={version}")
        return row

    def list_bible_versions(self, series_id: int) -> list[SeriesContinuity]:
        return list(self.session.scalars(select(SeriesContinuity).where(
            SeriesContinuity.series_id == series_id).order_by(SeriesContinuity.version)))

    def relevant_context(self, series_id: int, sections: Optional[list[str]] = None) -> dict:
        """Only the requested bible sections of the latest version (for the continuity reviewer)."""
        bible = self.get_bible(series_id).bible
        keys = sections or list(bible)
        return {k: bible[k] for k in keys if k in bible}
