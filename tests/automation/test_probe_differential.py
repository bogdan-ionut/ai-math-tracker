"""The K10 differential probe — offline.

The probe itself must spend API calls to answer anything, but its reasoning is
pure and testable, and it is worth testing precisely because a probe that
misreports is worse than no probe. Two of my earlier K10 hypotheses (length,
term count) were wrong; the third failure mode would be a probe that draws a
confident conclusion from an experiment that did not establish it.

The witness test is the sharp one, so most of these are about the conditions
under which it may and may not claim a verdict.
"""
from __future__ import annotations

from scripts.automation.probe_differential import (
    Probe,
    ablate,
    g,
    parse,
    unquote,
    witness,
)
from scripts.automation.twitter import FixtureSearchClient

Q = '("verified in Lean" OR "formal proof") (Gemini OR GPT OR Claude) lang:en -filter:retweets'


def tweet(text, tid="1", author="someone"):
    return {"id": tid, "text": text, "author": {"userName": author}}


class TestQueryDissection:
    def test_groups_and_tail_are_separated(self):
        groups, tail = parse(Q)
        assert groups == [["\"verified in Lean\"", "\"formal proof\""],
                          ["Gemini", "GPT", "Claude"]]
        assert tail == "lang:en -filter:retweets"

    def test_unquoting_keeps_only_the_first_word(self):
        """An unquoted multi-word phrase becomes an implicit AND, which would
        make the variant test something other than quoting."""
        assert unquote(['"verified in Lean"', "Gemini"]) == ["verified", "Gemini"]

    def test_a_group_round_trips(self):
        groups, _ = parse(Q)
        assert parse(g(groups[1]))[0] == [groups[1]]


class TestAblationLadder:
    def _labels(self, client):
        p = Probe(client)
        ablate(p, Q)
        return p, [t.label for t in p.trials]

    def test_baseline_is_run_verbatim(self):
        p, labels = self._labels(FixtureSearchClient())
        assert labels[0] == "baseline (verbatim)"
        assert p.trials[0].query == Q, "the baseline must not be rewritten"

    def test_every_element_is_removed_exactly_once(self):
        _, labels = self._labels(FixtureSearchClient())
        for expected in ("drop lang:en", "drop -filter:retweets",
                         "drop group 1", "drop group 2", "unquote group 1"):
            assert labels.count(expected) == 1, f"missing or repeated: {expected}"

    def test_only_quoted_groups_get_an_unquote_variant(self):
        _, labels = self._labels(FixtureSearchClient())
        assert "unquote group 2" not in labels, "group 2 has no quoted phrases"

    def test_no_query_is_paid_for_twice(self):
        """The ladder generates no-ops by construction: trimming a 3-term group
        to 8 terms changes nothing. Each is a paid call."""
        client = FixtureSearchClient()
        p, _ = self._labels(client)
        queries = [t.query for t in p.trials]
        assert len(queries) == len(set(queries))
        assert client.call_count == len(p.trials)

    def test_a_reused_query_reports_the_earlier_result(self):
        """The witness experiment re-asks the baseline; it must get its number
        back, not silence."""
        p = Probe(FixtureSearchClient(default=[tweet("x")]))
        first = p.run("first", Q)
        again = p.run("second", Q)
        assert again is first and again.returned == 1
        assert len(p.trials) == 1

    def test_a_dropped_group_is_really_gone(self):
        p, _ = self._labels(FixtureSearchClient())
        t = next(t for t in p.trials if t.label == "drop group 2")
        assert "Gemini" not in t.query and "verified in Lean" in t.query

    def test_errors_do_not_abort_the_ladder(self):
        class Boom(FixtureSearchClient):
            def search(self, *a, **k):
                from scripts.automation.twitter import TwitterApiError
                raise TwitterApiError("HTTP 500")

        p = Probe(Boom())
        ablate(p, Q)
        assert p.trials and all(t.error for t in p.trials)
        assert all(t.returned == -1 for t in p.trials), "an error is not zero results"


class TestWitness:
    """The witness must satisfy both groups *in the text the API returned*."""

    def test_a_real_witness_is_selected_and_verified(self):
        c = FixtureSearchClient(default=[
            tweet("no ai system named here, just a formal proof"),      # group 1 only
            tweet("Gemini produced a verified in Lean argument", "77", "alice"),
        ])
        r = witness(Probe(c), Q)
        assert r["conclusive"] and r["witnessId"] == "77"
        assert r["satisfiesGroup1Via"] == '"verified in Lean"'
        assert r["satisfiesGroup2Via"] == "Gemini"

    def test_a_post_matching_one_group_is_not_a_witness(self):
        c = FixtureSearchClient(default=[tweet("a formal proof, no model named")])
        r = witness(Probe(c), Q)
        assert r["conclusive"] is False
        assert "genuinely restrictive" in r["why"], (
            "finding no witness is evidence for restrictiveness, not for a backend bug"
        )

    def test_no_witness_never_claims_a_backend_bug(self):
        r = witness(Probe(FixtureSearchClient(default=[])), Q)
        assert r.get("backendDropsSatisfiableConjunctions") is None

    # --- the two verdicts ------------------------------------------------

    def test_zero_despite_a_witness_indicts_the_backend(self):
        """The whole point: the conjunction is provably satisfiable, so an empty
        result cannot be explained by the world being empty."""
        w = tweet("Gemini produced a verified in Lean argument", "77", "alice")

        class OnlyGroupOne(FixtureSearchClient):
            def search(self, query, *a, **k):
                self.call_count += 1
                return [w] if "Gemini" not in query else []

        r = witness(Probe(OnlyGroupOne()), Q)
        assert r["conclusive"] and r["backendDropsSatisfiableConjunctions"] is True
        assert "groups" in r["queriesReturningZeroDespiteWitness"]

    def test_a_returned_witness_exonerates_the_shape(self):
        w = tweet("Gemini produced a verified in Lean argument", "77", "alice")
        r = witness(Probe(FixtureSearchClient(default=[w])), Q)
        assert r["backendDropsSatisfiableConjunctions"] is False, (
            "if the conjunction returns the witness, the shape is fine"
        )

    def test_an_errored_variant_is_not_counted_as_zero(self):
        """A transport failure must never be read as 'the backend dropped it'."""
        w = tweet("Gemini produced a verified in Lean argument", "77", "alice")

        class ErrorsOnConjunction(FixtureSearchClient):
            def search(self, query, *a, **k):
                from scripts.automation.twitter import TwitterApiError
                self.call_count += 1
                if "Gemini" in query:
                    raise TwitterApiError("timeout")
                return [w]

        r = witness(Probe(ErrorsOnConjunction()), Q)
        assert r["queriesReturningZeroDespiteWitness"] == []
        assert r["backendDropsSatisfiableConjunctions"] is False

    def test_the_minimal_pair_is_the_two_hit_terms_only(self):
        w = tweet("Gemini produced a verified in Lean argument", "77", "alice")
        p = Probe(FixtureSearchClient(default=[w]))
        witness(p, Q)
        pair = next(t for t in p.trials if t.label == "witness: the two hit terms")
        assert pair.query == '"verified in Lean" Gemini lang:en -filter:retweets'
