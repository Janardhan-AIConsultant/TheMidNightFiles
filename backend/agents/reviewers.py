"""Continuity, Editorial and Global Safety reviewers with multi-section review and coverage accounting."""
from __future__ import annotations

from typing import ClassVar

from backend.agents.base import AgentFailure, AgentResult, BaseAgent, Usage
from backend.agents.content import section_token_limit
from backend.agents.schemas import (AggregatedReview, ContinuityOutput, EditorialOutput, ReviewInput, SafetyOutput)
from backend.services.chunking_service import ChunkingService

SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class SectionedReviewer(BaseAgent):
    input_model = ReviewInput
    # statuses ordered most to least severe; ``ok_status`` requires every section complete and OK
    status_priority: ClassVar[tuple[str, ...]] = ()
    ok_status: ClassVar[str] = ""
    incomplete_status: ClassVar[str] = "HUMAN_REVIEW_REQUIRED"

    def expected_output_tokens(self, inp):
        return int(inp.profile.get(f"{self.agent_id}_budget") or 1500)

    def split(self, text: str, story_id: str | None, version: int | None, profile: dict | None = None):
        limit = section_token_limit(self, self.expected_output_tokens(ReviewInput(story_text="x", profile=profile or {})), 800)
        return ChunkingService().chunk(text, story_id or "story", version or 0, limit)

    def section_complete(self, out) -> bool:
        return True

    def review_story(self, text: str, profile: dict, series_context: dict, story_id: str, version: int,
                     workflow_id: str | None = None) -> tuple[AggregatedReview, Usage]:
        chunks = self.split(text, story_id, version, profile)
        usage, done, failed, outs, errs = Usage(), set(), 0, [], []
        findings: list[dict] = []
        for c in chunks:
            r: AgentResult = self.run(ReviewInput(story_text=c.text, profile=profile, series_context=series_context,
                                                  section=c.index, total_sections=len(chunks), story_id=story_id,
                                                  version=version, workflow_id=workflow_id))
            usage.add(r.usage)
            if not r.ok:
                failed += 1
                errs.append(r.error)
                continue
            outs.append(r.output)
            findings += [f.model_dump() for f in r.output.findings]
            if self.section_complete(r.output):
                done.add(c.id)
        if failed == len(chunks):  # nothing reviewed at all -> hard failure, never a status
            raise AgentFailure(errs[0])
        coverage = ChunkingService.coverage(chunks, done)
        status = self.aggregate_status(outs, findings, coverage, failed)
        if failed:
            findings.append({"severity": "high", "issue": f"{failed} of {len(chunks)} sections could not be reviewed",
                             "location": "sections", "explanation": "; ".join(e.message for e in errs)[:300],
                             "recommendation": "Re-run the review or escalate to a human reviewer.",
                             "category": "coverage"})
        return AggregatedReview(status=status, findings=findings, coverage=round(coverage, 6), sections=len(chunks),
                                failed_sections=failed, scores=self.merge_scores(outs)), usage

    def merge_scores(self, outs) -> dict:
        return {}

    def aggregate_status(self, outs, findings, coverage, failed) -> str:
        statuses = {o.status for o in outs}
        for s in self.status_priority:
            if s in statuses:
                return s
        return self.ok_status if coverage >= 1.0 and not failed else self.incomplete_status


class ContinuityAgent(SectionedReviewer):
    agent_id = "continuity"
    output_model = ContinuityOutput
    cache_namespace = "continuity"
    allowed_tools = frozenset({"series_bible"})
    context_policy = "current story + only the relevant series-bible sections"
    status_priority = ("HUMAN_REVIEW_REQUIRED", "ISSUES_FOUND")
    ok_status = "CONSISTENT"

    def aggregate_status(self, outs, findings, coverage, failed):
        s = super().aggregate_status(outs, findings, coverage, failed)
        return "HUMAN_REVIEW_REQUIRED" if (failed or coverage < 1.0) and s == "CONSISTENT" else s


class EditorialAgent(SectionedReviewer):
    agent_id = "editorial"
    output_model = EditorialOutput
    cache_namespace = "editorial"
    allowed_tools = frozenset({"editorial_criteria"})
    context_policy = "complete narrative reviewed section by section; a synopsis alone is never sufficient"
    status_priority = ("REJECTED", "HUMAN_REVIEW_REQUIRED", "NEEDS_REVISION")
    ok_status = "APPROVED"

    def section_complete(self, out):
        return out.reviewed_complete

    def aggregate_status(self, outs, findings, coverage, failed):
        s = super().aggregate_status(outs, findings, coverage, failed)
        if s == "APPROVED" and (failed or coverage < 1.0):
            return "HUMAN_REVIEW_REQUIRED"  # approval requires the complete narrative
        return s

    def merge_scores(self, outs):
        merged: dict = {}
        for o in outs:
            for k, v in o.scores.items():
                if isinstance(v, (int, float)):
                    merged.setdefault(k, []).append(v)
        return {k: round(sum(v) / len(v), 3) for k, v in merged.items()}


class SafetyAgent(SectionedReviewer):
    agent_id = "safety"
    output_model = SafetyOutput
    cache_namespace = "safety"
    allowed_tools = frozenset({"safety_policies"})
    context_policy = "every section of the story plus safety policies; coverage must be 1.0 for PASSED"
    status_priority = ("BLOCKED", "HUMAN_REVIEW_REQUIRED", "NEEDS_REVISION")
    ok_status = "PASSED"

    def section_complete(self, out):
        return out.reviewed_complete

    def aggregate_status(self, outs, findings, coverage, failed):
        # critical findings always block, regardless of what the model's own status said (no quality override)
        if any(str(f.get("severity")).lower() == "critical" for f in findings):
            return "BLOCKED"
        s = super().aggregate_status(outs, findings, coverage, failed)
        if s == "PASSED" and (failed or coverage < 1.0):
            return "HUMAN_REVIEW_REQUIRED"
        return s
