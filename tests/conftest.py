import pytest

from emporio_agent.db import StoreDB


@pytest.fixture(scope="session")
def db() -> StoreDB:
    return StoreDB()
