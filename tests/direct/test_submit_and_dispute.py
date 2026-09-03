"""Commit submission + dispute filing state rules."""
import json
import pytest

import helpers as H


class TestSubmitCommit:
    def test_payee_submits_head_sha(self, direct_vm, env, direct_alice,
                                    direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Submitted"
        assert d["has_submission"] is True
        assert d["submitted_commit_sha"] == H.HEAD_SHA

    def test_only_payee_can_submit(self, direct_vm, env, direct_alice,
                                   direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        direct_vm.sender = direct_alice  # payer, not payee
        with pytest.raises(AssertionError):
            env.submit_commit(did, H.HEAD_SHA)

    def test_submit_requires_open_status(self, direct_vm, env,
                                         direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        # second submission from Submitted state reverts
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.submit_commit(did, H.HEAD_DIFFERENT)

    def test_short_sha_rejected_at_submit(self, direct_vm, env,
                                          direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.submit_commit(did, "abc123")
        with pytest.raises(AssertionError):
            env.submit_commit(did, "g" * 40)

    def test_submit_base_sha_rejected(self, direct_vm, env, direct_alice,
                                      direct_bob):
        # submitting the base itself is a zero-work claim
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.submit_commit(did, H.BASE_SHA)

    def test_submit_on_unknown_deal_reverts(self, direct_vm, env,
                                            direct_alice, direct_bob):
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.submit_commit("d99", H.HEAD_SHA)


class TestDisputeFiling:
    def _undetermined_deal(self, vm, c, alice, bob):
        """Deal that reached Undetermined (API failure scenario)."""
        did = H.create(vm, c, alice, bob)
        H.submit(vm, c, bob, did)
        # no web mocks -> compare fetch fails -> deterministic
        # fail-safe Undetermined
        vm.sender = alice
        c.request_verification(did)
        return did

    def test_dispute_moves_back_to_submitted(self, direct_vm, env,
                                             direct_alice, direct_bob):
        did = self._undetermined_deal(direct_vm, env, direct_alice,
                                       direct_bob)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Undetermined"
        direct_vm.sender = direct_bob
        env.dispute(did, "https://example.com/evidence")
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Submitted"
        assert d["dispute_count"] == 1
        assert d["dispute_evidence_url"] == "https://example.com/evidence"

    def test_dispute_requires_undetermined_status(self, direct_vm, env,
                                                  direct_alice,
                                                  direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.dispute(did, "https://example.com/evidence")

    def test_dispute_only_payee(self, direct_vm, env, direct_alice,
                                direct_bob):
        did = self._undetermined_deal(direct_vm, env, direct_alice,
                                       direct_bob)
        direct_vm.sender = direct_alice  # payer
        with pytest.raises(AssertionError):
            env.dispute(did, "https://example.com/evidence")

    def test_dispute_url_validated(self, direct_vm, env, direct_alice,
                                    direct_bob):
        did = self._undetermined_deal(direct_vm, env, direct_alice,
                                       direct_bob)
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.dispute(did, "ftp://bad-scheme")
        with pytest.raises(AssertionError):
            env.dispute(did, "")

    def test_verification_requires_filed_dispute(self, direct_vm, env,
                                                 direct_alice, direct_bob):
        # re-verification from Undetermined without a dispute reverts
        did = self._undetermined_deal(direct_vm, env, direct_alice,
                                       direct_bob)
        direct_vm.sender = direct_alice
        with pytest.raises(AssertionError):
            env.request_verification(did)
