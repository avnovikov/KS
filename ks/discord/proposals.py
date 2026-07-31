"""In-memory pending proposals for Discord Approve/Reject buttons."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class PendingProposal:
    id: str
    user_id: int
    rationale: str
    actions: Sequence[Any]
    created_at: float = field(default_factory=time.monotonic)


class ProposalStore:
    """TTL-backed store for Discord button confirmation state."""

    def __init__(self, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive; got {ttl_seconds}")
        self._ttl_seconds = ttl_seconds
        self._items: dict[str, PendingProposal] = {}

    def create(
        self,
        *,
        user_id: int,
        rationale: str,
        actions: Sequence[Any],
    ) -> PendingProposal:
        pending = PendingProposal(
            id=secrets.token_urlsafe(12),
            user_id=user_id,
            rationale=rationale,
            actions=tuple(actions),
        )
        self._items[pending.id] = pending
        return pending

    def get(self, proposal_id: str) -> PendingProposal | None:
        pending = self._items.get(proposal_id)
        if pending is None:
            return None
        if time.monotonic() - pending.created_at > self._ttl_seconds:
            self._items.pop(proposal_id, None)
            return None
        return pending

    def pop(self, proposal_id: str) -> PendingProposal | None:
        pending = self.get(proposal_id)
        if pending is None:
            return None
        self._items.pop(proposal_id, None)
        return pending
