import dataclasses
import random

import pytest

from backend.services.chunking_service import Chunk, ChunkingError, ChunkingService, paragraphs
from backend.services.context_budget_service import conservative_estimate

svc = ChunkingService()


def make_story(n_paras=40, words=30, seed=1, scene_every=0, chapters=False):
    rnd = random.Random(seed)
    vocab = "the dark house whispered under cold moon and nobody answered while rain kept falling".split()
    out = []
    for i in range(n_paras):
        if chapters and i % 10 == 0:
            out.append(f"## Chapter {i // 10 + 1}")
        if scene_every and i and i % scene_every == 0:
            out.append("* * *")
        out.append(f"P{i}. " + " ".join(rnd.choice(vocab) for _ in range(words)) + ".")
    return "\n\n".join(out)


def test_roundtrip_exact_and_valid():
    t = make_story()
    chunks = svc.chunk(t, "STORY-0001", 2, max_tokens=300)
    assert len(chunks) > 3
    assert svc.reassemble(chunks) == t
    assert svc.validate_reassembly(t, chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].start == 0 and chunks[-1].end == len(t)
    assert all(a.end == b.start for a, b in zip(chunks, chunks[1:]))


def test_stable_ids_hashes_and_metadata():
    t = make_story()
    a = svc.chunk(t, "STORY-0001", 2, 300)
    b = svc.chunk(t, "STORY-0001", 2, 300)
    assert [c.id for c in a] == [c.id for c in b] and [c.hash for c in a] == [c.hash for c in b]
    assert a[0].id == "STORY-0001-v002-c000"
    assert {c.version for c in a} == {2} and {c.story_id for c in a} == {"STORY-0001"}
    assert len({c.content_hash for c in a}) == 1 and a[0].total == len(a)
    assert len({c.id for c in a}) == len(a)
    assert svc.chunk(t + " changed", "STORY-0001", 2, 300)[0].content_hash != a[0].content_hash


def test_chunks_respect_token_limit():
    t = make_story(60, 40)
    for mt in (120, 300, 1000):
        for c in svc.chunk(t, "S", 1, mt):
            assert conservative_estimate(c.text) <= mt, (mt, c.id)


def test_no_paragraph_split_when_paragraphs_fit():
    t = make_story(30, 25)
    chunks = svc.chunk(t, "S", 1, 400)
    for c in chunks:
        for p in paragraphs(c.text):
            assert p in paragraphs(t)  # every chunk paragraph is a whole original paragraph


def test_single_chunk_for_small_text():
    t = "One short paragraph."
    c = svc.chunk(t, "S", 1, 1000)
    assert len(c) == 1 and c[0].text == t


def test_empty_and_whitespace():
    assert svc.chunk("", "S", 1, 100) == []
    assert svc.chunk("  \n\n ", "S", 1, 100) == []
    assert svc.validate_reassembly("", [])


def test_oversize_paragraph_split_at_sentences_then_words():
    sentences = " ".join(f"Sentence number {i} is rather eerie." for i in range(60))
    t = "Intro.\n\n" + sentences + "\n\nOutro."
    chunks = svc.chunk(t, "S", 1, 80)
    assert svc.reassemble(chunks) == t and svc.validate_reassembly(t, chunks)
    assert all(conservative_estimate(c.text) <= 80 for c in chunks)
    blob = "x" * 5000  # no whitespace at all
    cs = svc.chunk(blob, "S", 1, 100)
    assert svc.reassemble(cs) == blob and all(conservative_estimate(c.text) <= 100 for c in cs)
    words = " ".join(["word"] * 2000)  # no sentence punctuation
    cs = svc.chunk(words, "S", 1, 100)
    assert svc.reassemble(cs) == words and all(conservative_estimate(c.text) <= 100 for c in cs)


def test_chapter_headings_start_new_chunks():
    t = make_story(40, 30, chapters=True)
    chunks = svc.chunk(t, "S", 1, 700)
    for c in chunks[1:]:
        first = c.text.lstrip().splitlines()[0]
        # whenever a chapter heading is the first paragraph of a chunk we preserved the boundary;
        # headings must never be stranded as the last paragraph of a chunk
        assert not paragraphs(c.text)[-1].startswith("## Chapter")
    assert any(c.text.lstrip().startswith("## Chapter") for c in chunks[1:])


