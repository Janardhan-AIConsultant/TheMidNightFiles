"""Shared builders for agent / workflow tests (FakeLLMClient only - no network, no real publishing)."""
from __future__ import annotations

import itertools
import json
from contextlib import contextmanager

from sqlalchemy.orm import sessionmaker

from backend.agents import AgentConfig
from backend.config import Settings
from backend.database import init_db, make_engine
from backend.orchestration.context import build_context
from backend.orchestration.workflow_config import WorkflowConfig
from backend.orchestration.workflow_service import WorkflowService
from backend.services.cache_service import CacheService
from backend.services.llm_client import FakeLLMClient

MODEL = "fake-model"
TINY = "tiny-model"
MID = "mid-model"

REGISTRY = [
    {"provider": "fake", "model_id": MODEL, "context_limit": 100000, "max_output": 8000, "tools": True,
     "structured": True},
    {"provider": "fake", "model_id": MID, "context_limit": 6000, "max_output": 1500, "tools": True,
     "structured": True},
    {"provider": "fake", "model_id": TINY, "context_limit": 2500, "max_output": 400, "tools": True,
     "structured": True},
]

PARA = ("The lighthouse keeper heard the knocking again, slow and patient, from beneath the floorboards of the "
        "lamp room where no door had ever been built. ")


def story_text(paragraphs: int = 6, tag: str = "") -> str:
    return "\n\n".join(f"{PARA * 2}{tag} Part {i}." for i in range(paragraphs))


def finding(sev="medium", category="structure", issue="Weak middle"):
    return {"severity": sev, "issue": issue, "location": "paragraph 2", "explanation": "because",
            "recommendation": "fix it", "category": category}


PLANNER = {"working_title": "The Knocking Below", "genre": "horror", "subgenre": "gothic", "story_type": "standalone",
           "target_word_count": 300, "audience": "adults", "hook": "Knocking from nowhere", "synopsis": "A keeper "
           "hears knocking beneath a floor with no door.", "characters": ["Mara"], "setting": "lighthouse"}
IMAGES = {"assets": [{"kind": k, "aspect_ratio": a, "prompt": f"cinematic {k}", "alt_text": k}
                     for k, a in (("cover", "2:3"), ("article", "16:9"), ("youtube_thumbnail", "16:9"),
                                  ("instagram", "4:5"))]}
DIST = {"platforms": {
    "substack": {"title": "t", "body": "b", "seo_title": "s", "seo_description": "d", "tags": ["horror"]},
    "youtube_shorts": {"hook": "h", "narration": "n", "script": "s", "title": "t", "description": "d",
                       "hashtags": ["#a"]},
    "instagram_reels": {"hook": "h", "script": "s", "narration": "n", "description": "d", "hashtags": ["#a"]},
    "reddit": {"title": "t", "body": "b", "discussion_question": "q", "subreddits": ["r/nosleep"]}}}
OK_EDITORIAL = {"status": "APPROVED", "findings": [], "scores": {"hook": 8}, "reviewed_complete": True}
OK_SAFETY = {"status": "PASSED", "findings": [], "reviewed_complete": True}
OK_CONTINUITY = {"status": "CONSISTENT", "findings": []}


_COUNTER = itertools.count(1)


def _writer(req):
    return {"title": "The Knocking Below", "text": story_text(6, tag=f"w{next(_COUNTER)}")}


def _humanise(req):
    return {"text": json.loads(req.user)["story_text"] + " Polished.", "changes": ["rhythm"]}


def default_responses() -> dict:
    return {"planner": PLANNER, "writer": _writer, "humanisation": _humanise, "continuity": OK_CONTINUITY,
            "editorial": OK_EDITORIAL, "safety": OK_SAFETY, "image": IMAGES, "distribution": DIST}


def gen_image(spec, story_id, version):
    """Importable image tool for IMAGE_GENERATOR=tests.workflows.support:gen_image (no real backend)."""
    return f"{story_id}/v{version}/{spec['kind']}.png"


def make_settings(tmp_path, **kw) -> Settings:
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(REGISTRY), encoding="utf-8")
    return Settings(_env_file=None, cache_directory=str(tmp_path / "cache"), log_dir=str(tmp_path / "logs"),
                    data_dir=str(tmp_path), model_registry_file=str(reg), openai_model=MODEL,
                    cache_lock_timeout_seconds=2, cache_lock_stale_seconds=5, langsmith_tracing=False, **kw)


class Env:
    """engine + session factory + settings + context/service wired to a FakeLLMClient."""

    def __init__(self, tmp_path, llm: FakeLLMClient | None = None, model: str = MODEL, cache: bool = True,
                 max_revisions: int = 3, inline: bool = True):
        self.tmp = tmp_path
        self.settings = make_settings(tmp_path)
        self.engine = make_engine(f"sqlite:///{(tmp_path / 'biz.db').as_posix()}")
        init_db(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.llm = llm or FakeLLMClient(default_responses())
        self.cache = CacheService(self.settings) if cache else None
        self.model = model
        self.max_revisions = max_revisions
        self.inline = inline
        self.refs: list = []
        self.ckpt = str(tmp_path / "checkpoints.db")
        self.service = self.new_service()

    @contextmanager
    def session_factory(self):
        s = self.Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def new_service(self, llm=None) -> WorkflowService:
        def gen_image(spec, story_id, version):
            ref = f"{story_id}/v{version}/{spec['kind']}.png"
            self.refs.append(ref)
            return ref

        ctx = build_context(
            llm or self.llm, self.settings, self.session_factory, self.cache,
            agent_config=AgentConfig(model_id=self.model, backoff_base_s=0, timeout_s=10, max_retries=2),
            config=WorkflowConfig(max_revision_attempts=self.max_revisions, checkpoint_path=self.ckpt),
            extra_tools={"image": {"generate_image": gen_image}}, tracing=False)
        return WorkflowService(ctx, self.ckpt, inline=self.inline)

    @property
    def ctx(self):
        return self.service.ctx

    def story_service(self, s):
        return self.ctx.story_service(s)

    def versions(self, story_id):
        with self.session_factory() as s:
            return [(r.version, r.kind) for r in self.story_service(s).list_revisions(story_id)]

    def run(self, request=None, **kw) -> str:
        req = {"workflow_type": "story_generation", "requested_word_count": 300}
        req.update(request or {})
        return self.service.start(req)
