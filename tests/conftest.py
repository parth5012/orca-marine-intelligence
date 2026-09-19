import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "isro: marks test as validating ISRO SIH26176 requirements")


@pytest.fixture(autouse=True)
def reset_graph_cache():
    """Reset LangGraph compiled graph cache before each test."""
    import backend.agents.graph
    backend.agents.graph._compiled_graph = None
    yield
    backend.agents.graph._compiled_graph = None


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Reset in-memory rate limit state before and after each test."""
    try:
        from backend.core.security import clear_rate_limit_state

        clear_rate_limit_state()
    except Exception:
        pass
    yield
    try:
        from backend.core.security import clear_rate_limit_state

        clear_rate_limit_state()
    except Exception:
        pass
