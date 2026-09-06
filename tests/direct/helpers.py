"""Shared helpers for CommitScopeEscrow direct-mode tests.

Patterns proven on SecondHandCarInspectionEscrow (60/60),
AIEscrowAdjudicator, PRBountyEscrow and TrustReconciler:
- transfer hook mirrors the child-tx balance movement of emit_transfer
- mock_llm drives per-condition verdicts (first-match-wins -> clear first)
- set_time + message_raw patch controls the activity timeout
- vm.deal funds the contract so payable flows have real balance
- mock_web patterns use non-greedy URL segments (gltest pitfall)
"""
import json
import sys
import time

from eth_utils import to_checksum_address

CONTRACT = "contracts/commit_scope_escrow.py"

AMOUNT = 10**18  # 1 GEN

# ---- default deal terms ----------------------------------------------------

REPO = "acme-org/widgets"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
PATHS = "src/widgets/core.py,src/widgets/render.py,tests/"

TITLE = "Widget renderer milestone"
DESCRIPTION = ("Implement the widget renderer refactor across the agreed "
               "core and render modules with passing CI.")

HEAD_DIFFERENT = "c" * 40


def addr_str(raw):
    if isinstance(raw, str):
        return raw
    if hasattr(raw, "as_bytes"):
        raw = raw.as_bytes
    return to_checksum_address(bytes(raw))


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"


def iso_in(seconds):
    return time.strftime(
        "%Y-%m-%dT%H:%M:%S",
        time.gmtime(time.time() + seconds)) + ".000Z"


def set_time(vm, iso):
    vm.warp(iso)
    gl_mod = sys.modules.get("genlayer.gl")
    if gl_mod is not None:
        try:
            if getattr(gl_mod, "message_raw", None):
                gl_mod.message_raw["datetime"] = iso
        except Exception:
            pass


def install_transfer_hook(vm):
    """PostMessage hook that moves value like a real child tx: debit the
    contract, credit the recipient (gltest direct default is a no-op)."""
    def hook(vmm, request):
        pm = (request or {}).get("PostMessage")
        if not pm:
            return None
        a = pm.get("address")
        recipient = bytes(a.as_bytes) if hasattr(a, "as_bytes") else bytes(a)
        value = int(pm.get("value", 0))
        ca = vmm._to_bytes(vmm._contract_address)
        vmm._balances[ca] = vmm._balances.get(ca, 0) - value
        vmm._balances[recipient] = vmm._balances.get(recipient, 0) + value
        return {"ok": None}
    vm._gl_call_hook = hook


def fund_contract(vm, amount=1000 * AMOUNT):
    vm.deal(vm._to_bytes(vm._contract_address), amount)


def balance_of(vm, who):
    return vm._balances.get(vm._to_bytes(who), 0)


def contract_balance(vm):
    return vm._balances.get(vm._to_bytes(vm._contract_address), 0)


# ---- flow helpers ----------------------------------------------------------


def create(vm, c, payer, payee, repo=REPO, base=BASE_SHA, paths=PATHS,
           title=TITLE, description=DESCRIPTION, amount=AMOUNT):
    vm.sender = payer
    vm.value = amount
    deal_id = c.create_deal(addr_str(payee), repo, base, paths,
                             title, description)
    vm.value = 0
    # simulate the GEN actually arriving in the contract
    vm.deal(vm._to_bytes(vm._contract_address),
            contract_balance(vm) + amount)
    return deal_id


def submit(vm, c, payee, deal_id, sha=HEAD_SHA):
    vm.sender = payee
    c.submit_commit(deal_id, sha)


# ---- GitHub API view builders ----------------------------------------------


def compare_view(status="ahead", files=None, previous=None):
    """compare API view. status: ahead|identical|behind|diverged.
    previous: parallel list of previous_filenames ('' when the file
    was not renamed) - same length as files when given."""
    return {
        "view": "compare", "ok": True, "err": "",
        "compare_status": status,
        "changed_files": files if files is not None else
        ["src/widgets/core.py", "src/widgets/render.py"],
        "previous_files": previous if previous is not None else [],
    }


def checks_view(total=1, runs=None):
    """check-runs API view. runs: list of [name, status, conclusion]."""
    if runs is None:
        runs = [["ci", "completed", "success"]]
    return {
        "view": "checks", "ok": True, "err": "",
        "check_runs": [[r[0], r[1], r[2]] for r in runs],
        "total_count": total if total is not None else len(runs),
    }


def status_view(state="success", total=1):
    return {"view": "status", "ok": True, "err": "",
            "state": state, "total_count": total}


# ---- mock registration -----------------------------------------------------
#
# mock_web patterns must be non-greedy: '.*' swallows segments
# (gltest pitfall). The registered body must be a JSON STRING matching
# MockedWebResponseData-ish shape actually used by gltest: {"method",
# "status", "body"}.
#
# mock matching is FIRST-MATCH-WINS and re-registering the same URL
# never overrides - parameterize registration and call vm.clear_mocks()
# between different evidence sets.


def gh_body(payload, status_code=200):
    """Flat gltest mock body: {method, status, body(json-str)}."""
    return {
        "method": "GET",
        "status": status_code,
        "body": json.dumps(payload),
    }


