"""Permissionless settlement + balance conservation (spec tests
#10-#14)."""
import json
import pytest

import gh_helpers as H

AMOUNT = H.AMOUNT
TIMEOUT = 5 * 24 * 3600


def verify_good(vm, c, did, who):
    H.register_good_mocks(vm)
    H.mock_llm_verdict(vm, ["PASS", "PASS", "PASS"])
    vm.sender = who
    c.request_verification(did)


class TestClaimPayout:
    def test_claim_after_release(self, direct_vm, env, direct_alice,
                                 direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        verify_good(direct_vm, env, did, direct_alice)
        assert json.loads(env.get_deal(did))["status"] == "Released"
        start_bob = H.balance_of(direct_vm, direct_bob)
        # payee claims
        direct_vm.sender = direct_bob
        env.claim_payout(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Paid"
        assert d["settled"] is True
        assert d["settlement_kind"] == "release"
        assert H.balance_of(direct_vm, direct_bob) == start_bob + AMOUNT

    def test_claim_by_non_payee_succeeds_permissionless(self, direct_vm,
                                                       env, direct_alice,
                                                       direct_bob,
                                                       direct_charlie):
        """Spec #11: claim_payout by a third party still succeeds and
        pays THE PAYEE (permissionless, not payee-restricted)."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        verify_good(direct_vm, env, did, direct_alice)
        start_bob = H.balance_of(direct_vm, direct_bob)
        start_charlie = H.balance_of(direct_vm, direct_charlie)
        direct_vm.sender = direct_charlie  # NOT the payee
        env.claim_payout(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Paid"
        assert H.balance_of(direct_vm, direct_bob) == start_bob + AMOUNT
        # the third-party claimer does not get paid
        assert H.balance_of(direct_vm, direct_charlie) == start_charlie

    def test_double_claim_reverts(self, direct_vm, env, direct_alice,
                                  direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        verify_good(direct_vm, env, did, direct_alice)
        direct_vm.sender = direct_bob
        env.claim_payout(did)
        with pytest.raises(AssertionError):
            env.claim_payout(did)

    def test_claim_before_release_reverts(self, direct_vm, env,
                                          direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.claim_payout(did)  # status Submitted

    def test_claim_on_undetermined_reverts(self, direct_vm, env,
                                           direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        # no mocks -> Undetermined
        direct_vm.sender = direct_alice
        env.request_verification(did)
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.claim_payout(did)


class TestReclaimExpired:
    def test_reclaim_open_after_timeout(self, direct_vm, env,
                                        direct_alice, direct_bob):
        """Spec #13: after timeout, Open deal refunds the payer."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        start_alice = H.balance_of(direct_vm, direct_alice)
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        direct_vm.sender = direct_bob  # ANYONE can reclaim
        env.reclaim_expired(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Refunded"
        assert d["settled"] is True
        assert d["settlement_kind"] == "refund_expired"
        assert H.balance_of(direct_vm, direct_alice) == \
            start_alice + AMOUNT

    def test_reclaim_before_timeout_reverts(self, direct_vm, env,
                                             direct_alice, direct_bob):
        """Spec #12: reclaim before the timeout reverts."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.set_time(direct_vm, H.iso_in(TIMEOUT - 60))
        direct_vm.sender = direct_alice
        with pytest.raises(AssertionError):
            env.reclaim_expired(did)

    def test_reclaim_submitted_after_timeout(self, direct_vm, env,
                                             direct_alice, direct_bob,
                                             direct_charlie):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        direct_vm.sender = direct_charlie
        env.reclaim_expired(did)
        assert json.loads(env.get_deal(did))["status"] == "Refunded"

    def test_reclaim_underreview_after_timeout(self, direct_vm, env,
                                               direct_alice, direct_bob):
        # a deal stuck mid-consensus (state UnderReview persisted via
        # verification_runs marker) still refunds after timeout
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        direct_vm.sender = direct_alice
        env.reclaim_expired(did)
        assert json.loads(env.get_deal(did))["status"] == "Refunded"

    def test_reclaim_rejected_immediate(self, direct_vm, env,
                                        direct_alice, direct_bob):
        # Rejected verdicts refund the payer immediately - no timeout
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm,
                              files=["src/widgets/core.py", "evil.py"])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        assert json.loads(env.get_deal(did))["status"] == "Rejected"
        start_alice = H.balance_of(direct_vm, direct_alice)
        direct_vm.sender = direct_bob
        env.reclaim_expired(did)
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Refunded"
        assert d["settlement_kind"] == "refund_rejected"
        assert H.balance_of(direct_vm, direct_alice) == \
            start_alice + AMOUNT

    def test_reclaim_double_reverts(self, direct_vm, env, direct_alice,
                                     direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        direct_vm.sender = direct_alice
        env.reclaim_expired(did)
        with pytest.raises(AssertionError):
            env.reclaim_expired(did)

    def test_reclaim_after_paid_reverts(self, direct_vm, env,
                                        direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        verify_good(direct_vm, env, did, direct_alice)
        direct_vm.sender = direct_bob
        env.claim_payout(did)
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        with pytest.raises(AssertionError):
            env.reclaim_expired(did)

    def test_reclaim_refunded_not_available(self, direct_vm, env,
                                            direct_alice, direct_bob):
        # activity timeout is measured from last_activity; a refunded
        # deal is settled, so a second reclaim attempt reverts
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        direct_vm.sender = direct_alice
        env.reclaim_expired(did)
        H.set_time(direct_vm, H.iso_in(2 * TIMEOUT))
        with pytest.raises(AssertionError):
            env.reclaim_expired(did)


class TestBalanceConservation:
    """Spec #14: total in == total out in every scenario; nothing
    stranded."""

    def test_released_scenario_conserves(self, direct_vm, env,
                                         direct_alice, direct_bob):
        """Three released deals, all claimed: every deposited GEN is
        paid out to the payee; locked total returns to zero; the
        contract keeps nothing beyond its pre-existing top-up."""
        contract_before = H.contract_balance(direct_vm)
        for _ in range(3):
            did = H.create(direct_vm, env, direct_alice, direct_bob)
            H.submit(direct_vm, env, direct_bob, did)
            verify_good(direct_vm, env, did, direct_alice)
            direct_vm.sender = direct_alice
            env.claim_payout(did)
        assert env.get_locked_total() == 0
        # deposits (3 GEN) in, 3 GEN out -> balance unchanged
        assert H.contract_balance(direct_vm) == contract_before

    def test_mixed_scenarios_conserves(self, direct_vm, env,
                                       direct_alice, direct_bob):
        """One Released, one Rejected, one expired refund: the sum of
        recipient payouts equals total deposits; locked goes to 0.
        Each deal uses a DIFFERENT head sha so the per-URL first-match
        -wins mock set of one deal can never answer another deal's
        fetches (gltest pitfall)."""
        deposits = 0
        payouts = 0

        # deal 1: released + claimed
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        deposits += AMOUNT
        H.submit(direct_vm, env, direct_bob, did, sha=H.HEAD_SHA)
        verify_good(direct_vm, env, did, direct_alice)
        bob_before = H.balance_of(direct_vm, direct_bob)
        direct_vm.sender = direct_alice
        env.claim_payout(did)
        payouts += H.balance_of(direct_vm, direct_bob) - bob_before

        # deal 2: rejected + immediate refund
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        deposits += AMOUNT
        H.submit(direct_vm, env, direct_bob, did, sha=H.HEAD_DIFFERENT)
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_DIFFERENT + "$",
            H.gh_body(H.raw_compare_payload(
                "ahead", files=["src/widgets/core.py", "evil.py"])))
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/commits/"
            + H.HEAD_DIFFERENT + "/check-runs$",
            H.gh_body(H.raw_checks_payload()))
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/commits/"
            + H.HEAD_DIFFERENT + "/status$",
            H.gh_body(H.raw_status_payload("success")))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        direct_vm.sender = direct_alice
        env.request_verification(did)
        assert json.loads(env.get_deal(did))["status"] == "Rejected"
        alice_before = H.balance_of(direct_vm, direct_alice)
        env.reclaim_expired(did)
        payouts += H.balance_of(direct_vm, direct_alice) - alice_before

        # deal 3: open + timeout refund
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        deposits += AMOUNT
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        alice_before = H.balance_of(direct_vm, direct_alice)
        direct_vm.sender = direct_bob
        env.reclaim_expired(did)
        payouts += H.balance_of(direct_vm, direct_alice) - alice_before

        assert deposits == 3 * AMOUNT
        assert payouts == deposits
        assert env.get_locked_total() == 0

    def test_no_stranded_funds_undetermined_then_expired(self, direct_vm,
                                                          env,
                                                          direct_alice,
                                                          direct_bob):
        """Undetermined deal (API failure) + no dispute + timeout ->
        payer refund: nothing stranded even after a failed
        verification round."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        # no mocks -> Undetermined
        direct_vm.sender = direct_alice
        env.request_verification(did)
        assert json.loads(env.get_deal(did))["status"] == "Undetermined"
        # dispute window opens but payee does nothing -> timeout
        H.set_time(direct_vm, H.iso_in(TIMEOUT + 60))
        alice_before = H.balance_of(direct_vm, direct_alice)
        direct_vm.sender = direct_bob
        env.reclaim_expired(did)
        assert H.balance_of(direct_vm, direct_alice) - alice_before \
            == AMOUNT
        assert env.get_locked_total() == 0
