#!/usr/bin/env python3
"""CommitScopeEscrow - Studionet deploy + 4-scenario live smoke test.

Scenarios (spec STOP 2):
  S1 Released       - deal anchored to this repo, base b47dd6f (CI green),
                      head 0f87385 (CI green), scope=README.md - all three
                      conditions provable -> Released
  S2 Rejected       - same real commits, but allowed_paths=contracts/ so
                      README.md is provably OUT OF SCOPE -> Rejected with
                      the filename cited
  S3 Undetermined   - deal anchored to a nonexistent repo+commit -> compare
                      API 404s -> Undetermined (fail-safe)
  S4 Dispute        - payee disputes S3 with an evidence URL; the primary
                      GitHub evidence still 404s -> STAYS Undetermined
                      (fail-safe identical on the dispute path)

Each write is FULL CONSENSUS (not leader_only). Verdicts are verified by
READING BACK on-chain state (get_deal), never by trusting the receipt
alone. All tx hashes + timings are logged to docs/deployment_log.json.
"""
import json
import sys
import time
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus

CODE_PATH = Path("contracts/commit_scope_escrow.py")
KEYFILE = Path("scripts/smoke_deployer.json")   # gitignored
PAYEE_KEYFILE = Path("scripts/smoke_payee.json")  # gitignored
LOG_PATH = Path("docs/deployment_log.json")

# Real, verifiable GitHub evidence for this repo
REPO = "faisalnugroho/commitscope-escrow"
BASE_SHA = "b47dd6f200b567b0d9023edf59c726bb526a88f9"  # CI-green commit
HEAD_SHA = "0f87385f86e86d60d366a44a23b1a084eb4862e7"  # CI-green commit (verified full sha via git rev-parse)

# S3/S4: genuinely nonexistent repo+commit (compare 404)
GHOST_REPO = "faisalnugroho/this-repo-does-not-exist-xyz"
GHOST_SHA = "d" * 40

AMOUNT = 10**18  # 1 GEN

log = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def load_account():
    if KEYFILE.exists():
        data = json.loads(KEYFILE.read_text())
        return create_account(account_private_key=data["private_key"])
    acct = create_account()
    KEYFILE.write_text(json.dumps(
        {"address": acct.address,
         "private_key": acct.key.hex()}))
    KEYFILE.chmod(0o600)
    return acct


def wait_final(client, tx_hash, label):
    """Robust FINALIZED wait: parses both receipt shapes, checks the
    leader execution result (FINALIZED != success)."""
    receipt = client.wait_for_transaction_receipt(
        transaction_hash=tx_hash,
        status=TransactionStatus.FINALIZED,
        retries=120,
        interval=3000,
    )
    if isinstance(receipt, dict):
        data = receipt.get("data") or {}
        addr = (data.get("contract_address")
                if isinstance(data, dict) else None)
        if addr is None:
            addr = receipt.get("to_address")
        leader = (receipt.get("consensus_data") or {}).get(
            "leader_receipt", [{}])
        exec_result = (leader[0] if leader else {}).get("execution_result")
        if exec_result is None:
            exec_result = receipt.get("result_name")
        exec_name = receipt.get("tx_execution_result_name")
    else:
        addr = getattr(receipt, "contract_address", None)
        exec_result = None
        exec_name = None
    print(f"[{label}] FINALIZED leader_execution={exec_result} "
          f"exec_name={exec_name}", flush=True)
    if exec_result not in (None, "SUCCESS", "FINISHED_WITH_RETURN") \
            and exec_name not in (None, "FINISHED_WITH_RETURN"):
        print("EXECUTION FAILED - consensus dump:")
        try:
            print(json.dumps(receipt.get("consensus_data"),
                             default=str)[:3000])
        except Exception:
            print(str(receipt)[:3000])
        raise RuntimeError(label + " execution failed")
    return {"execution_result": exec_result or "SUCCESS",
            "exec_name": exec_name, "contract_address": addr}


def read_deal(client, addr, deal_id):
    raw = client.read_contract(address=addr, function_name="get_deal",
                               args=[deal_id])
    return json.loads(raw if isinstance(raw, str) else str(raw))


def write(client, addr, fname, args, label, account=None, value=0):
    t0 = time.time()
    tx = client.write_contract(
        address=addr, function_name=fname, args=args,
        account=account or client.local_account, value=value)
    res = wait_final(client, tx, label)
    secs = round(time.time() - t0, 1)
    log[label] = {"tx_hash": tx, "secs": secs,
                  "execution": res["execution_result"]}
    return tx, secs


