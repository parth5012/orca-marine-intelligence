import pytest


@pytest.fixture(autouse=True)
def reset_graph_cache():
    """Reset LangGraph compiled graph cache before each test."""
    import backend.agents.graph
    backend.agents.graph._compiled_graph = None
    yield
    backend.agents.graph._compiled_graph = None
