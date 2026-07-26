"""Sprint 6 — resolving claimed arXiv references.

An observation earned `published`, the strongest evidence tier this project
awards, because its text contained something shaped like an arXiv id. Nobody
checked the paper existed. A mis-transcribed number, a hallucinated citation and
a genuine preprint were indistinguishable and all counted the same.

That is the same failure as the old boolean `has_corroboration`, one level down:
treating the presence of a reference as the substance of one.

The distinction these tests care most about is `unresolved` versus `unchecked`.
"The paper does not exist" and "we could not ask" are different facts, and this
project has now had to relearn that twice — once when judge unavailability was
recorded as the judge's conclusion (A3), once when a Gemini quota looked like a
pacing problem (K12).
"""
from __future__ import annotations

import pytest

from scripts.automation.arxiv import (
    ArxivError,
    FixtureArxivClient,
    Paper,
    normalise,
    parse_feed,
)
from scripts.automation.verify_refs import (
    RESOLVED,
    UNCHECKED,
    UNRESOLVED,
    needs_check,
    verified_tier,
    verify_one,
)

NOW = "2026-07-26T00:00:00+00:00"

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2607.16401v1</id>
    <title>An improved bound for the unit distance
    problem</title>
    <published>2026-07-24T10:00:00Z</published>
    <updated>2026-07-25T09:00:00Z</updated>
    <author><name>A. Mathematician</name></author>
    <author><name>B. Collaborator</name></author>
    <category term="math.CO"/>
    <arxiv:doi>10.1000/xyz</arxiv:doi>
  </entry>
</feed>"""

ERROR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format</id>
    <title>Error</title>
  </entry>
</feed>"""


def obs(ids=None, refs=None, oid="obs_1"):
    o = {"id": oid, "sourceType": "twitter", "sourceNativeId": "1",
         "url": "https://x.com/a/status/1", "collectedAt": NOW, "lastSeenAt": NOW,
         "externalIds": ids if ids is not None else {"arxiv": ["2607.16401"]}}
    if refs is not None:
        o["references"] = refs
    return o


class TestIdentifiersAreNormalised:
    @pytest.mark.parametrize("raw", ["2607.16401", "2607.16401v2", "arXiv:2607.16401",
                                     " 2607.16401 ", "ARXIV:2607.16401V3"])
    def test_the_same_paper_normalises_to_one_id(self, raw):
        assert normalise(raw) == "2607.16401"


class TestTheFeedIsParsedHonestly:
    def test_a_real_entry_becomes_a_paper(self):
        papers = parse_feed(FEED)
        p = papers["2607.16401"]
        assert p.title.startswith("An improved bound")
        assert "\n" not in p.title, "whitespace in arXiv titles must be collapsed"
        assert p.authors == ["A. Mathematician", "B. Collaborator"]
        assert p.published == "2026-07-24T10:00:00Z" and p.doi == "10.1000/xyz"

    def test_an_error_entry_is_not_a_paper(self):
        """arXiv answers a bad id with an entry titled 'Error', not an HTTP
        error. Treating that as a hit would defeat the whole point of asking."""
        assert parse_feed(ERROR_FEED) == {}

    def test_a_malformed_response_raises_rather_than_returning_nothing(self):
        with pytest.raises(ArxivError):
            parse_feed("<not xml")

    def test_an_empty_feed_is_empty_not_an_error(self):
        assert parse_feed('<feed xmlns="http://www.w3.org/2005/Atom"/>') == {}


class TestUnresolvedIsNotUnchecked:
    """The distinction this project has had to relearn twice."""

    def test_a_resolved_reference_carries_the_paper(self):
        client = FixtureArxivClient({"2607.16401": parse_feed(FEED)["2607.16401"]})
        out = verify_one(obs(), client.fetch(["2607.16401"]), NOW)
        entry = out["references"]["arxiv"][0]
        assert entry["status"] == RESOLVED
        assert entry["paper"]["title"].startswith("An improved bound")

    def test_an_id_arxiv_does_not_know_is_unresolved(self):
        client = FixtureArxivClient({})
        out = verify_one(obs(), client.fetch(["2607.16401"]), NOW)
        assert out["references"]["arxiv"][0]["status"] == UNRESOLVED

    def test_an_id_we_never_asked_about_is_unchecked(self):
        """Network failure must not be recorded as 'the paper does not exist'."""
        out = verify_one(obs(), {}, NOW)
        assert out["references"]["arxiv"][0]["status"] == UNCHECKED
        assert out["references"]["arxiv"][0]["paper"] is None

    def test_unchecked_is_retried_and_unresolved_is_not(self):
        assert needs_check(obs(refs={"arxiv": [{"id": "x", "status": UNCHECKED}]}))
        assert not needs_check(obs(refs={"arxiv": [{"id": "x", "status": UNRESOLVED}]})), (
            "arXiv does not grow new papers under old ids"
        )
        assert not needs_check(obs(refs={"arxiv": [{"id": "x", "status": RESOLVED}]}))

    def test_an_observation_without_a_claimed_id_is_not_checked(self):
        assert not needs_check(obs(ids={}))
        assert not needs_check(obs(ids={"github": ["a/b"]}))


