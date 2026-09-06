# CommitScopeEscrow

A GenLayer Intelligent Contract that locks escrowed GEN to an **exact
commit hash + diff scope** of work in a public GitHub repository — a
stronger settlement primitive than "PR merged": release conditions are
anchored to immutable, independently re-fetchable GitHub API evidence.

Use cases: freelance milestone payment, DAO grant tranches, vendor
delivery payments — any agreement of the shape *"you may only touch
these paths; when you're done, the work commit must descend from this
base and its CI must be green"*.

## Release conditions (all three must hold, positively proven)

| # | Condition | Positive proof (GitHub API) |
|---|-----------|------------------------------|
| R1 | Submitted commit **exists in the agreed repo and descends from the agreed base commit** | compare API `status` field is `"ahead"` or `"identical"`; `"behind"`/`"diverged"` is positive proof of non-descent |
| R2 | **Every changed file lies within the agreed `allowed_paths`** | compare API `files[].filename`, compared one file at a time (exact path or directory prefix) — renames validated on BOTH `previous_filename` (source) and `filename` (destination); a capped/truncated compare response is partial evidence, never a proof — never commit messages or PR bodies |
| R3 | **The commit's real CI is green** | Checks API: every check-run `status="completed"` + `conclusion="success"`; or legacy combined status `state="success"`. Workflow-file existence proves nothing |

If any condition cannot be verified with positive proof (API failure,
404, rate-limit 403/429, timeout, malformed JSON, missing fields,
pending CI, ambiguous data) the deal resolves to **Undetermined** —
never Released, never Rejected on missing data. A Rejected verdict
always cites the specific out-of-scope filenames, the explicit
non-descent compare status, or the failed check names.

## Why GenLayer (the judgment layer)

Ancestry and scope are deterministic functions of the compare payload —
the contract computes them itself. But "is this commit's CI REALLY
green?" is an interpretation problem over heterogeneous, evolving API
data: check-runs carry conclusions (success/failure/skipped/neutral/
stale/…), the legacy status endpoint can lag or contradict, and
"pending with zero contexts" (the common shape for Actions-only repos)
must not be misread as a pass. Turning that raw evidence into per-
condition PASS/FAIL/UNCERTAIN judgments — and independently
re-verifying that interpretation via the Equivalence Principle
(leader proposal + validator cross-check over the same re-fetched
data) — is decentralized judgment with real on-chain GEN consequences.

The LLM never picks the outcome. It judges the three conditions; the
contract derives the verdict mechanically:

```
any FAIL           -> Rejected   (refund path for the payer)
else any UNCERTAIN -> Undetermined (funds stay locked, fail-safe)
else               -> Released  (permissionless payout to the payee)
```

Deterministic clamps bound what the LLM can conclude: ancestry and
scope are ALWAYS clamped to the API facts; an explicit CI failure
clamps to FAIL; ambiguous CI clamps PASS→UNCERTAIN (no release on
unproven CI). Only on provably-green data does the LLM's consensus-
verified interpretation stand.

## State machine

```
Open --submit_commit(payee)--> Submitted
Submitted --request_verification(anyone)--> UnderReview
    -> consensus -> Released | Rejected | Undetermined
Undetermined --dispute(payee, max 1, evidence URL)--> Submitted
    (the SAME permissionless verification re-runs - no separate branch)
Released --claim_payout(anyone)--> Paid
Rejected --reclaim_expired(anyone, immediate)--> Refunded
Open/Submitted/UnderReview/Undetermined
    --reclaim_expired(anyone, 5 days no activity)--> Refunded
```

Settlement is **permissionless**: `claim_payout` and `reclaim_expired`
can be called by anyone once conditions hold — the caller never
decides the outcome, the consensus record does. `total_locked` tracks
escrowed GEN; funds can never be stranded (rejected deals refund
immediately, stalled deals after a 5-day activity timeout).

## Fail-safe architecture (audited against every execution path)

1. **One centralized API helper** — `_gh_get()` is the only web call
   in the contract. Non-2xx (404/403/429/5xx), empty body, malformed
   JSON, or any exception is a fetch failure → Undetermined.
2. **Positive proof only** — absence of violation is never proof, and
   neither is partial evidence: a capped/truncated/paginated compare
   response (the compare API pages at 300 files) resolves to
   Undetermined, the same fail-safe as any API failure.
3. **Dispute path = initial path** — `request_verification` runs the
   identical consensus function for round 1 and round 2; no shortcut
   branch exists.
4. **Scope check from the actual diff** — `files[].filename` compared
   one-by-one against `allowed_paths`, and for renames BOTH the source
   (`previous_filename`) and destination (`filename`) must be in
   scope — an out-of-scope source cannot disappear via a rename.
5. **CI from the commit's real check-runs/statuses** — never from
   workflow-file existence.
6. **Ambiguous scope rejected at creation** — empty/wildcard/parent-
   traversal/duplicate paths revert in `create_deal`, so no
   unverifiable deal can ever exist.

## Equivalence principle

`gl.vm.run_nondet(leader_fn, validator_fn)` with partial-field
equivalence: validators re-fetch the same API views, re-run their own
LLM cross-check, apply the same deterministic clamps, and accept the
leader only when every per-condition status and the derived verdict
agree. Free text (reasoning) is never compared — only the stable
decision fields. If fetch outcomes differ between validators, the
transaction does not finalize and funds stay locked (fail-safe).

## Repo layout

```
contracts/commit_scope_escrow.py   the Intelligent Contract (only contract)
tests/direct/                      82 direct-mode tests (gltest)
.github/workflows/ci.yml           CI: the same pytest suite on Actions
pyproject.toml
```

This is a contract-only repository (Intelligent Contracts category
policy: no frontend/backend mixing).

## Running the tests

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python \
    genlayer-test pytest eth_utils
.venv/bin/python -m pytest tests/direct/ -q
```

The suite covers (see test files for the full matrix): happy path
Released; scope violation Rejected with cited filenames; non-descent
Rejected; CI failure/pending/skipped handling; 404/403/429/malformed/
missing-field/timeout → Undetermined; capped/truncated compare
(truncated flag, over-cap, at-cap boundary, commits-count mismatch) →
Undetermined; rename scope validation (out-of-scope source Rejected,
in-scope→in-scope Released, destination out-of-scope Rejected, missing
previous_filename Undetermined, mixed rename+modified Released);
dispute round-2 with identical gates; double-dispute revert;
permissionless claim/reclaim; balance conservation across mixed
outcomes; empty/ambiguous scope rejected at creation.

## Known limitations

- GitHub API responses are read anonymously (no token): heavily
  rate-limited repos can produce Undetermined verdicts — by design
  (fail-safe), and the payee can dispute once after the limit resets.
- `allowed_paths` uses exact-path / directory-prefix semantics — no
  glob wildcards (explicit paths only, to keep scope-checking
  deterministic and positive).
- The activity timeout (5 days) is measured from on-chain transaction
  activity (node-assigned timestamps), not from GitHub events.
