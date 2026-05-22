"""Shared pytest configuration.

Normalizes Neo4j credential environment variables so both naming
conventions used across the test suite resolve to the same values:

    NEO4J_USER     ↔ NEO4J_USERNAME
    NEO4J_PASS     ↔ NEO4J_PASSWORD

This keeps the older `test_models_integration.py` (which uses
NEO4J_USER / NEO4J_PASS) and the newer `test_orm_neo4j.py` (which uses
NEO4J_USERNAME / NEO4J_PASSWORD) in sync regardless of which set the
user / CI exports.
"""
from __future__ import annotations

import os


_PAIRS = (
    ("NEO4J_USER", "NEO4J_USERNAME"),
    ("NEO4J_PASS", "NEO4J_PASSWORD"),
)


def _mirror_env() -> None:
    for a, b in _PAIRS:
        a_val = os.environ.get(a)
        b_val = os.environ.get(b)
        if a_val and not b_val:
            os.environ[b] = a_val
        elif b_val and not a_val:
            os.environ[a] = b_val


# Run once at collection time so fixtures see the mirrored values.
_mirror_env()