class TestTheTierMustBeEarned:
    def _verified(self, papers, ids=None):
        client = FixtureArxivClient(papers)
        o = obs(ids=ids)
        return verify_one(o, client.fetch(sum(o["externalIds"].values(), [])), NOW)

    def test_a_resolved_reference_keeps_published(self):
        out = self._verified({"2607.16401": parse_feed(FEED)["2607.16401"]})
        assert verified_tier(out) == "published"

    def test_an_unresolved_reference_cannot_buy_published(self):
        """The overstatement this stage exists to prevent."""
        out = self._verified({})
        assert verified_tier(out) != "published"

    def test_it_falls_back_to_what_the_other_ids_support(self):
        out = self._verified({}, ids={"arxiv": ["2607.16401"], "erdos": ["728"]})
        assert verified_tier(out) == "registered"

    def test_an_unchecked_reference_does_not_award_published_either(self):
        """Until we have asked, we have not earned it."""
        out = verify_one(obs(), {}, NOW)
        assert verified_tier(out) != "published"

    def test_one_resolved_id_among_several_is_enough(self):
        client = FixtureArxivClient({"2607.16401": parse_feed(FEED)["2607.16401"]})
        o = obs(ids={"arxiv": ["2607.16401", "2607.99999"]})
        out = verify_one(o, client.fetch(["2607.16401", "2607.99999"]), NOW)
        assert verified_tier(out) == "published"

    def test_an_observation_with_no_arxiv_claim_is_unaffected(self):
        o = obs(ids={"doi": ["10.1/x"]})
        assert verified_tier(o) == "published"


class TestNothingIsDeleted:
    def test_an_unresolved_id_stays_on_the_record(self):
        """The claim that someone posted that id remains true and auditable."""
        out = verify_one(obs(), FixtureArxivClient({}).fetch(["2607.16401"]), NOW)
        assert out["externalIds"]["arxiv"] == ["2607.16401"]

    def test_verification_does_not_touch_other_fields(self):
        before = obs()
        after = verify_one(before, {}, NOW)
        for key in before:
            if key != "references":
                assert after[key] == before[key]


class TestTheClientAsksProperly:
    def test_duplicate_and_versioned_ids_collapse_to_one_request(self):
        client = FixtureArxivClient({})
        out = client.fetch(["2607.16401", "2607.16401v2", "arXiv:2607.16401"])
        assert list(out) == ["2607.16401"]

    def test_an_id_asked_about_always_appears_in_the_answer(self):
        """Silent absence would be read as 'not checked' forever."""
        out = FixtureArxivClient({}).fetch(["2607.16401", "2601.00001"])
        assert set(out) == {"2607.16401", "2601.00001"}
        assert all(v is None for v in out.values())

    def test_the_courtesy_interval_is_respected_by_default(self):
        from scripts.automation.arxiv import MIN_INTERVAL_SECONDS
        assert MIN_INTERVAL_SECONDS >= 3.0, "arXiv asks for one request per 3 seconds"

    def test_a_paper_serialises_without_the_abstract(self):
        """We store enough for a curator to judge, not a copy of the paper."""
        d = Paper("2607.1", "T", authors=["A"] * 20).to_dict()
        assert len(d["authors"]) <= 8 and "abstract" not in d


class TestTitleAffinityIsAHintNotAVerdict:
    """A live check found 2607.16401 resolving perfectly to "Apple-π:
    Benchmarking Thinking with Video" — a real paper with nothing to do with the
    Erdős problem it was cited for. Existence and relevance are different
    questions and only the first can be answered mechanically."""

    def _obs(self, name):
        o = obs()
        o["extraction"] = {"canonicalProblemName": name}
        return o

    def test_a_matching_title_scores_high(self):
        from scripts.automation.verify_refs import title_affinity
        paper = parse_feed(FEED)["2607.16401"]
        assert title_affinity(self._obs("unit distance problem"), paper) > 0.8

    def test_an_unrelated_title_scores_low(self):
        from scripts.automation.verify_refs import title_affinity
        paper = Paper("2607.16401", "Apple-$π$: Benchmarking Thinking with Video")
        assert title_affinity(self._obs("Erdős problem on unit distances"), paper) < 0.4

    def test_a_low_score_never_downgrades_the_tier(self):
        """Recorded and shown, never acted on."""
        paper = Paper("2607.16401", "Something completely unrelated")
        out = verify_one(self._obs("unit distances"),
                         {"2607.16401": paper}, NOW)
        assert out["references"]["arxiv"][0]["titleAffinity"] < 0.4
        assert verified_tier(out) == "published", (
            "affinity is a hint for a curator; only resolution gates the tier"
        )

    def test_it_is_absent_when_there_is_nothing_to_compare(self):
        from scripts.automation.verify_refs import title_affinity
        assert title_affinity(obs(), parse_feed(FEED)["2607.16401"]) is None
        assert title_affinity(self._obs("x"), None) is None
