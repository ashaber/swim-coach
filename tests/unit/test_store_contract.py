"""Run the shared StoreInterface contract suite against FileStore.

The same suite runs against a real DbStore in tests/integration (gated on a
throwaway DB). Proving it here against FileStore proves the contract itself is
well-formed and that FileStore honors it.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from swim_coach.store import FileStore

# Make the shared suite (tests/store_contract.py) importable regardless of
# pytest's rootdir/import-mode.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from store_contract import StoreContractTests  # noqa: E402


class TestFileStoreContract(StoreContractTests):
    @pytest.fixture
    def store(self, tmp_path):
        return FileStore(base_dir=tmp_path)
