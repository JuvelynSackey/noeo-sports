"""Canonical ID helpers.

A provider's own id is only unique within that provider, so every entity we
persist is keyed as "<provider_name>:<provider_native_id>" to stay stable
across a provider swap or a secondary-provider failover (sections 5, 9, 10).
"""
from __future__ import annotations


def canonical_id(provider_name: str, native_id: str) -> str:
    return f"{provider_name}:{native_id}"
