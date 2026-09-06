#!/usr/bin/env python3
"""Read back all deals on the NEW boundary-fix Studionet contract to
verify on-chain verdicts independently of the smoke script."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deploy_smoke import load_account, read_deal  # noqa

from genlayer_py import create_client
from genlayer_py.chains import studionet

CONTRACT = "0x68571BEABCA01fD4eBc720916E7367bC6f233280"


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    n = client.read_contract(address=CONTRACT,
                             function_name="get_total_deals", args=[])
    total = int(n) if not isinstance(n, str) else int(str(n))
    print("total deals:", total)
    for i in range(1, total + 1):
        did = "d" + str(i)
        try:
            d = read_deal(client, CONTRACT, did)
            print(f"{did}: status={d['status']} verdict={d['verdict']} "
                  f"round={d['verification_round']} "
                  f"title={d['title']}")
            for c in json.loads(d["condition_checks"]):
                print(f"    {c['condition']}: {c['status']} - "
                      f"{c['evidence']}")
        except Exception as e:
            print(f"{did}: error: {str(e)[:120]}")


if __name__ == "__main__":
    main()
