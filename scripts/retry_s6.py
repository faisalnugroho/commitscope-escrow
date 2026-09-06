#!/usr/bin/env python3
"""Retry S6 (deal d5 on the boundary-fix contract): the payee disputes
the rate-limited Undetermined verdict (the contract's designed
recovery path - dispute moves the deal back to Submitted and the SAME
consensus re-runs). If the validators' GitHub quota has recovered, the
re-run resolves to Rejected with the out-of-scope source path cited.

Exit code 0 only when d5's verdict reads back as Rejected AND the
diff_scope evidence cites docs/smoke_rename_provenance.md.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deploy_smoke import (load_account, read_deal, wait_final,
                          PAYEE_KEYFILE)  # noqa

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet

CONTRACT = "0x68571BEABCA01fD4eBc720916E7367bC6f233280"
DEAL = "d5"
LOG_PATH = Path("docs/deployment_log.json")


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    payee = create_account(account_private_key=json.loads(
        PAYEE_KEYFILE.read_text())["private_key"])

    d = read_deal(client, CONTRACT, DEAL)
    print(f"d5 before: status={d['status']} verdict={d['verdict']} "
          f"disputes={d['dispute_count']}", flush=True)
    if d["status"] != "Undetermined":
        if d["verdict"] == "Rejected":
            print("already Rejected - nothing to do", flush=True)
            return 0
        print("d5 not in Undetermined - abort", flush=True)
        return 1

    log = json.loads(LOG_PATH.read_text())
    log["s6_retry"] = {}

    # the payee disputes (max-1 enforced) -> Submitted -> re-verify
    t0 = time.time()
    tx = client.write_contract(
        address=CONTRACT, function_name="dispute",
        args=[DEAL, "https://faisalnugroho.github.io/commitscope-s1.txt"],
        account=payee)
    wait_final(client, tx, "s6_dispute")
    log["s6_retry"]["dispute_tx"] = tx
    log["s6_retry"]["dispute_secs"] = round(time.time() - t0, 1)
    print("dispute tx:", tx, flush=True)

    t0 = time.time()
    tx = client.write_contract(
        address=CONTRACT, function_name="request_verification",
        args=[DEAL], account=account)
    wait_final(client, tx, "s6_verify_round2")
    log["s6_retry"]["verify_tx"] = tx
    log["s6_retry"]["verify_secs"] = round(time.time() - t0, 1)
    print("verify round2 tx:", tx, flush=True)

    d = read_deal(client, CONTRACT, DEAL)
    print(f"d5 after: status={d['status']} verdict={d['verdict']} "
          f"round={d['verification_round']}", flush=True)
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}",
              flush=True)

    log["s6_retry"]["verdict"] = d["verdict"]
    log["s6_retry"]["round"] = d["verification_round"]
    log["s6_retry"]["condition_checks"] = json.loads(
        d["condition_checks"])
    log["results"]["S6"] = {
        "verdict": d["verdict"], "status": d["status"],
        "round": d["verification_round"],
        "create_tx": log["s6_create"]["tx_hash"],
        "submit_tx": log["s6_submit"]["tx_hash"],
        "first_verify_tx": log["s6_verify"]["tx_hash"],
        "dispute_tx": log["s6_retry"]["dispute_tx"],
        "verify_round2_tx": log["s6_retry"]["verify_tx"],
        "condition_checks": json.loads(d["condition_checks"]),
    }
    LOG_PATH.write_text(json.dumps(log, indent=2))

    scope_ev = ""
    for c in json.loads(d["condition_checks"]):
        if c["condition"] == "diff_scope":
            scope_ev = c["evidence"]
    ok = (d["verdict"] == "Rejected"
          and "docs/smoke_rename_provenance.md" in scope_ev)
    print("S6_RETRY_OK:", ok, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
