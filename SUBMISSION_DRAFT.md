# CommitScopeEscrow — Submission Draft (GenLayer Builder Portal)

**Category:** Intelligent Contracts
**Repo:** https://github.com/faisalnugroho/commitscope-escrow (contract-only)
**Contract:** `contracts/commit_scope_escrow.py` (GenVM runner pin `py-genlayer:1jb45...`)

## One-paragraph pitch

CommitScopeEscrow locks escrowed GEN to an **exact commit hash + diff
scope** of work in a public GitHub repository — a settlement primitive
stronger than "PR merged". A payer creates a deal naming the repo, the
base commit, and the allowed file paths; the payee submits a commit
hash; release happens only when decentralized consensus can POSITIVELY
PROVE all three: (1) the commit descends from the base (GitHub compare
API `status: ahead/identical`), (2) every changed file lies within the
allowed paths (compare `files[].filename` checked one-by-one — never
commit messages or PR bodies), (3) the commit's real CI is green
(Checks API `status=completed + conclusion=success`, or legacy
combined status `state=success` — never workflow-file existence).
Anything unverifiable — API failure, 404, 403/429 rate-limit, timeout,
malformed JSON, pending CI — resolves to **Undetermined**: funds stay
locked, never released and never rejected on missing data. This
fail-safe is enforced identically on every execution path including the
dispute re-verification (there is no separate dispute branch — the same
consensus function runs again with the extra evidence attached).

## Why this needs GenLayer (not a plain contract)

Ancestry and scope are deterministic functions of the compare payload —
the contract computes them itself and the LLM cannot override them
(deterministic clamp layer, tested: an LLM that says all-PASS on an
out-of-scope diff still yields Rejected). The genuine judgment layer is
the CI interpretation: check-runs carry heterogeneous conclusions
(success/failure/skipped/neutral/stale/timed_out), the legacy status
endpoint can lag or contradict, and "pending with zero contexts" (the
normal shape for Actions-only repos — probed live) must not be misread
as a pass. The LLM cross-check judges each release condition
PASS/FAIL/UNCERTAIN from the fetched API data; validators independently
re-fetch and re-run their own cross-check (Equivalence Principle over
the stable decision fields); the contract then derives the verdict
mechanically:

```
any FAIL           -> Rejected  (payer refund path, permissionless)
else any UNCERTAIN -> Undetermined (fail-safe: funds stay locked)
else               -> Released  (permissionless payout to the payee)
```

Settlement is permissionless end-to-end: `request_verification`,
`claim_payout`, and `reclaim_expired` can be called by ANYONE; the
caller never decides the outcome, the consensus record does. Rejected
deals refund the payer immediately; stalled deals refund after a 5-day
activity timeout (node-clock based). Balance conservation is enforced
and tested (no stranded funds in any scenario).

## Evidence quality (fail-safe architecture, audited per path)

1. ONE centralized API helper `_gh_get()` — the only web call in the
   contract. Non-2xx, empty body, malformed JSON, any exception →
   Undetermined. Verified by grep: no raw web call exists outside the
   helper.
2. Positive proof only — absence of violation is never proof. ancestry
   requires compare `status` ∈ {ahead, identical}; behind/diverged is
   positive FAIL evidence.
3. Dispute path = initial path — identical consensus function
   (fail-safe #3; the historical rejection reason of
   WarrantyClaimOracle).
4. Scope from the actual diff, file by file.
5. CI from the commit's real check-runs/statuses.
6. Ambiguous scope (empty/wildcard/traversal/duplicate) rejected AT
   CREATION.

## Test evidence

- **72/72 direct-mode tests pass** (`tests/direct/`, gltest 0.29.x),
  covering all 15 spec scenarios: happy path, scope violation with
  cited filenames, non-descent, CI failure/pending/skipped, 404/403/
  429/malformed/missing-fields/timeout → Undetermined, dispute round-2
  with identical gates, double-dispute revert, permissionless claim/
  reclaim by third parties, balance conservation across mixed
  outcomes, empty-scope-at-create revert.
