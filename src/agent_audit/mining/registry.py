"""Named-query registry for the deterministic mining layer.

The stable artifact identity (e.g. ``01_churn``) lives in each query's
own output ``name``; this registry key is the short CLI-/model-facing
handle used to look the query up.
"""

from __future__ import annotations

from collections.abc import Callable

from .churn import churn_query

REGISTRY: dict[str, Callable[..., dict]] = {
    "churn": churn_query,
}


def list_queries() -> list[str]:
    """Return the registered query names, sorted."""
    return sorted(REGISTRY)


def get_query(name: str) -> Callable[..., dict]:
    """Return the query callable for ``name``; raise KeyError if unknown."""
    return REGISTRY[name]
