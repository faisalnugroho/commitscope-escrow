"""Verification consensus: happy path, gate rejections, and the
fail-safe Undetermined family (spec tests #1-#9)."""
import json
import pytest

import gh_helpers as H

CONDITIONS = ["commit_ancestry", "diff_scope", "ci_status"]


def verify(vm, c, who, did):
    vm.sender = who
    c.request_verification(did)


def read_checks(c, did):
    d = json.loads(c.get_deal(did))
    return json.loads(d["condition_checks"]), d["verdict"]


class TestHappyPathReleased:
    def test_all_conditions_met_releases(self, direct_vm, env,
                                         direct_alice, direct_bob,
                                         direct_charlie):
        """Spec #1: valid commit, scope ok, CI success -> Released."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm)
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        # anyone may trigger - a third party does it
        verify(direct_vm, env, direct_charlie, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Released"
        assert [c["status"] for c in checks] == ["PASS", "PASS", "PASS"]
        d = json.loads(env.get_deal(did))
        assert d["status"] == "Released"
        assert d["verification_round"] == 1
        assert d["verification_runs"] == 1


class TestScopeAndAncestryRejections:
    def test_out_of_scope_file_rejected(self, direct_vm, env,
                                        direct_alice, direct_bob):
        """Spec #2: file outside allowed_paths -> Rejected with the
        filename cited."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(
            direct_vm, files=["src/widgets/core.py", "README.md"])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert checks[0]["status"] == "PASS"       # ancestry ahead
        assert checks[1]["status"] == "FAIL"       # scope violation
        assert "README.md" in checks[1]["evidence"]

    def test_unrelated_history_rejected(self, direct_vm, env,
                                        direct_alice, direct_bob):
        """Spec #3: head not descendant of base -> Rejected (positive
        proof via compare status diverged)."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm, compare_status="diverged")
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert checks[0]["status"] == "FAIL"
        assert "diverged" in checks[0]["evidence"]
        # scope/ci still evaluated on fetched data
        assert checks[1]["status"] == "PASS"
        assert checks[2]["status"] == "PASS"

    def test_behind_status_is_also_non_descent(self, direct_vm, env,
                                               direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm, compare_status="behind")
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert checks[0]["status"] == "FAIL"

    def test_identical_status_passes_ancestry(self, direct_vm, env,
                                              direct_alice, direct_bob):
        # base...head identical: zero-diff, provably same lineage
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm, compare_status="identical",
                              files=[])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Released"
        assert checks[0]["status"] == "PASS"

    def test_directory_prefix_scope_covered(self, direct_vm, env,
                                             direct_alice, direct_bob):
        # files nested under an allowed directory are in scope
        did = H.create(direct_vm, env, direct_alice, direct_bob,
                       paths="src/widgets/")
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(
            direct_vm,
            files=["src/widgets/core.py", "src/widgets/deep/mod.py"])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Released"


class TestUndeterminedFailSafe:
    """Spec #5-#8: every API failure mode resolves to Undetermined,
    never Released, never Rejected-on-missing-data."""

    def _deal_submitted(self, vm, c, alice, bob):
        did = H.create(vm, c, alice, bob)
        H.submit(vm, c, bob, did)
        return did

    def test_compare_404_undetermined(self, direct_vm, env, direct_alice,
                                      direct_bob):
        """Spec #5: commit not found -> Undetermined."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        H.register_poisoned_compare(direct_vm, http_status=404)
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert all(c["status"] == "UNCERTAIN" for c in checks)

    def test_compare_429_rate_limit_undetermined(self, direct_vm, env,
                                                 direct_alice, direct_bob):
        """Spec #6: rate limit -> Undetermined."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                   direct_bob)
        H.register_poisoned_compare(
            direct_vm, http_status=429,
            body={"message": "API rate limit exceeded"})
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"

    def test_compare_403_undetermined(self, direct_vm, env, direct_alice,
                                      direct_bob):
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                   direct_bob)
        H.register_poisoned_compare(direct_vm, http_status=403)
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        assert json.loads(env.get_deal(did))["verdict"] == "Undetermined"

    def test_compare_malformed_json_undetermined(self, direct_vm, env,
                                                  direct_alice, direct_bob):
        """Spec #7: malformed JSON body -> Undetermined."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                   direct_bob)
        # valid HTTP 200 but body is not JSON at all
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            {"method": "GET", "status": 200,
             "body": "<html>not json</html>"})
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        assert json.loads(env.get_deal(did))["verdict"] == "Undetermined"

    def test_compare_missing_fields_undetermined(self, direct_vm, env,
                                                 direct_alice, direct_bob):
        """Spec #7: 200 OK but required fields missing -> Undetermined."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                   direct_bob)
        # status field missing
        H.register_poisoned_compare(
            direct_vm, http_status=200,
            body={"files": [{"filename": "src/widgets/core.py"}]})
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        assert json.loads(env.get_deal(did))["verdict"] == "Undetermined"

    def test_compare_missing_files_undetermined(self, direct_vm, env,
                                                direct_alice, direct_bob):
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                   direct_bob)
        H.register_poisoned_compare(
            direct_vm, http_status=200, body={"status": "ahead"})
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        assert json.loads(env.get_deal(did))["verdict"] == "Undetermined"

    def test_no_mocks_timeout_undetermined(self, direct_vm, env,
                                           direct_alice, direct_bob):
        """Spec #8: no web mocks at all -> web.get raises (simulated
        timeout/network failure) -> Undetermined."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        assert json.loads(env.get_deal(did))["verdict"] == "Undetermined"

    def test_no_web_mocks_llm_never_burned(self, direct_vm, env,
                                           direct_alice, direct_bob):
        """Without compare data the deterministic short-circuit must
        skip the LLM call - verification completes with no prompt."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                   direct_bob)
        verify(direct_vm, env, direct_alice, did)
        d = json.loads(env.get_deal(did))
        assert d["verdict"] == "Undetermined"
        assert "verification_unavailable" in d["reasoning"]


class TestCiGate:
    def test_ci_failure_rejected(self, direct_vm, env, direct_alice,
                                 direct_bob):
        """Spec #4a: failed check-run -> Rejected (positive failure
        proof), even if the LLM misreads it as pass."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(
            direct_vm, runs=[["ci", "completed", "failure"]])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert checks[2]["status"] == "FAIL"
        assert "ci=failure" in checks[2]["evidence"]

    def test_ci_pending_undetermined(self, direct_vm, env, direct_alice,
                                     direct_bob):
        """Spec #4b: in-flight CI is ambiguous -> Undetermined, never
        Released."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(
            direct_vm, runs=[["ci", "in_progress", None]],
            status_state="pending")
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert checks[2]["status"] == "UNCERTAIN"

    def test_ci_skipped_is_not_success(self, direct_vm, env, direct_alice,
                                       direct_bob):
        # skipped conclusion is neutral, not green -> ambiguous
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(
            direct_vm,
            runs=[["ci", "completed", "success"],
                  ["lint", "completed", "skipped"]])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert checks[2]["status"] == "UNCERTAIN"

    def test_zero_check_runs_pending_status_undetermined(self, direct_vm,
                                                         env,
                                                         direct_alice,
                                                         direct_bob):
        # Actions-only repo: 0 check-runs + legacy pending/0 - the
        # real shape probed live - no CI signal is never a pass
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(
            direct_vm, runs=[], status_state="pending", status_total=0)
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert checks[2]["status"] == "UNCERTAIN"

    def test_legacy_status_failure_rejected(self, direct_vm, env,
                                            direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm, status_state="failure")
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert checks[2]["status"] == "FAIL"

    def test_llm_misread_clamped_by_data_gates(self, direct_vm, env,
                                               direct_alice, direct_bob):
        """The LLM says all-PASS on data that violates scope - the
        deterministic clamp layer must catch it (LLM cannot override
        API facts)."""
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(
            direct_vm, files=["src/widgets/core.py", "secret/out.py"])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert "secret/out.py" in checks[1]["evidence"]

    def test_legacy_status_alone_can_release(self, direct_vm, env,
                                              direct_alice, direct_bob):
        # repo with legacy CI only: checks view 404 but combined
        # status green -> ci PASS via the legacy view
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        # register good compare + good legacy status, and a 404 on the
        # check-runs view (do NOT clear mocks here: first-match-wins
        # would lose the compare mock - register the poisoned checks
        # mock FIRST is wrong too; register it after and let matching
        # be by URL specificity)
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(H.raw_compare_payload("ahead")))
        H.register_poisoned_checks(direct_vm, http_status=404)
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/commits/"
            + H.HEAD_SHA + "/status$",
            H.gh_body(H.raw_status_payload("success")))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Released"
        assert checks[2]["status"] == "PASS"


class TestTruncatedCompareUndetermined:
    """Boundary fix: the GitHub compare API is paginated and capped.
    A truncated/capped files array is PARTIAL diff data - scope can
    never be positively proven from it, so it must resolve to
    Undetermined exactly like any other API failure, never a
    diff_scope PASS on partial data."""

    def _deal_submitted(self, vm, c, alice, bob):
        did = H.create(vm, c, alice, bob)
        H.submit(vm, c, bob, did)
        return did

    def test_truncated_flag_true_undetermined(self, direct_vm, env,
                                               direct_alice,
                                               direct_bob):
        """Compare response carries truncated=true -> Undetermined."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(H.raw_compare_payload("ahead", files=[], renamed=[],
                                            truncated=True)))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert all(c["status"] == "UNCERTAIN" for c in checks)
        assert "truncated" in checks[0]["evidence"]

    def test_over_cap_files_undetermined(self, direct_vm, env,
                                         direct_alice, direct_bob):
        """File count exceeds the 300 cap -> Undetermined (not provable)."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        files = ["src/widgets/f%03d.py" % i for i in range(301)]
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(H.raw_compare_payload("ahead", files=files)))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert all(c["status"] == "UNCERTAIN" for c in checks)

    def test_at_exact_cap_not_provable_undetermined(self, direct_vm, env,
                                                     direct_alice,
                                                     direct_bob):
        """Exactly 300 files = the paging boundary: a complete 300-file
        diff and a capped first page are indistinguishable, so
        completeness is NOT provable -> Undetermined (fail-safe)."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        files = ["src/widgets/f%03d.py" % i for i in range(300)]
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(H.raw_compare_payload("ahead", files=files)))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert "cap" in checks[0]["evidence"] or \
            "diff" in checks[0]["evidence"]

    def test_commits_count_mismatch_paginated_undetermined(
            self, direct_vm, env, direct_alice, direct_bob):
        """total_commits (250) does not match the commits array length
        (1) - the paginated/capped response shape -> Undetermined."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(H.raw_compare_payload(
                "ahead", files=["src/widgets/core.py"],
                total_commits=250, commits_len=1)))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert all(c["status"] == "UNCERTAIN" for c in checks)

    def test_consistent_small_compare_still_processes(self, direct_vm,
                                                      env, direct_alice,
                                                      direct_bob):
        """Sanity: a small, consistent, non-truncated compare payload
        (counts match, no flags) still processes normally - the guard
        must not break the happy path."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        vm = direct_vm
        vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(H.raw_compare_payload(
                "ahead", files=["src/widgets/core.py"],
                total_commits=1, commits_len=1, truncated=False)))
        vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/commits/"
            + H.HEAD_SHA + "/check-runs$",
            H.gh_body(H.raw_checks_payload()))
        vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/commits/"
            + H.HEAD_SHA + "/status$",
            H.gh_body(H.raw_status_payload("success")))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Released"
        assert checks[1]["status"] == "PASS"


