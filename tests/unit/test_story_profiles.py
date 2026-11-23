import pytest

from backend.services.story_profile_service import (DEFAULT_PROFILES, UnsupportedStoryProfile, list_profiles,
                                                    select_story_profile)

TABLE = {"Micro Horror": (100, 75, 150), "Flash Fiction": (500, 400, 600), "Short Horror": (1000, 800, 1200),
         "Standard Horror": (1250, 1000, 1500), "Long Horror": (2000, 1500, 2500),
         "Premium Feature": (2500, 2000, 3000), "Serialized Episode": (1500, 1000, 2000)}


@pytest.mark.parametrize("name,vals", TABLE.items())
def test_defaults_table(name, vals):
    p = select_story_profile(story_type=name)
    assert (p.target_words, p.min_words, p.max_words) == vals
    assert p.profile_name == name and p.overridden_from is None


def test_type_normalisation():
    assert select_story_profile("standard_horror").profile_name == "Standard Horror"
    assert select_story_profile("  PREMIUM feature ").profile_name == "Premium Feature"


def test_default_when_nothing_given():
    assert select_story_profile().profile_name == "Standard Horror"


def test_requested_count_honoured_not_shrunk():
    p = select_story_profile(requested_word_count=2500)
    assert p.target_words == 2500 and p.max_words >= 2500 and p.profile_name in ("Long Horror", "Premium Feature")
    p = select_story_profile("Short Horror", 2500)  # explicit type cannot hold request: keep the 2500
    assert p.target_words == 2500 and p.max_words >= 2500 and p.overridden_from == "Short Horror"


def test_requested_within_profile_keeps_profile_range():
    p = select_story_profile("Short Horror", 900)
    assert p.target_words == 900 and (p.min_words, p.max_words) == (800, 1200) and p.profile_name == "Short Horror"


def test_gap_between_ranges_widens_bounds():
    p = select_story_profile(requested_word_count=700)  # between Flash (<=600) and Short (>=800)
    assert p.min_words <= 700 <= p.max_words and p.target_words == 700


@pytest.mark.parametrize("n", [0, 74, 3001, 10_000, -5])
def test_unsupported_counts_raise(n):
    with pytest.raises(UnsupportedStoryProfile):
        select_story_profile(requested_word_count=n)


def test_non_int_count_rejected():
    for bad in (True, 1000.5, "1000"):
        with pytest.raises(UnsupportedStoryProfile):
            select_story_profile(requested_word_count=bad)


def test_unknown_type_and_platform_raise():
    with pytest.raises(UnsupportedStoryProfile):
        select_story_profile(story_type="Epic Saga")
    with pytest.raises(UnsupportedStoryProfile):
        select_story_profile(platform="myspace")


def test_series_mode_defaults_to_episode():
    p = select_story_profile(series_mode=True)
    assert p.profile_name == "Serialized Episode" and p.series_mode
    assert select_story_profile(series_mode=True, requested_word_count=1800).target_words == 1800


def test_platform_adaptations_are_separate_deliverables():
    p = select_story_profile("Standard Horror", platform="YouTube")
    assert p.platform == "youtube"
    assert any("never truncate" in a for a in p.platform_adaptations)
    assert p.target_words == 1250  # original never shortened for platform
    assert select_story_profile().platform_adaptations == ()


def test_budgets_scale_with_length_and_present():
    small, big = select_story_profile("Micro Horror"), select_story_profile("Premium Feature")
    assert big.writer_output_budget > small.writer_output_budget > 0
    for f in ("humanisation_budget", "continuity_budget", "editorial_budget", "safety_budget", "synopsis_budget"):
        assert getattr(big, f) > 0
    assert big.writer_output_budget >= int(big.max_words * 1.0)  # at least a token per word of headroom
    assert big.chapter_count >= 1 and big.narrative_structure


def test_to_dict_and_list_profiles():
    d = select_story_profile("Long Horror", platform="reddit").to_dict()
    assert d["profile_name"] == "Long Horror" and isinstance(d["platform_adaptations"], list)
    assert len(list_profiles()) == len(DEFAULT_PROFILES) == 7


def test_profiles_are_configurable():
    from backend.services.story_profile_service import ProfileDef

    custom = (ProfileDef("Tiny", 50, 40, 60, "x", 1),)
    p = select_story_profile("tiny", profiles=custom, min_words=10, max_words=100)
    assert p.target_words == 50
    with pytest.raises(UnsupportedStoryProfile):
        select_story_profile(requested_word_count=500, profiles=custom, min_words=10, max_words=100)
