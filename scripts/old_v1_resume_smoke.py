#!/usr/bin/env python3
"""Resume the live smoke on the ALREADY-DEPLOYED contract:
- d1 already Released (S1 proven live, recorded).
- Runs S2 (scope violation), S3 (nonexistent repo), S4 (dispute),
  with RPC retry so transient 502s don't kill the run.
Writes docs/deployment_log.json (merge with deploy record).
"""
import json
import time
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus

sys_path = Path(__file__).parent
import sys
sys.path.insert(0, str(sys_path))
from deploy_smoke import (load_account, wait_final, read_deal,  # noqa
                          REPO, BASE_SHA, HEAD_SHA, GHOST_REPO, GHOST_SHA,
                          AMOUNT, LOG_PATH)

# The live contract from the interrupted run (d1 already Released)
CONTRACT = "0xAB8378c82C9EEee4ABDD979bb978FBB33ADe80E5"
DEPLOY_TX = None  # fill from earlier explorer evidence


def rpc_retry(fn, label, attempts=6, wait=30):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"[{label}] attempt {i+1} failed: {str(e)[:120]}",
                  flush=True)
            time.sleep(wait)
    raise RuntimeError(label + " failed after retries: " + str(last))


def write(client, addr, fname, args, label, account=None, value=0):
    t0 = time.time()

    def go():
        tx = client.write_contract(
            address=addr, function_name=fname, args=args,
            account=account or client.local_account, value=value)
        return tx, wait_final(client, tx, label)

    tx, res = rpc_retry(go, label)
    secs = round(time.time() - t0, 1)
    return tx, secs


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    payer = account
    payee = create_account(account_private_key=json.loads(
        Path("scripts/smoke_payee.json").read_text())["private_key"])
    addr = CONTRACT
    print("contract:", addr, flush=True)

    # rebuild the log from what is already proven + what we run now
    log = {"contract": addr, "scenarios": {}}

    def read_deal_r(cid):
        return rpc_retry(lambda: read_deal(client, addr, cid),
                         "read " + cid)

    # ---- S1 record (already on-chain from the interrupted run) ----
    d = read_deal_r("d1")
    log["scenarios"]["S1"] = {
        "verdict": d["verdict"], "status": d["status"],
        "note": "proven live in the interrupted run; read back now",
        "condition_checks": json.loads(d["condition_checks"]),
    }
    print(f"S1 (recorded): {d['verdict']} / {d['status']}", flush=True)

    # =============== S2: Rejected (scope violation) ===============
    print("\n--- S2: Rejected (scope violation) ---", flush=True)
    tx, _ = write(client, addr, "create_deal",
                  [payee.address, REPO, BASE_SHA, "contracts/",
                   "S2-rejected", "Smoke S2: changed files (ci.yml, "
                   "conftest.py) are outside the allowed contracts/ "
                   "scope"], "s2_create", account=payer, value=AMOUNT)
    s2_create = tx
    write(client, addr, "submit_commit", ["d2", HEAD_SHA], "s2_submit",
          account=payee)
    write(client, addr, "request_verification", ["d2"], "s2_verify")
    d = read_deal_r("d2")
    print(f"S2 verdict: {d['verdict']} status={d['status']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)
    log["scenarios"]["S2"] = {"verdict": d["verdict"],
                              "status": d["status"],
                              "create_tx": s2_create,
                              "condition_checks":
                              json.loads(d["condition_checks"])}

    # =============== S3: Undetermined (API failure) ===============
    print("\n--- S3: Undetermined (nonexistent repo/commit) ---",
          flush=True)
    tx, _ = write(client, addr, "create_deal",
                  [payee.address, GHOST_REPO, GHOST_SHA, "src/",
                   "S3-undetermined", "Smoke S3: repo does not exist - "
                   "compare 404 -> fail-safe Undetermined"],
                  "s3_create", account=payer, value=AMOUNT)
    s3_create = tx
    write(client, addr, "submit_commit", ["d3", "e" * 40], "s3_submit",
          account=payee)
    write(client, addr, "request_verification", ["d3"], "s3_verify")
    d = read_deal_r("d3")
    print(f"S3 verdict: {d['verdict']} status={d['status']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)
    log["scenarios"]["S3"] = {"verdict": d["verdict"],
                              "status": d["status"],
                              "create_tx": s3_create,
                              "condition_checks":
                              json.loads(d["condition_checks"])}

    # =============== S4: dispute, still failing ===============
    print("\n--- S4: dispute with evidence, still failing ---",
          flush=True)
    write(client, addr, "dispute",
          ["d3", "https://faisalnugroho.github.io/commitscope-s1.txt"],
          "s4_dispute", account=payee)
    write(client, addr, "request_verification", ["d3"], "s4_verify")
    d = read_deal_r("d3")
    print(f"S4 verdict: {d['verdict']} status={d['status']} "
          f"round={d['verification_round']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)
    log["scenarios"]["S4"] = {"verdict": d["verdict"],
                              "status": d["status"],
                              "round": d["verification_round"],
                              "condition_checks":
                              json.loads(d["condition_checks"])}

    Path("docs/deployment_log.json").write_text(json.dumps(log, indent=2))
    ok = (log["scenarios"]["S1"]["verdict"] == "Released"
          and log["scenarios"]["S2"]["verdict"] == "Rejected"
          and log["scenarios"]["S3"]["verdict"] == "Undetermined"
          and log["scenarios"]["S4"]["verdict"] == "Undetermined")
    print("\n=== RESUME SMOKE SUMMARY ===", flush=True)
    for k in ("S1", "S2", "S3", "S4"):
        s = log["scenarios"][k]
        print(f"{k}: {s['verdict']} ({s['status']})", flush=True)
    print("ALL_SCENARIOS_OK:", ok, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
