"""Shared pytest fixtures for the CommitScopeEscrow direct-mode suite."""
from pathlib import Path

import pytest

from gltest.direct.sdk_loader import setup_sdk_paths

# Pass the CONTRACT PATH so setup_sdk_paths parses the contract header
# and honors its runner pin (py-genlayer:1jb45...). Without the path,
# gltest falls back to the "latest" runner in the tarball, whose
# manifest points at the NEW std-lib (10pqy...) that no longer
# exports allow_storage -> every contract load fails with
# NameError: allow_storage.
CONTRACT_PATH = Path(__file__).resolve().parents[2] / \
    "contracts" / "commit_scope_escrow.py"
setup_sdk_paths(CONTRACT_PATH)

import helpers as H


@pytest.fixture()
def env(direct_vm, direct_deploy):
    """Fresh deployed contract with transfer hook + balance + clean clock."""
    vm = direct_vm
    H.set_time(vm, H.iso_now())
    c = direct_deploy(H.CONTRACT)
    H.install_transfer_hook(vm)
    H.fund_contract(vm)
    return c
