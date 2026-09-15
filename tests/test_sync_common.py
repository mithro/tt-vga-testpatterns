# SPDX-License-Identifier: Apache-2.0
"""common/hvsync_generator.v is the single source of truth; each design's
src/hvsync_generator.v is a copy kept in sync by scripts/sync_common.sh
(also `make sync-common`), since the Tiny Tapeout hardening flow only reads
a design's own src/ directory. This test catches a copy drifting from the
source without anyone re-running the sync script.
"""
from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO_ROOT / "common" / "hvsync_generator.v"
DESIGN_COPIES = sorted((REPO_ROOT / "designs").glob("*/src/hvsync_generator.v"))


def test_common_hvsync_generator_exists():
    assert COMMON.is_file()


def test_at_least_one_design_copy_found():
    assert DESIGN_COPIES, "no designs/*/src/hvsync_generator.v found"


@pytest.mark.parametrize("copy", DESIGN_COPIES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_design_copy_matches_common(copy: pathlib.Path):
    common_text = COMMON.read_text()
    copy_text = copy.read_text()
    assert copy_text == common_text, (
        f"{copy.relative_to(REPO_ROOT)} has drifted from common/hvsync_generator.v; "
        "run `make sync-common` (or scripts/sync_common.sh) and commit the result"
    )