class TestRenamedFileScope:
    """Boundary fix: GitHub compare marks renames with status='renamed'
    and exposes previous_filename. The scope gate must validate BOTH
    the destination filename AND the previous (source) filename
    against allowed_paths - either side out of scope is a FAIL."""

    def _deal_submitted(self, vm, c, alice, bob, paths=None):
        did = H.create(vm, c, alice, bob,
                       paths=paths if paths is not None else
                       "src/widgets/,tests/")
        H.submit(vm, c, bob, did)
        return did

    def test_rename_out_of_scope_source_rejected(self, direct_vm, env,
                                                  direct_alice,
                                                  direct_bob):
        """Renamed from OUT of allowed_paths INTO allowed_paths ->
        still Rejected: the out-of-scope previous_filename is detected
        (it cannot 'disappear' via the rename)."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        # docs/legacy_notes.md is OUT of scope; src/widgets/notes.py
        # is IN scope. Old code (filename-only) wrongly passed this.
        H.register_renamed_mocks(
            direct_vm,
            renamed=[("docs/legacy_notes.md", "src/widgets/notes.py")])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert checks[1]["status"] == "FAIL"
        assert "docs/legacy_notes.md" in checks[1]["evidence"]
        assert "renamed from" in checks[1]["evidence"]

    def test_rename_in_scope_to_in_scope_released(self, direct_vm, env,
                                                  direct_alice,
                                                  direct_bob):
        """Renamed from one allowed path to another allowed path ->
        Released: both sides of the rename are inside the scope."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        # src/widgets/core.py -> src/widgets/engine.py: both covered
        # by the src/widgets/ prefix in the default PATHS.
        H.register_renamed_mocks(
            direct_vm,
            renamed=[("src/widgets/core.py", "src/widgets/engine.py")])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Released"
        assert checks[1]["status"] == "PASS"
        assert "renames validated" in checks[1]["evidence"]

    def test_rename_destination_out_of_scope_rejected(self, direct_vm,
                                                      env, direct_alice,
                                                      direct_bob):
        """Renamed from an allowed path to a path OUTSIDE the scope ->
        Rejected (the destination filename itself is the violation)."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        H.register_renamed_mocks(
            direct_vm,
            renamed=[("src/widgets/core.py", "outside/renamed.py")])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Rejected"
        assert checks[1]["status"] == "FAIL"
        assert "outside/renamed.py" in checks[1]["evidence"]

    def test_renamed_without_previous_filename_undetermined(
            self, direct_vm, env, direct_alice, direct_bob):
        """status='renamed' but previous_filename missing/empty: the
        source path is unknown, so scope is NOT provable ->
        Undetermined (never a blind PASS)."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        # hand-build the payload: renamed entry without previous path
        payload = {
            "status": "ahead", "ahead_by": 1, "total_commits": 1,
            "files": [{"filename": "src/widgets/notes.py",
                       "status": "renamed"}],
        }
        direct_vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(payload))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Undetermined"
        assert all(c["status"] == "UNCERTAIN" for c in checks)

    def test_mixed_rename_and_normal_files_released(self, direct_vm,
                                                    env, direct_alice,
                                                    direct_bob):
        """A normal in-scope modification plus an in-scope rename in
        the same diff -> Released (rename handling composes with the
        ordinary file-by-file check)."""
        did = self._deal_submitted(direct_vm, env, direct_alice,
                                    direct_bob)
        vm = direct_vm
        vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/compare/"
            + H.BASE_SHA + "\\.\\.\\." + H.HEAD_SHA + "$",
            H.gh_body(H.raw_compare_payload(
                "ahead", files=["src/widgets/render.py"],
                renamed=[("src/widgets/core.py",
                          "src/widgets/engine.py")])))
        vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/commits/"
            + H.HEAD_SHA + "/check-runs$",
            H.gh_body(H.raw_checks_payload()))
        vm.mock_web(
            "api\\.github\\.com/repos/acme-org/widgets/commits/"
            + H.HEAD_SHA + "/status$",
            H.gh_body(H.raw_status_payload("success")))
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        checks, verdict = read_checks(env, did)
        assert verdict == "Released"
        assert checks[1]["status"] == "PASS"


