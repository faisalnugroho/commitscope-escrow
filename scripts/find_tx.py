#!/usr/bin/env python3
"""Recover the failed s1_create tx hash from the Studionet explorer
queue of the deployer, then dump its debug trace."""
import json
import sys
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet

sys.path.insert(0, str(Path(__file__).parent))
from deploy_smoke import load_account, wait_final, CODE_PATH  # noqa

CONTRACT = "0x4Bc81006b5E89fe313b2b1725fee7A2c3A85A9D2"


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)

    # list all txs to the contract via consensus data contract
    cdc = client.chain.consensus_data_contract
    rec = cdc["address"]
    abi = [a for a in cdc["abi"] if a.get("type") == "function"
           and a["name"] in ("getLatestAcceptedTransactions",
                             "getLatestFinalizedTransactions")]
    # use provider eth_call via client's web3
    w3 = client
    # simpler: use getRecipientQueues on consensus data contract
    from web3 import Web3
    funcs = {a["name"]: a for a in cdc["abi"]
             if a.get("type") == "function"}
    qc = funcs["getRecipientQueues"]
    # encode call manually through w3 eth
    provider = client.provider
    # use JSON-RPC directly
    import requests
    url = client.chain.rpc_urls["default"]["http"][0]

    def rpc(method, params):
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1,
                                     "method": method, "params": params})
        return r.json().get("result")

    # eth_call getRecipientQueues(recipient=contract)
    # encode: function selector + address param
    selector = Web3.keccak(text="getRecipientQueues(address)")[:4].hex()
    addr_arg = CONTRACT[2:].lower().rjust(64, "0")
    data = "0x" + selector + addr_arg
    result = rpc("eth_call", [{"to": rec, "data": data}, "latest"])
    print("queues raw:", str(result)[:400])


if __name__ == "__main__":
    main()