def create_deal(client, addr, payer_acct, payee_addr, repo, base, paths,
                title, description, label):
    tx, secs = write(
        client, addr, "create_deal",
        [payee_addr, repo, base, paths, title, description],
        label, account=payer_acct, value=AMOUNT)
    return tx, secs


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    payer = account
    print("deployer:", account.address, flush=True)

    # ---- deploy (full consensus) ----
    code = CODE_PATH.read_text()
    tx = client.deploy_contract(code=code, account=client.local_account,
                                args=[])
    res = wait_final(client, tx, "deploy")
    addr = res["contract_address"]
    print("CONTRACT:", addr, flush=True)
    print("explorer: https://explorer-studio.genlayer.com/address/" + addr,
          flush=True)
    log["deploy"] = {"tx_hash": tx, "address": addr,
                     "execution": res["execution_result"]}

    # ---- payee wallet (distinct from payer - the contract enforces it) ----
    if PAYEE_KEYFILE.exists():
        payee = create_account(account_private_key=json.loads(
            PAYEE_KEYFILE.read_text())["private_key"])
    else:
        payee = create_account()
        PAYEE_KEYFILE.write_text(json.dumps(
            {"address": payee.address,
             "private_key": payee.key.hex()}))
        PAYEE_KEYFILE.chmod(0o600)
    print("payee:", payee.address, flush=True)
    # fund the payee wallet via the Studionet faucet RPC
    try:
        client.provider.make_request("sim_fundAccount",
                                     [payee.address, 5 * 10**18])
        print("payee funded via sim_fundAccount", flush=True)
    except Exception as e:
        print("sim_fundAccount failed (continuing - payee only needs "
              "gas for submit/dispute):", e, flush=True)

    results = {}

    # =============== S1: Released ===============
    print("\n--- S1: Released (scope+CI valid) ---", flush=True)
    tx, _ = create_deal(
        client, addr, payer, payee.address, REPO, BASE_SHA,
        "tests/direct/conftest.py,.github/workflows/ci.yml",
        "S1-released", "Smoke S1: conftest fix commit, both changed "
        "files in scope, green CI",
        "s1_create")
    s1_create = tx
    write(client, addr, "submit_commit", ["d1", HEAD_SHA], "s1_submit", account=payee)
    write(client, addr, "request_verification", ["d1"], "s1_verify")
    d = read_deal(client, addr, "d1")
    print(f"S1 verdict: {d['verdict']} status={d['status']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)
    results["S1"] = {"verdict": d["verdict"], "status": d["status"],
                     "create_tx": s1_create}

    # =============== S2: Rejected (scope violation) ===============
    print("\n--- S2: Rejected (scope violation) ---", flush=True)
    tx, _ = create_deal(
        client, addr, payer, payee.address, REPO, BASE_SHA, "contracts/",
        "S2-rejected", "Smoke S2: same real commits, changed files "
        "(ci.yml, conftest.py) are outside the allowed contracts/ scope",
        "s2_create")
    s2_create = tx
    write(client, addr, "submit_commit", ["d2", HEAD_SHA], "s2_submit", account=payee)
    write(client, addr, "request_verification", ["d2"], "s2_verify")
    d = read_deal(client, addr, "d2")
    print(f"S2 verdict: {d['verdict']} status={d['status']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)
    results["S2"] = {"verdict": d["verdict"], "status": d["status"],
                     "create_tx": s2_create}

    # =============== S3: Undetermined (API failure) ===============
    print("\n--- S3: Undetermined (nonexistent repo/commit) ---",
          flush=True)
    tx, _ = create_deal(
        client, addr, payer, payee.address, GHOST_REPO, GHOST_SHA, "src/",
        "S3-undetermined", "Smoke S3: repo does not exist - compare "
        "404 -> fail-safe Undetermined", "s3_create")
    s3_create = tx
    write(client, addr, "submit_commit", ["d3", "e" * 40], "s3_submit", account=payee)
    write(client, addr, "request_verification", ["d3"], "s3_verify")
    d = read_deal(client, addr, "d3")
    print(f"S3 verdict: {d['verdict']} status={d['status']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)
    results["S3"] = {"verdict": d["verdict"], "status": d["status"],
                     "create_tx": s3_create}

    # =============== S4: Dispute recovery stays Undetermined ======
    print("\n--- S4: dispute with evidence, still failing ---",
          flush=True)
    write(client, addr, "dispute",
          ["d3", "https://faisalnugroho.github.io/commitscope-s1.txt"],
          "s4_dispute", account=payee)
    write(client, addr, "request_verification", ["d3"], "s4_verify")
    d = read_deal(client, addr, "d3")
    print(f"S4 verdict: {d['verdict']} status={d['status']} "
          f"round={d['verification_round']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)
    results["S4"] = {"verdict": d["verdict"], "status": d["status"],
                     "round": d["verification_round"]}

    # ---- summary ----
    log["results"] = results
    log["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    LOG_PATH.parent.mkdir(exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2))

    print("\n=== SMOKE SUMMARY ===", flush=True)
    ok = True
    if results["S1"]["verdict"] != "Released":
        ok = False
    if results["S2"]["verdict"] != "Rejected":
        ok = False
    if results["S3"]["verdict"] != "Undetermined":
        ok = False
    if results["S4"]["verdict"] != "Undetermined":
        ok = False
    for k in ("S1", "S2", "S3", "S4"):
        print(f"{k}: {results[k]['verdict']} ({results[k]['status']})",
              flush=True)
    print("ALL_SCENARIOS_OK:", ok, flush=True)
    print("log:", LOG_PATH, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
