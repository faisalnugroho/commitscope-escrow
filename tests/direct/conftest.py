"""Shared pytest fixtures for the CommitScopeEscrow direct-mode suite."""
import pytest

from gltest.direct.sdk_loader import setup_sdk_paths

setup_sdk_paths()

import genlayer
import sys
print(f"[CI-DEBUG] genlayer from: {genlayer.__file__}", file=sys.stderr)
print(f"[CI-DEBUG] allow_storage: {hasattr(genlayer, 'allow_storage')}", file=sys.stderr)

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