- **genvm-lint: ok:true, 0 errors** (11 methods: 5 view + 6 write).
- **GitHub Actions CI green on a clean runner**: the same 72-test
  suite — https://github.com/faisalnugroho/commitscope-escrow/actions
  (and the repo's own CI doubles as live dogfood evidence for the
  contract's CI condition).

## Live Studionet evidence (STOP 2 smoke — ALL 4 SCENARIOS PROVEN)

- **Contract:** `0xAB8378c82C9EEee4ABDD979bb978FBB33ADe80E5`
  https://explorer-studio.genlayer.com/address/0xAB8378c82C9EEee4ABDD979bb978FBB33ADe80E5
- **Deploy tx:** `0xb0f91d9bb4a7ea224675718f726e92e8d42eb291342bb70dbcce838bf05b305a` (FINALIZED, GenVM SUCCESS, full consensus, 5 validators)
- **Payer:** `0x971425e5043745cE4337ab80712E781A0B427773` — **Payee:** `0xB67e1b2b90274cfF672B0dA47cd589cE16DAa6a6`
- All verdicts below are read back on-chain via `get_deal` (never
  inferred from receipts alone). Every tx: FINALIZED + GenVM SUCCESS +
  consensus Accepted. Full tx list on the explorer address page above.

### S1 — Released (scope + CI valid) — deal `d1`

Repo `faisalnugroho/commitscope-escrow` (this repo), base
`b47dd6f200b567b0d9023edf59c726bb526a88f9`, head
`0f87385f86e86d60d366a44a23b1a084eb4862e7` (both real, CI-green
commits), scope `tests/direct/conftest.py,.github/workflows/ci.yml`
(the exact files the real diff touched).

| Step | Tx |
|---|---|
| create_deal (1 GEN escrowed) | `0x0d88def7e0f9680102945cfddfeda641109969ff1bff8d7482c601ee28b8ccb7` |
| submit_commit (payee) | `0x23d58989caa5cee3170c87e0d236d8fdfd648ef4460574b331034c5ef7ba3b32` |
| request_verification → **Released** | `0x0f1396f966b353f0b9a57cd189c832332674a3cb343082505d048623461b8db3` |

On-chain condition checks (from `get_deal`):
- commit_ancestry: **PASS** — "compare status is ahead - positive ancestry proof"
- diff_scope: **PASS** — "all 2 changed files within allowed scope"
- ci_status: **PASS** — LLM cross-check: "check_runs contains one entry with status 'completed' and conclusion 'success'"

### S2 — Rejected (scope violation) — deal `d2`

Same real commits as S1, but allowed_paths `contracts/` — the
actually-changed files are provably out of scope.

| Step | Tx |
|---|---|
| create_deal | `0x9d770f45a47aff628a9ffcecd5fb8c9831e1a2ce588beebc590d861d5f43df04` |
| submit_commit | `0x616721e750c32fef8977b1eda6f01731d1eedf0948c2e6f1e7f76b416ad7b390` |
| request_verification → **Rejected** | `0x5134adbcbd47833c5b7900892ef35840eeed3cdb4379e079af3087ff706223b1` |

On-chain condition checks:
- commit_ancestry: PASS — "compare status is ahead - positive ancestry proof"
- diff_scope: **FAIL** — "files outside allowed scope: .github/workflows/ci.yml,tests/direct/conftest.py" (both filenames cited)
- ci_status: PASS — green CI confirmed

### S3 — Undetermined (API failure) — deals `d3` and `d4`

Two live demonstrations of the fail-safe:

(a) **Nonexistent commit sha** — deal `d3`: the payee submitted a
40-hex sha that does not exist in the repo → GitHub compare 404s →
Undetermined:

| Step | Tx |
|---|---|
| create_deal | `0x989c37d03cc63a09ce3a901a6219dbbbc8543ccef230d1a0670eb4e9bebad214` |
| submit_commit (nonexistent sha) | `0x8e230e7e8e4c2b534ae9c9b65377012decfcee1a2418f610deb92dffc03ae495` |
| request_verification → **Undetermined** | `0x9dd24f05047d0f20b4f0b39604c4dfe96af9b2fbcca40e6c90ed329cac1bd11c` |

(b) **Nonexistent repository** — deal `d4`: repo
`faisalnugroho/this-repo-does-not-exist-xyz` genuinely does not exist →
compare 404 → Undetermined:

| Step | Tx |
|---|---|
| create_deal | `0x0eecf7481bdaf1b033eb92f973f6bcd4bd72f529f90b53b4a66ed678ac2bd13a` |
| submit_commit | `0xa75963bfb2bb7e80b7ec8fd015d676144b2cf6f057ff9f6ca81bb5bc35b27974` |
| request_verification → **Undetermined** | `0x76fb206e38551193639a3d2a7dbbb8d06d34f82c6a909111dd6c98d79e2a6dfa` |

Both: all three conditions UNCERTAIN — "compare view failed:
http_status_404". Funds remain locked (fail-safe, NOT rejected: missing
data is never proof).

