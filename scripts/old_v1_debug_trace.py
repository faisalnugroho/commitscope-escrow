#!/usr/bin/env python3
"""Debug a failed smoke tx: dump the full genvm stderr trace."""
import json
import sys
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet

KEYFILE = Path("scripts/smoke_deployer.json")


def main():
    tx = sys.argv[1]
    account = create_account(
        account_private_key=json.loads(KEYFILE.read_text())["private_key"])
    client = create_client(chain=studionet, account=account)
    trace = client.debug_trace_transaction(transaction_hash=tx)
    print(json.dumps(trace, indent=2, default=str)[:8000])


if __name__ == "__main__":
    main()
