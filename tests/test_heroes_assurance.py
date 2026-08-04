from ks.heroes.assurance import (
    FieldAssurance,
    assurance_from_dict,
    assurance_to_dict,
    ensure_legacy,
    field_assurance,
    has_low,
    set_field,
)


def test_field_assurance_unknown_level_becomes_medium():
    a = field_assurance("wat", "x")
    assert a.level == "medium"
    assert a.reason == "x"


def test_set_field_and_round_trip_dict():
    m = set_field({}, "power", "high", "manual_confirm")
    assert m["power"] == FieldAssurance("high", "manual_confirm")
    assert assurance_from_dict(assurance_to_dict(m)) == m


def test_ensure_legacy_fills_missing_only():
    m = set_field({}, "power", "high", "manual_confirm")
    out = ensure_legacy(m, present_fields={"power": 1, "stars": 3})
    assert out["power"].level == "high"
    assert out["stars"] == FieldAssurance("medium", "legacy_unscored")


def test_has_low():
    m = set_field({}, "power", "low", "power_i_sources_disagree")
    assert has_low(m) is True
    assert has_low(set_field({}, "power", "high", "manual_confirm")) is False
