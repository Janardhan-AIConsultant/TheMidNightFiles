import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.workflows.support import Env  # noqa: E402


@pytest.fixture()
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    from backend.orchestration.checkpoint_manager import close_checkpointer
    close_checkpointer(e.ckpt)
    e.engine.dispose()