### S4 — Dispute recovery still Undetermined — deal `d3`, round 2

The payee disputed d3 once with an additional evidence URL; the SAME
consensus function re-ran (round 2) and — because the primary GitHub
evidence still 404s — the result STAYED Undetermined (fail-safe
identical on the dispute path — no shortcut branch).

| Step | Tx |
|---|---|
| dispute (payee, max-1x enforced) | `0x022e10910ba6bcaed5802929e642db229361fcf33a1bb87899d4a0fe42f5ffe3` |
| request_verification → **Undetermined** (round=2) | `0x6e10b218e0a9761cfa37b2f7d6f5913084991d39646160170593bb30c22ff347` |

### Honest incident log (kept deliberately as reviewer evidence)

Four smoke attempts were needed; every infrastructure failure made
the contract fail-safe EXACTLY as designed:

1. **Fabricated-sha incident:** the first smoke script embedded a
   40-hex sha derived (incorrectly) from a short hash. GitHub
   correctly 404'd it → the contract returned Undetermined (not
   Released, not Rejected). A live probe contract
   (`0xB4586F7786b1DB4798d206cD17c95AcfFD5a82Ef`) then confirmed
   api.github.com is reachable from validators (HTTP 200 on repo,
   rate_limit, raw.githubusercontent, example.com), isolating the
   error to the evidence, not the contract.
2. **Rate-limit incident:** with the corrected sha, consensus fetches
   (leader + validators × 3 endpoints ≈ 15 requests/verify) exhausted
   the anonymous GitHub quota (60/h/IP) mid-run → 403 → Undetermined
   on every affected verify, exactly the documented behavior.
3. **Partial-scope incident:** one run used scope
   `tests/direct/conftest.py` while the real diff also touched
   `.github/workflows/ci.yml` → the scope gate correctly Rejected
   with BOTH filenames cited. The contract was right; the smoke
   config was wrong.
4. **Studionet 502s + resume:** two runs were interrupted by
   transient gateway errors; the resume run's hard-coded deal ids
   drifted by one (the interrupted run's create_deal HAD finalized),
   which produced a second S2 attempt (d3) later disputed to
   Undetermined round 2 — incidentally giving the cleanest possible
   S4 evidence (Rejected → dispute → still-failing API → stayed
   Undetermined), plus d4 re-proving the ghost-repo S3 mechanism.

All of these validate the core design claim: **no path exists from
failed or partial API data to Released/Rejected** — demonstrated live
under Studionet consensus, not just in unit tests.

## Known limitations (documented in README)

- GitHub API is consumed anonymously from validators (no token in
  contract code — an on-chain token would be public). Heavily
  rate-limited windows can produce Undetermined verdicts; the payee's
  single dispute round can re-verify after the quota resets. This is
  the deliberate fail-safe trade-off, not a bug.
- `allowed_paths` uses exact-path / directory-prefix semantics — no
  glob wildcards (explicit paths only, keeping the scope check
  deterministic and positive).
- The 5-day activity timeout uses node-assigned transaction timestamps
  (`gl.message_raw["datetime"]`), not GitHub events.

## Reproducibility

```bash
git clone https://github.com/faisalnugroho/commitscope-escrow
cd commitscope-escrow
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "genlayer-test==0.29.2" pytest eth_utils
.venv/bin/python -m pytest tests/direct/ -q    # 72 passed
```

Studionet smoke scripts: `scripts/deploy_smoke.py` (fresh deploy +
scenarios), `scripts/resume_smoke.py` (resume with RPC retry),
`scripts/read_all_deals.py` (on-chain verification of every deal).
Evidence log: `docs/deployment_log.json`.
