from ks.heroes.optimize.combat_formation import ALL_SLOTS, FRONT, BACK


def test_slots_match_arena_shape() -> None:
    assert FRONT == ("F1", "F2")
    assert BACK == ("B1", "B2", "B3")
    assert ALL_SLOTS == FRONT + BACK