def raw_compare_payload(status="ahead", files=None, renamed=None,
                        truncated=None, total_commits=None,
                        commits_len=None):
    """Raw GitHub compare API response payload.

    files: list of plain filenames (each becomes {filename, status}).
    renamed: list of (previous_filename, new_filename) tuples - each
      becomes {filename, status: 'renamed', previous_filename}.
    truncated: sets the top-level truncated flag (None omits it).
    total_commits / commits_len: when both are given, a commits array
      of commits_len stub entries is included alongside total_commits
      (make them differ to simulate count/array mismatch - the
      paginated/capped response shape).
    """
    body_files = []
    for f in (files if files is not None else
              ["src/widgets/core.py", "src/widgets/render.py"]):
        body_files.append({"filename": f, "status": "modified"})
    for pf, nf in (renamed or []):
        body_files.append({"filename": nf, "status": "renamed",
                            "previous_filename": pf})
    payload = {
        "status": status,
        "ahead_by": 1 if status == "ahead" else 0,
        "behind_by": 0,
        "total_commits": 1 if status == "ahead" else 0,
        "commits": [{"sha": "e" * 40}] if status == "ahead" else [],
        "files": body_files,
    }
    if total_commits is not None:
        payload["total_commits"] = total_commits
        payload["commits"] = [{"sha": "f" * 40}
                              for _ in range(commits_len
                                             if commits_len is not None
                                             else total_commits)]
    if truncated is not None:
        payload["truncated"] = truncated
    return payload


def raw_checks_payload(runs=None, total=None):
    """Raw GitHub check-runs API response payload."""
    if runs is None:
        runs = [["ci", "completed", "success"]]
    body_runs = [{"name": r[0], "status": r[1], "conclusion": r[2]}
                 for r in runs]
    return {
        "total_count": len(body_runs) if total is None else total,
        "check_runs": body_runs,
    }


def raw_status_payload(state="success", total=1):
    """Raw GitHub combined-status API response payload."""
    return {"state": state, "total_count": total, "statuses": []}


def register_good_mocks(vm, repo=REPO, base=BASE_SHA, head=HEAD_SHA,
                        files=None, compare_status="ahead",
                        runs=None, status_state="success",
                        status_total=1):
    """Register the full good-path GitHub mock set (compare ahead +
    in-scope files, checks green, legacy status success)."""
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/compare/" + base + "\\.\\.\\." + head + "$",
        gh_body(raw_compare_payload(compare_status, files)))
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/commits/" + head + "/check-runs$",
        gh_body(raw_checks_payload(runs)))
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/commits/" + head + "/status$",
        gh_body(raw_status_payload(status_state, status_total)))


def register_poisoned_compare(vm, repo=REPO, base=BASE_SHA, head=HEAD_SHA,
                              http_status=404, body=None):
    """Replace ONLY the compare mock with a failing one. MUST be called
    INSTEAD of register_good_mocks (first-match-wins: a good compare
    mock registered earlier keeps answering forever)."""
    payload = body
    if payload is None:
        payload = {"message": "Not Found"}
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/compare/" + base + "\\.\\.\\." + head + "$",
        gh_body(payload, status_code=http_status))


def register_poisoned_checks(vm, repo=REPO, head=HEAD_SHA,
                             http_status=404, body=None):
    """Register ONLY a failing check-runs mock (no other mocks)."""
    payload = body
    if payload is None:
        payload = {"message": "Not Found"}
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/commits/" + head + "/check-runs$",
        gh_body(payload, status_code=http_status))


def register_renamed_mocks(vm, renamed, repo=REPO, base=BASE_SHA,
                           head=HEAD_SHA, compare_status="ahead",
                           runs=None, status_state="success"):
    """Register the full good-path mock set with a compare payload that
    contains renamed files (list of (previous, new) tuples). CI views
    are green so ONLY the rename scope logic decides the verdict."""
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/compare/" + base + "\\.\\.\\." + head + "$",
        gh_body(raw_compare_payload(compare_status, files=[],
                                    renamed=renamed)))
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/commits/" + head + "/check-runs$",
        gh_body(raw_checks_payload(runs)))
    vm.mock_web(
        "api\\.github\\.com/repos/" + repo.replace(".", "\\.")
        + "/commits/" + head + "/status$",
        gh_body(raw_status_payload(status_state)))


def cond_verdicts(statuses, evidence="API data substantiates this "
                   "condition"):
    """Build LLM-mock condition_checks from a list of statuses
    (1:1 with CONDITIONS order)."""
    conds = ["commit_ancestry", "diff_scope", "ci_status"]
    out = []
    for i, st in enumerate(statuses):
        out.append({"condition": conds[i], "status": st,
                    "evidence": evidence})
    return out


def mock_llm_verdict(vm, statuses, reasoning="All conditions evaluated "
                     "against the fetched GitHub API data.",
                     marker="verification oracle"):
    """Register the LLM mock returning this cross-check JSON. The
    prompt pattern keys on the stable prompt preamble so all runs of
    this contract hit it."""
    body = {
        "condition_checks": cond_verdicts(statuses),
        "reasoning": reasoning,
    }
    vm.mock_llm(marker, json.dumps(body))