def test_scene_breaks_preferred_boundaries():
    t = make_story(40, 30, scene_every=5)
    chunks = svc.chunk(t, "S", 1, 450)
    assert any(c.text.lstrip().startswith("* * *") for c in chunks[1:])
    assert svc.validate_reassembly(t, chunks)


def test_overlap_context_not_part_of_core():
    t = make_story()
    chunks = svc.chunk(t, "S", 1, 300, overlap=80)
    assert chunks[0].overlap_before == ""
    withov = [c for c in chunks[1:] if c.overlap_before]
    assert withov
    for c in withov:
        prev = chunks[c.index - 1]
        assert prev.text.endswith(c.overlap_before) or c.overlap_before in prev.text
        assert conservative_estimate(c.overlap_before) <= 80 + 5 * 1  # unit sums are an upper bound
        assert t[c.overlap_start:c.overlap_start + len(c.overlap_before)] == c.overlap_before
    assert svc.reassemble(chunks) == t  # overlap never duplicates content


def test_invalid_params():
    with pytest.raises(ChunkingError):
        svc.chunk("x", "S", 1, 0)
    with pytest.raises(ChunkingError):
        svc.chunk("x", "S", 1, 100, overlap=100)
    with pytest.raises(ChunkingError):
        svc.chunk("x", "S", 1, 100, overlap=-1)


def test_repeated_identical_paragraphs_are_legit():
    t = "The knocking.\n\nSilence.\n\nThe knocking.\n\nSilence.\n\nThe knocking."
    chunks = svc.chunk(t, "S", 1, 8)
    assert len(chunks) > 1 and svc.validate_reassembly(t, chunks)


# ---------------- validation catches defects ----------------
def _chunks():
    t = make_story(20, 30)
    return t, svc.chunk(t, "S", 1, 250)


def test_detects_missing_chunk():
    t, cs = _chunks()
    with pytest.raises(ChunkingError, match="missing|gap|contiguous|end"):
        svc.validate_reassembly(t, cs[:1] + cs[2:])


def test_detects_duplicate_chunk():
    t, cs = _chunks()
    with pytest.raises(ChunkingError):
        svc.validate_reassembly(t, cs + [cs[1]])


def test_detects_dropped_last_chunk():
    t, cs = _chunks()
    with pytest.raises(ChunkingError, match="end of text"):
        svc.validate_reassembly(t, cs[:-1])


def test_detects_tampered_text_and_hash():
    t, cs = _chunks()
    bad = list(cs)
    bad[1] = dataclasses.replace(bad[1], text=bad[1].text.replace("P", "Q", 1))
    with pytest.raises(ChunkingError, match="source span|hash"):
        svc.validate_reassembly(t, bad)


def test_detects_duplicated_paragraph_with_consistent_positions():
    t = "A one.\n\nB two.\n\nC three."
    dup = "A one.\n\nB two.\n\nB two.\n\nC three."
    cs = svc.chunk(dup, "S", 1, 6)
    with pytest.raises(ChunkingError, match="duplicate|differs|source"):
        svc.validate_reassembly(t, cs)


def test_detects_shuffled_order_via_positions():
    t, cs = _chunks()
    shuffled = [dataclasses.replace(cs[0], index=1), dataclasses.replace(cs[1], index=0)] + cs[2:]
    with pytest.raises(ChunkingError):
        svc.validate_reassembly(t, shuffled)


def test_reassemble_sorts_by_index():
    t, cs = _chunks()
    assert svc.reassemble(list(reversed(cs))) == t


def test_coverage_for_safety_gate():
    t, cs = _chunks()
    assert svc.coverage(cs, [c.id for c in cs]) == 1.0
    assert svc.coverage(cs, [c.id for c in cs[:-1]]) < 1.0
    assert svc.coverage(cs, []) == 0.0
    assert svc.coverage([], []) == 1.0


def test_full_length_story_2500_words():
    t = make_story(50, 50)  # ~2500 words
    for mt in (500, 1500):
        cs = svc.chunk(t, "STORY-0042", 3, mt, overlap=100)
        assert svc.validate_reassembly(t, cs)
