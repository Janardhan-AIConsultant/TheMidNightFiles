"""PII detection/redaction (Microsoft Presidio). Used at two points: inbound (user-supplied topic/notes are redacted
before they reach an LLM) and outbound (the publish gate blocks drafts that contain PII).

Fiction note: PERSON / LOCATION are deliberately NOT in the default entity list. Horror stories are full of invented
names and places; flagging them would block every draft. Only identifiers that can harm a real person are checked."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger("midnight.safety.pii")

DEFAULT_ENTITIES = ("EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "IP_ADDRESS", "US_SSN",
                    "US_PASSPORT", "US_BANK_NUMBER", "CRYPTO", "MEDICAL_LICENSE")


class PiiUnavailable(RuntimeError):
    """The PII engine could not be built. Callers on the publish path must treat this as a block (fail closed)."""


@dataclass(frozen=True)
class PiiHit:
    entity: str
    start: int
    end: int
    score: float


class PiiDetector(Protocol):
    def detect(self, text: str, entities: tuple[str, ...], threshold: float) -> list[PiiHit]: ...


class PresidioDetector:
    """Lazy, thread-safe Presidio analyzer using the small spaCy model (en_core_web_sm)."""

    def __init__(self, model: str = "en_core_web_sm", language: str = "en"):
        self.model, self.language = model, language
        self._engine: Any = None
        self._lock = threading.Lock()

    def _build(self):
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            nlp = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy", "models": [{"lang_code": self.language, "model_name": self.model}],
            }).create_engine()
            return AnalyzerEngine(nlp_engine=nlp, supported_languages=[self.language])
        except Exception as exc:  # missing package, missing spaCy model, ...
            raise PiiUnavailable(
                f"Presidio unavailable ({type(exc).__name__}: {exc}). Install presidio-analyzer and run "
                f"`python -m spacy download {self.model}`.") from exc

    def detect(self, text, entities, threshold):
        with self._lock:
            if self._engine is None:
                self._engine = self._build()
        res = self._engine.analyze(text=text, language=self.language, entities=list(entities),
                                   score_threshold=threshold)
        return [PiiHit(r.entity_type, r.start, r.end, float(r.score)) for r in res]


# Presidio scores a bare phone number at 0.4 (0.75 with context words like "phone"), so the global 0.5 would miss it.
ENTITY_THRESHOLDS = {"PHONE_NUMBER": 0.4}


class PiiService:
    def __init__(self, detector: PiiDetector | None = None, entities: tuple[str, ...] = DEFAULT_ENTITIES,
                 threshold: float = 0.5, entity_thresholds: dict[str, float] | None = None):
        self.detector = detector or PresidioDetector()
        self.entities, self.threshold = tuple(entities), threshold
        self.entity_thresholds = {**ENTITY_THRESHOLDS, **(entity_thresholds or {})}

    def scan(self, text: str) -> list[PiiHit]:
        if not text or not text.strip():
            return []
        floor = min([self.threshold, *self.entity_thresholds.values()])
        hits = self.detector.detect(text, self.entities, floor)
        return sorted((h for h in hits if h.score >= self.entity_thresholds.get(h.entity, self.threshold)),
                      key=lambda h: h.start)

    def redact(self, text: str) -> tuple[str, list[PiiHit]]:
        """Replace each hit with <ENTITY>; overlapping hits collapse to the earliest/widest."""
        hits = self.scan(text)
        out, pos, kept = [], 0, []
        for h in hits:
            if h.start < pos:
                continue
            out.append(text[pos:h.start])
            out.append(f"<{h.entity}>")
            pos = h.end
            kept.append(h)
        out.append(text[pos:])
        return "".join(out), kept


_SHARED: PresidioDetector | None = None
_SHARED_LOCK = threading.Lock()


def shared_detector() -> PresidioDetector:
    """One analyzer per process: loading the spaCy model is the expensive part."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = PresidioDetector()
        return _SHARED