class TestPermissionlessTrigger:
    def test_anyone_can_trigger_verification(self, direct_vm, env,
                                             direct_alice, direct_bob,
                                             direct_charlie):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm)
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_charlie, did)
        assert json.loads(env.get_deal(did))["status"] == "Released"

    def test_verification_requires_submitted(self, direct_vm, env,
                                             direct_alice, direct_bob):
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        direct_vm.sender = direct_alice
        with pytest.raises(AssertionError):
            env.request_verification(did)

    def test_rejected_is_final_no_resubmit(self, direct_vm, env,
                                           direct_alice, direct_bob):
        # after Rejected, submit/verify/dispute all refuse
        did = H.create(direct_vm, env, direct_alice, direct_bob)
        H.submit(direct_vm, env, direct_bob, did)
        H.register_good_mocks(direct_vm,
                              files=["src/widgets/core.py", "evil.py"])
        H.mock_llm_verdict(direct_vm, ["PASS", "PASS", "PASS"])
        verify(direct_vm, env, direct_alice, did)
        assert json.loads(env.get_deal(did))["status"] == "Rejected"
        direct_vm.sender = direct_bob
        with pytest.raises(AssertionError):
            env.dispute(did, "https://example.com/evidence")
        with pytest.raises(AssertionError):
            env.request_verification(did)
