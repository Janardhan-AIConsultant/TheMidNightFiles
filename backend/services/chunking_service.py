"""Paragraph-, scene- and chapter-aware chunking with exact reassembly.

Design: chunk cores PARTITION the source text (chunk[i].end == chunk[i+1].start, first start 0,
last end len(text)), so ``"".join(c.text)`` reproduces the original byte-for-byte and no
paragraph can be missing or duplicated. Overlap is supplied as read-only context
(``overlap_before``) taken from the tail of the previous chunk; it is never part of ``text``.
Token counts use an injectable estimator (default: conservative; sums of per-unit estimates are
an upper bound of the whole-chunk estimate).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable

from backend.services.context_budget_service import conservative_estimate

_PARA_SEP = re.compile(r"(?:\r?\n[ \t]*){2,}")
_CHAPTER = re.compile(r"^\s*(#{1,3}\s|chapter\b|part\b|prologue\b|epilogue\b|book\b)", re.I)
_SCENE = re.compile(r"^\s*(?:(?:\*\s*){3,}|-{3,}|_{3,}|#)\s*$")
_SENT_END = re.compile(r"(?<=[.!?…\"”'])\s+")


class ChunkingError(ValueError):
    pass


@dataclass(frozen=True)
class Chunk:
    id: str
    index: int
    start: int
    end: int
    text: str
    hash: str
    story_id: str = ""
    version: int = 0
    content_hash: str = ""
    total: int = 0
    overlap_before: str = ""
    overlap_start: int | None = None


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARA_SEP.split(text) if p.strip()]


class ChunkingService:
    def __init__(self, estimator: Callable[[str], int] = conservative_estimate):
        self.estimate = estimator

    # -- splitting -----------------------------------------------------
    def _units(self, text: str, max_tokens: int) -> list[tuple[int, int, str]]:
        """Partition text into (start, end, kind) units; kind in para|chapter|scene."""
        spans: list[tuple[int, int]] = []
        pos = 0
        for m in _PARA_SEP.finditer(text):
            spans.append((pos, m.end()))
            pos = m.end()
        if pos < len(text):
            spans.append((pos, len(text)))
        units: list[tuple[int, int, str]] = []
        for s, e in spans:
            body = text[s:e].strip()
            kind = "chapter" if _CHAPTER.match(body) else "scene" if _SCENE.match(body) else "para"
            if self.estimate(text[s:e]) > max_tokens:
                units.extend((a, b, "para") if i else (a, b, kind) for i, (a, b) in enumerate(self._split_big(text, s, e, max_tokens)))
            else:
                units.append((s, e, kind))
        return units

    def _split_big(self, text: str, s: int, e: int, max_tokens: int) -> list[tuple[int, int]]:
        """Split an oversize paragraph at sentence boundaries, then at whitespace, keeping a partition."""
        cuts = [s]
        for m in _SENT_END.finditer(text, s, e):
            cuts.append(m.end())
        cuts.append(e)
        out: list[tuple[int, int]] = []
        for a, b in zip(cuts, cuts[1:]):
            if a == b:
                continue
            if self.estimate(text[a:b]) <= max_tokens:
                out.append((a, b))
                continue
            # hard split at whitespace
            step = max(8, max_tokens * 2)
            p = a
            while p < b:
                q = min(b, p + step)
                while q < b and q > p + 1 and self.estimate(text[p:q]) > max_tokens:
                    q = p + max(1, (q - p) * 3 // 4)
                if q < b:
                    ws = text.rfind(" ", p + 1, q)
                    if ws > p:
                        q = ws + 1
                out.append((p, q))
                p = q
        # merge pieces greedily so units stay as large as allowed
        merged: list[tuple[int, int]] = []
        for a, b in out:
            if merged and self.estimate(text[merged[-1][0]:b]) <= max_tokens:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        return merged

    # -- public API ----------------------------------------------------
    def chunk(self, text: str, story_id: str, version: int, max_tokens: int, overlap: int = 0) -> list[Chunk]:
        if max_tokens <= 0:
            raise ChunkingError("max_tokens must be > 0")
        if overlap < 0 or overlap >= max_tokens:
            raise ChunkingError("overlap must be >= 0 and < max_tokens")
        if not text or not text.strip():
            return []
        units = self._units(text, max_tokens)
        groups: list[list[tuple[int, int, str]]] = []
        cur: list[tuple[int, int, str]] = []
        cur_tok = 0
        for u in units:
            t = self.estimate(text[u[0]:u[1]])
            force = u[2] == "chapter" and cur_tok >= 0.4 * max_tokens
            soft = u[2] == "scene" and cur_tok >= 0.5 * max_tokens
            if cur and (cur_tok + t > max_tokens or force or soft):
                groups.append(cur)
                cur, cur_tok = [], 0
            cur.append(u)
            cur_tok += t
        if cur:
            groups.append(cur)

        chash = _sha(text)
        chunks: list[Chunk] = []
        n = len(groups)
        for i, g in enumerate(groups):
            start = 0 if i == 0 else g[0][0]
            end = len(text) if i == n - 1 else g[-1][1]
            ctext = text[start:end]
            ov_text, ov_start = "", None
            if overlap and i > 0:
                acc, take = 0, []
                for u in reversed(groups[i - 1]):
                    t = self.estimate(text[u[0]:u[1]])
                    if acc + t > overlap:
                        break
                    acc += t
                    take.append(u)
                if take:
                    ov_start = take[-1][0]
                    ov_text = text[ov_start:take[0][1]]
            chunks.append(Chunk(id=f"{story_id}-v{version:03d}-c{i:03d}", index=i, start=start, end=end,
                                text=ctext, hash=_sha(ctext), story_id=story_id, version=version,
                                content_hash=chash, total=n, overlap_before=ov_text, overlap_start=ov_start))
        return chunks

    @staticmethod
    def reassemble(chunks: Iterable[Chunk]) -> str:
        return "".join(c.text for c in sorted(chunks, key=lambda c: c.index))

    @staticmethod
    def validate_reassembly(original: str, chunks: list[Chunk]) -> bool:
        problems: list[str] = []
        cs = sorted(chunks, key=lambda c: c.index)
        if not cs:
            if original.strip():
                raise ChunkingError("no chunks for non-empty text")
            return True
        if [c.index for c in cs] != list(range(len(cs))):
            problems.append("chunk indexes are not contiguous from 0 (missing or duplicate chunk)")
        ids = [c.id for c in cs]
        if len(set(ids)) != len(ids):
            problems.append("duplicate chunk ids")
        if cs[0].start != 0:
            problems.append("first chunk does not start at 0")
        if cs[-1].end != len(original):
            problems.append("last chunk does not end at end of text")
        for a, b in zip(cs, cs[1:]):
            if a.end != b.start:
                problems.append(f"gap/overlap between {a.id} and {b.id}")
        for c in cs:
            if original[c.start:c.end] != c.text:
                problems.append(f"{c.id} text does not match source span")
            if _sha(c.text) != c.hash:
                problems.append(f"{c.id} hash mismatch")
        joined = "".join(c.text for c in cs)
        if joined != original:
            problems.append("reassembled text differs from original")
        want, got = Counter(paragraphs(original)), Counter(paragraphs(joined))
        missing, extra = want - got, got - want
        if missing:
            problems.append(f"{sum(missing.values())} paragraph(s) missing")
        if extra:
            problems.append(f"{sum(extra.values())} duplicate/extra paragraph(s)")
        if problems:
            raise ChunkingError("; ".join(problems))
        return True

    @staticmethod
    def coverage(chunks: list[Chunk], reviewed_ids: Iterable[str]) -> float:
        """Fraction of chunk characters whose chunk id has been reviewed (1.0 required for safety PASSED)."""
        reviewed = set(reviewed_ids)
        total = sum(len(c.text) for c in chunks)
        if total == 0:
            return 1.0
        return sum(len(c.text) for c in chunks if c.id in reviewed) / total
