"""Dispute round-2 fail-safe consistency (spec #9, #10).

The dispute path must use the IDENTICAL validation as the initial
verification: no shortcut branch exists. If the API still fails after
a dispute, the result stays Undetermined.
"""
import json
import pytest

import helpers as H


class TestDisputeRound2:
    def _undetermined(self, vm, c, alice, bob):
        did = H.create(vm, c, alice, bob)
        H.submit(vm, c, bob, did)
        # no web mocks -> compare fetch fails -> Undetermined
        vm.sender = alice
        c.request_verification(did)
        return did

    def test_dispute_then_still_failing_undetermined(self, direct_vm,
                                                     env, direct_alice,
                                                     direct_bob):
        """Spec #9: dispute with additional evidence, but the GitHub
        API still fails -> STILL Undetermined (fail-safe identical to
        the initial path - the dispute evidence URL cannot rescue a
        failed primary fetch)."""
        did = self._undetermined(direct_vm, env, direct_alice,
                                 direct_bob)
        assert json.loads(env.get_deal(did))["status"] == "Undetermined"
        # payee disputes with an evidence URL
        direct_vm.sender = direct_bob
        env.dispute(did, "https://example.com/extra-evidence")
        # API still failing (no mocks registered)
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Undetermined"
        assert d["verification_round"] == 2
        assert d["verification_runs"] == 2
        # all conditions UNCERTAIN - no shortcut, no release
        st = [c["status"] for c in json.loads(d["condition_checks"])]
        assert st == ["UNCERTAIN", "UNCERTAIN", "UNCERTAIN"]

    def test_dispute_then_good_data_released(self, direct_vm, env,
                                             direct_alice, direct_bob,
                                             direct_charlie):
        """Round 2 with the API now healthy: full happy path through
        the SAME consensus function."""
        did = self._undetermined(direct_vm, env, direct_alice,
                                 direct_bob)
        direct_vm.sender = direct_bob
        env.dispute(did, "https://example.com/extra-evidence")
        # API recovered - register good mocks INCLUDING the dispute
        # evidence URL
        H.register_good_mocks(direct_vm)
        direct_vm.mock_web(
            "example\\.com/extra-evidence$",
            H.gh_body({"note": "CI re-ran and passed"}))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Released"
        assert d["verification_round"] == 2
        # claim works after dispute-round release
        direct_vm.sender = direct_charlie
        env.claim_payout(did)
        assert json.loads(env.get_deal(did))["status"] == "Paid"

    def test_dispute_twice_reverts(self, direct_vm, env, direct_alice,
                                   direct_bob):
        """Spec #10: dispute is capped at 1 - the SECOND dispute
        reverts at the contract level."""
        did = self._undetermined(direct_vm, env, direct_alice,
                                  direct_bob)
        direct_vm.sender = direct_bob
        env.dispute(did, "https://example.com/evidence-1")
        # round 2 also fails (no mocks) -> Undetermined again
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        assert json.loads(env.get_deal(did))["status"] == "Undetermined"
        # second dispute attempt reverts
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.dispute(did, "https://example.com/evidence-2")

    def test_dispute_round2_scope_violation_still_rejected(
            self, direct_vm, env, direct_alice, direct_bob):
        """Round 2 must apply the SAME gates: an out-of-scope file in
        the recovered data is still Rejected (no softer dispute
        branch)."""
        did = self._undetermined(direct_vm, env, direct_alice,
                                 direct_bob)
        direct_vm.sender = direct_bob
        env.dispute(did, "https://example.com/extra-evidence")
        H.register_good_mocks(
            direct_vm, files=["src/widgets/core.py", "outside/x.py"])
        direct_vm.mock_web(
            "example\\.com/extra-evidence$",
            H.gh_body({"note": "payee says scope was agreed"}))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Rejected"
        checks = json.loads(d["condition_checks"])
        assert "outside/x.py" in checks[1]["evidence"]

    def test_dispute_evidence_url_failure_not_fatal(self, direct_vm,
                                                    env, direct_alice,
                                                    direct_bob):
        """The additional evidence URL 404s, but the PRIMARY GitHub
        views are healthy: verification proceeds on GitHub evidence -
        the dispute URL is supplementary context only."""
        did = self._undetermined(direct_vm, env, direct_alice,
                                 direct_bob)
        direct_vm.sender = direct_bob
        env.dispute(did, "https://example.com/missing")
        H.register_good_mocks(direct_vm)
        # dispute evidence URL is NOT mocked -> its fetch fails
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Released"
        assert d["verification_round"] == 2

    def test_dispute_round2_ci_failure_still_rejected(self, direct_vm,
                                                      env, direct_alice,
                                                      direct_bob):
        """Round 2 with recovered data but a failed CI run: Rejected
        through the same gates."""
        did = self._undetermined(direct_vm, env, direct_alice,
                                 direct_bob)
        direct_vm.sender = direct_bob
        env.dispute(did, "https://example.com/extra-evidence")
        H.register_good_mocks(
            direct_vm, runs=[["ci", "completed", "failure"]])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Rejected"
        checks = json.loads(d["condition_checks"])
        assert checks[2]["status"] == "FAIL"
