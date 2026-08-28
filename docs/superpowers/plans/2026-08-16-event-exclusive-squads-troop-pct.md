# Event exclusive squads + troop % Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. Steps use checkbox syntax.

**Goal:** Swordland exclusive Garrison after Rally Lead; Bear one-click Joiner-without-lead; troop lines as % of capacity.

**Architecture:** Re-solve Swordland `garrison` in `_event_bundle` after `rally_lead`. Bear reuses `POST /api/optimize/beartrap/joiner`. Shared JS `troopsLine` formats percents.

**Tech Stack:** Python optimize_run, FastAPI UI static JS, pytest.

## Task 1: Swordland exclusive garrison

- [ ] Failing test: garrison heroes disjoint from rally_lead
- [ ] Implement re-solve in `_event_bundle` when `event.name == "swordland"`
- [ ] Green + commit

## Task 2: Bear Joiner-without-lead button

- [ ] HTML + JS button; call joiner API with roster − lead
- [ ] Page smoke asserts control id
- [ ] Commit

## Task 3: Troop % of capacity

- [ ] JS test or string-assert helper for `%` in troopsLine (events + board)
- [ ] Implement both `troopsLine` functions
- [ ] Commit
