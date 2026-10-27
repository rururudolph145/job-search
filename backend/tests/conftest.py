"""Shared pytest hooks for the backend test suite."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Run coroutine tests in a fresh event loop.

    The suite has no async plugin installed, and adding one for a handful of
    coroutine tests would outweigh the benefit. Return ``None`` for sync tests
    so pytest's default handling applies.
    """
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None
    kwargs: dict[str, Any] = {
        arg: pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test_func(**kwargs))
    return True
