#!/usr/bin/env python3
"""Read back all four live deals on the Studionet contract to pin the
exact deal_id -> scenario mapping and their verdicts."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from deploy_smoke import load_account, read_deal  # noqa

from genlayer_py import create_client
from genlayer_py.chains import studionet

CONTRACT = "0xAB8378c82C9EEee4ABDD979bb978FBB33ADe80E5"


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    for did in ("d1", "d2", "d3", "d4"):
        try:
            d = read_deal(client, CONTRACT, did)
            print(f"{did}: status={d['status']} verdict={d['verdict']} "
                  f"title={d['title']} repo={d['repo']} "
                  f"scope={d['allowed_paths'][:50]} "
                  f"disputes={d['dispute_count']} "
                  f"round={d['verification_round']}")
        except Exception as e:
            print(f"{did}: not found / error: {str(e)[:100]}")


if __name__ == "__main__":
    main()
