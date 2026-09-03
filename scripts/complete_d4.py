#!/usr/bin/env python3
"""Complete deal d4 (ghost-repo S3) on the live contract: submit a
commit + request verification. d4's repo genuinely does not exist, so
consensus must fail-safe to Undetermined - the exact S3 mechanism from
the original smoke plan (the resume run's ID drift left d4 unverified)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deploy_smoke import load_account, wait_final, read_deal  # noqa
from resume_smoke import rpc_retry  # noqa

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet

CONTRACT = "0xAB8378c82C9EEee4ABDD979bb978FBB33ADe80E5"


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    payee = create_account(account_private_key=json.loads(
        Path("scripts/smoke_payee.json").read_text())["private_key"])

    # payee submits on d4 (ghost repo deal)
    def go_submit():
        tx = client.write_contract(
            address=CONTRACT, function_name="submit_commit",
            args=["d4", "e" * 40], account=payee)
        return tx, wait_final(client, tx, "d4_submit")

    tx1, _ = rpc_retry(go_submit, "d4_submit")
    print("d4 submit tx:", tx1)

    def go_verify():
        tx = client.write_contract(
            address=CONTRACT, function_name="request_verification",
            args=["d4"], account=client.local_account)
        return tx, wait_final(client, tx, "d4_verify")

    tx2, _ = rpc_retry(go_verify, "d4_verify")
    print("d4 verify tx:", tx2)

    d = read_deal(client, CONTRACT, "d4")
    print(f"d4: status={d['status']} verdict={d['verdict']}")
    for c in json.loads(d["condition_checks"]):
        print(f"  {c['condition']}: {c['status']} - {c['evidence']}")

    # persist
    log_path = Path("docs/deployment_log.json")
    log = json.loads(log_path.read_text())
    log["scenarios"]["S3_ghost_repo"] = {
        "deal": "d4",
        "verdict": d["verdict"], "status": d["status"],
        "submit_tx": tx1, "verify_tx": tx2,
        "condition_checks": json.loads(d["condition_checks"]),
        "note": "ghost repo - compare 404 (original S3 mechanism; run "
                "after resume-script ID drift left d4 unverified)",
    }
    log_path.write_text(json.dumps(log, indent=2))
    print("log updated")


if __name__ == "__main__":
    main()
