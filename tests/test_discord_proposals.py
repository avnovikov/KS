"""Pending Discord proposal store tests."""

import time

import pytest

from ks.discord.proposals import PendingProposal, ProposalStore


def test_create_and_get_proposal():
    store = ProposalStore(ttl_seconds=300)
    pending = store.create(
        user_id=1,
        rationale="gather bread",
        actions=(),
    )
    assert isinstance(pending, PendingProposal)
    got = store.get(pending.id)
    assert got is not None
    assert got.rationale == "gather bread"
    assert got.user_id == 1


def test_pop_removes_proposal():
    store = ProposalStore(ttl_seconds=300)
    pending = store.create(user_id=1, rationale="x", actions=())
    popped = store.pop(pending.id)
    assert popped is not None
    assert store.get(pending.id) is None


def test_expired_proposal_returns_none(monkeypatch):
    store = ProposalStore(ttl_seconds=10)
    pending = store.create(user_id=1, rationale="x", actions=())
    monkeypatch.setattr(time, "monotonic", lambda: pending.created_at + 11)
    assert store.get(pending.id) is None


def test_ttl_must_be_positive():
    with pytest.raises(ValueError, match="ttl_seconds"):
        ProposalStore(ttl_seconds=0)
