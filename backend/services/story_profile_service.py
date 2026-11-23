"""Central story-length profile service (spec section 7). Agents must not duplicate these rules."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

TOKENS_PER_WORD = 1.6  # conservative English-prose assumption used only for sizing output budgets
GLOBAL_MIN_WORDS = 75
GLOBAL_MAX_WORDS = 3000


class UnsupportedStoryProfile(ValueError):
    pass


@dataclass(frozen=True)
class ProfileDef:
    name: str
    target: int
    min: int
    max: int
    structure: str
    chapters: int


# Initial configurable defaults (spec section 7 table).
DEFAULT_PROFILES: tuple[ProfileDef, ...] = (
    ProfileDef("Micro Horror", 100, 75, 150, "single beat: setup, sting", 1),
    ProfileDef("Flash Fiction", 500, 400, 600, "single scene: hook, escalation, twist", 1),
    ProfileDef("Short Horror", 1000, 800, 1200, "three beats: hook, escalation, reveal", 1),
    ProfileDef("Standard Horror", 1250, 1000, 1500, "classic arc: hook, dread build, climax, aftermath", 1),
    ProfileDef("Long Horror", 2000, 1500, 2500, "multi-scene arc in three acts", 3),
    ProfileDef("Premium Feature", 2500, 2000, 3000, "full feature: four movements with layered reveals", 4),
    ProfileDef("Serialized Episode", 1500, 1000, 2000, "episode arc with series hook and cliffhanger", 1),
)

# Platform adaptations are SEPARATE deliverables; the original story is never truncated.
PLATFORM_ADAPTATIONS: dict[str, list[str]] = {
    "substack": ["publish the full approved story; add title, subtitle, SEO description and tags"],
    "youtube": ["separate script/short derived from the story", "never truncate the original story",
                "short-form narration length is its own deliverable"],
    "instagram": ["separate caption and carousel/reel text derived from the story",
                  "never truncate the original story"],
    "reddit": ["separate post version formatted for the target subreddit rules",
               "never truncate the original story; link or split into parts only as a distinct deliverable"],
    "x": ["separate teaser thread; never truncate the original story"],
    "twitter": ["separate teaser thread; never truncate the original story"],
}


@dataclass(frozen=True)
class StoryProfile:
    profile_name: str
    target_words: int
    min_words: int
    max_words: int
    narrative_structure: str
    chapter_count: int
    writer_output_budget: int
    humanisation_budget: int
    continuity_budget: int
    editorial_budget: int
    safety_budget: int
    synopsis_budget: int
    platform: str | None = None
    platform_adaptations: tuple[str, ...] = ()
    series_mode: bool = False
    requested_word_count: int | None = None
    overridden_from: str | None = None  # explicit story_type that could not hold the requested count

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform_adaptations"] = list(self.platform_adaptations)
        return d


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def _budgets(p: ProfileDef, target: int, mx: int) -> dict:
    out = math.ceil(mx * TOKENS_PER_WORD) + 256
    return dict(writer_output_budget=out, humanisation_budget=out,
                continuity_budget=800 + math.ceil(target * 0.1 * TOKENS_PER_WORD),
                editorial_budget=1500, safety_budget=1200, synopsis_budget=400)


def select_story_profile(story_type: str | None = None, requested_word_count: int | None = None,
                         platform: str | None = None, series_mode: bool = False, *,
                         profiles: tuple[ProfileDef, ...] = DEFAULT_PROFILES,
                         min_words: int = GLOBAL_MIN_WORDS, max_words: int = GLOBAL_MAX_WORDS) -> StoryProfile:
    by_key = {_norm(p.name): p for p in profiles}
    if requested_word_count is not None:
        if isinstance(requested_word_count, bool) or not isinstance(requested_word_count, int):
            raise UnsupportedStoryProfile("requested_word_count must be an integer")
        if not (min_words <= requested_word_count <= max_words):
            raise UnsupportedStoryProfile(
                f"requested word count {requested_word_count} outside supported range {min_words}-{max_words}")

    def containing(n: int) -> ProfileDef | None:
        c = [p for p in profiles if p.min <= n <= p.max]
        return min(c, key=lambda p: abs(p.target - n)) if c else None

    chosen: ProfileDef | None
    overridden = None
    if story_type:
        chosen = by_key.get(_norm(story_type))
        if chosen is None:
            raise UnsupportedStoryProfile(f"unknown story type {story_type!r}; supported: "
                                          + ", ".join(p.name for p in profiles))
    elif series_mode and "serialized_episode" in by_key:
        chosen = by_key["serialized_episode"]
    elif requested_word_count is not None:
        chosen = containing(requested_word_count) or min(profiles, key=lambda p: abs(p.target - requested_word_count))
    else:
        chosen = by_key.get("standard_horror") or profiles[0]

    target = requested_word_count if requested_word_count is not None else chosen.target
    if chosen is not None and not (chosen.min <= target <= chosen.max):
        # Honour the request: never silently shrink/grow it. Re-select a profile that can hold it.
        alt = containing(target)
        if alt is None:  # supported globally but between profile ranges
            alt = min(profiles, key=lambda p: abs(p.target - target))
        if story_type and alt.name != chosen.name:
            overridden = chosen.name
        chosen = alt
    mn, mx = chosen.min, chosen.max
    if not (mn <= target <= mx):  # request in a gap between profile ranges
        mn, mx = min(mn, target), max(mx, target)

    plat = None
    adapt: tuple[str, ...] = ()
    if platform:
        plat = _norm(platform)
        if plat not in PLATFORM_ADAPTATIONS:
            raise UnsupportedStoryProfile(f"unsupported platform {platform!r}; supported: "
                                          + ", ".join(sorted(PLATFORM_ADAPTATIONS)))
        adapt = tuple(PLATFORM_ADAPTATIONS[plat])

    return StoryProfile(profile_name=chosen.name, target_words=target, min_words=mn, max_words=mx,
                        narrative_structure=chosen.structure, chapter_count=chosen.chapters,
                        platform=plat, platform_adaptations=adapt, series_mode=bool(series_mode),
                        requested_word_count=requested_word_count, overridden_from=overridden,
                        **_budgets(chosen, target, mx))


def list_profiles(profiles: tuple[ProfileDef, ...] = DEFAULT_PROFILES) -> list[dict]:
    return [asdict(p) for p in profiles]
