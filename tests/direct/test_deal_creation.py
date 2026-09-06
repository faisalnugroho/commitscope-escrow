"""Deal creation validation (spec test #15 and boundary rules).

Every deal must be verifiable from birth: empty/ambiguous allowed_paths,
malformed repo, short sha, bad addresses are rejected AT CREATION - a
deal that could never be positively verified must not exist.
"""
import json
import pytest

import gh_helpers as H

AMOUNT = H.AMOUNT


def status_of(c, deal_id):
    return json.loads(c.get_deal_status(deal_id))


class TestCreateDealHappy:
    def test_create_returns_id_and_locks_funds(self, direct_vm, env,
                                               direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        assert did == "d1"
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Open"
        assert d["amount_wei"] == AMOUNT
        assert d["repo"] == H.REPO
        assert d["base_commit_sha"] == H.BASE_SHA
        assert d["allowed_paths"] == H.PATHS
        assert d["payer"] == H.addr_str(direct_alice)
        assert d["payee"] == H.addr_str(direct_bob)
        assert d["settled"] is False
        # bookkeeping
        assert env.get_locked_total() == AMOUNT
        assert env.get_total_deals() == 1

    def test_create_multiple_deals(self, direct_vm, env, direct_alice,
                                   direct_bob):
        H.create(direct_vm, env, direct_alice, direct_bob)
        H.create(direct_vm, env, direct_alice, direct_bob)
        did3 = H.create(direct_vm, env, direct_bob, direct_alice)
        assert did3 == "d3"
        assert env.get_total_deals() == 3
        assert env.get_locked_total() == 3 * AMOUNT

    def test_create_directory_prefix_scope(self, direct_vm, env,
                                           direct_alice, direct_bob):
        H.create(direct_vm, env, direct_alice, direct_bob,
                 paths="src/")
        d = json.loads(env.get_deal("d1"))
        assert d["allowed_paths"] == "src/"

    def test_get_deal_roundtrip_all_fields(self, direct_vm, env,
                                           direct_alice, direct_bob):
        H.create(direct_vm, env, direct_alice, direct_bob,
                 paths="a.py,b/c.py")
        d = json.loads(env.get_deal("d1"))
        assert d["allowed_paths"] == "a.py,b/c.py"
        assert d["has_submission"] is False
        assert d["has_verification"] is False
        assert d["dispute_count"] == 0
        assert d["settlement_kind"] == ""
        assert d["title"] == H.TITLE
        assert d["description"] == H.DESCRIPTION


class TestCreateDealReverts:
    def test_empty_paths_reverted_at_create(self, direct_vm, env,
                                            direct_alice, direct_bob):
        # spec #15: empty scope must never reach verification
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            "", H.TITLE, H.DESCRIPTION)
        direct_vm.value = 0
        assert env.get_total_deals() == 0
        assert env.get_locked_total() == 0

    def test_whitespace_and_empty_segments_reverted(self, direct_vm, env,
                                                    direct_alice,
                                                    direct_bob):
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            "  ,  ", H.TITLE, H.DESCRIPTION)
        direct_vm.value = 0

    def test_wildcard_paths_reverted(self, direct_vm, env, direct_alice,
                                     direct_bob):
        # ambiguous scope (glob) is rejected at create - the contract
        # only accepts explicit paths
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            "src/*", H.TITLE, H.DESCRIPTION)
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            "src/**/*.py", H.TITLE, H.DESCRIPTION)
        direct_vm.value = 0

    def test_parent_traversal_and_leading_slash_reverted(self, direct_vm,
                                                         env, direct_alice,
                                                         direct_bob):
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            "../etc/passwd", H.TITLE, H.DESCRIPTION)
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            "/abs/path.py", H.TITLE, H.DESCRIPTION)
        direct_vm.value = 0

    def test_duplicate_paths_reverted(self, direct_vm, env, direct_alice,
                                       direct_bob):
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            "a.py,a.py", H.TITLE, H.DESCRIPTION)
        direct_vm.value = 0

    def test_bad_repo_format_reverted(self, direct_vm, env, direct_alice,
                                       direct_bob):
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        for bad in ("no-slash", "a/b/c", "/x", "x/", "a/../../b",
                    "a/b?c", ""):
            with pytest.raises(AssertionError):
                env.create_deal(H.addr_str(direct_bob), bad, H.BASE_SHA,
                                H.PATHS, H.TITLE, H.DESCRIPTION)
        direct_vm.value = 0

    def test_short_sha_reverted(self, direct_vm, env, direct_alice,
                                direct_bob):
        # short shas are ambiguous evidence - full 40-hex required
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, "abc123",
                            H.PATHS, H.TITLE, H.DESCRIPTION)
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO,
                            "z" * 41, H.PATHS, H.TITLE, H.DESCRIPTION)
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO,
                            "g" * 40, H.PATHS, H.TITLE, H.DESCRIPTION)
        direct_vm.value = 0

    def test_bad_payee_address_reverted(self, direct_vm, env,
                                        direct_alice, direct_bob):
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal("0xdeadbeef", H.REPO, H.BASE_SHA, H.PATHS,
                            H.TITLE, H.DESCRIPTION)
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_alice), H.REPO, H.BASE_SHA,
                            H.PATHS, H.TITLE, H.DESCRIPTION)  # self-deal
        direct_vm.value = 0

    def test_zero_value_reverted(self, direct_vm, env, direct_alice,
                                 direct_bob):
        direct_vm.sender = direct_alice
        direct_vm.value = 0
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            H.PATHS, H.TITLE, H.DESCRIPTION)

    def test_bad_title_and_description_reverted(self, direct_vm, env,
                                                direct_alice, direct_bob):
        direct_vm.sender = direct_alice
        direct_vm.value = AMOUNT
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            H.PATHS, "ab", H.DESCRIPTION)
        with pytest.raises(AssertionError):
            env.create_deal(H.addr_str(direct_bob), H.REPO, H.BASE_SHA,
                            H.PATHS, H.TITLE, "too short")
        direct_vm.value = 0


class TestCreateEvents:
    def test_create_emits_deal_created(self, direct_vm, env,
                                        direct_alice, direct_bob):
        # sanity: the event emission path executes without error and
        # the deal is queryable afterwards
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        assert json.loads(env.get_deal(did))["status"] == "Open"
