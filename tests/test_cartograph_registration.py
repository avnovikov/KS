"""Tests for robust global cartograph frame registration."""

from dataclasses import FrozenInstanceError

import cv2
import numpy as np
import pytest

from ks.cartograph.landmarks import NameLandmark
from ks.cartograph.mask import MaskConfig
from ks.cartograph import registration as registration_module
from ks.cartograph.registration import (
    GlobalRegistration,
    PairTranslation,
    RegistrationGraphError,
    RegistrationMetrics,
    RegistrationThresholdError,
    build_registration_constraints,
    competing_feature_track_pairs,
    match_static_translation,
    solve_frame_translations,
)


def _constraint(
    frame_a: str,
    frame_b: str,
    delta_x: float,
    delta_y: float,
    *,
    weight: float = 1.0,
    source: str = "synthetic",
    inliers: int = 30,
) -> PairTranslation:
    return PairTranslation(
        frame_a=frame_a,
        frame_b=frame_b,
        delta_x=delta_x,
        delta_y=delta_y,
        weight=weight,
        source=source,
        inliers=inliers,
    )


def _whole_frame_mask() -> MaskConfig:
    return MaskConfig(rects=(), fill=(0, 0, 0))


def _textured_image(seed: int = 7, size: int = 320) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = np.zeros((size, size, 3), dtype=np.uint8)
    for _ in range(180):
        center = tuple(int(value) for value in rng.integers(8, size - 8, size=2))
        color = tuple(int(value) for value in rng.integers(30, 255, size=3))
        radius = int(rng.integers(2, 7))
        cv2.circle(image, center, radius, color, -1)
    return image


def _translate_image(image: np.ndarray, delta: tuple[float, float]) -> np.ndarray:
    dx, dy = delta
    transform = np.float32([[1.0, 0.0, -dx], [0.0, 1.0, -dy]])
    return cv2.warpAffine(image, transform, (image.shape[1], image.shape[0]))


def test_match_static_translation_recovers_known_textured_shift() -> None:
    expected_delta = (24.0, -13.0)
    frame_a = _textured_image()
    frame_b = _translate_image(frame_a, expected_delta)

    constraint = match_static_translation(
        frame_a,
        frame_b,
        seed_delta=(20.0, -10.0),
        mask_cfg=_whole_frame_mask(),
    )

    assert constraint is not None
    assert (constraint.delta_x, constraint.delta_y) == pytest.approx(
        expected_delta,
        abs=0.75,
    )
    assert constraint.source == "static"
    assert constraint.inliers >= 8
    assert constraint.weight > 0.0


def test_match_static_translation_ignores_moving_sprite() -> None:
    expected_delta = (19.0, 11.0)
    frame_a = _textured_image(seed=11)
    frame_b = _translate_image(frame_a, expected_delta)
    cv2.rectangle(frame_a, (35, 35), (105, 105), (255, 255, 255), -1)
    cv2.rectangle(frame_b, (210, 195), (280, 265), (255, 255, 255), -1)
    cv2.putText(frame_a, "MOVING", (38, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
    cv2.putText(frame_b, "MOVING", (213, 235), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

    constraint = match_static_translation(
        frame_a,
        frame_b,
        seed_delta=expected_delta,
        mask_cfg=_whole_frame_mask(),
    )

    assert constraint is not None
    assert (constraint.delta_x, constraint.delta_y) == pytest.approx(
        expected_delta,
        abs=0.75,
    )


def test_match_static_translation_rejects_repeated_distractors() -> None:
    tile = np.zeros((32, 32, 3), dtype=np.uint8)
    cv2.circle(tile, (16, 16), 8, (255, 255, 255), 2)
    frame_a = np.tile(tile, (10, 10, 1))
    frame_b = np.roll(frame_a, shift=(9, 17), axis=(0, 1))

    constraint = match_static_translation(
        frame_a,
        frame_b,
        seed_delta=(-17.0, -9.0),
        mask_cfg=_whole_frame_mask(),
    )

    assert constraint is None


def test_competing_feature_track_pairs_empty_for_single_shift() -> None:
    expected_delta = (24.0, -13.0)
    frame_a = _textured_image(seed=3)
    frame_b = _translate_image(frame_a, expected_delta)
    frames = {"a": frame_a, "b": frame_b}
    offsets = {"a": (0.0, 0.0), "b": expected_delta}

    assert (
        competing_feature_track_pairs(
            frames,
            offsets,
            mask_cfg=_whole_frame_mask(),
        )
        == ()
    )


def test_competing_feature_track_pairs_reports_secondary_peak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = {
        "a": _textured_image(seed=1, size=160),
        "b": _textured_image(seed=2, size=160),
    }
    offsets = {"a": (0.0, 0.0), "b": (40.0, 0.0)}
    monkeypatch.setattr(
        registration_module,
        "_secondary_static_peak",
        lambda *args, **kwargs: (9.5, 22),
    )

    pairs = competing_feature_track_pairs(
        frames,
        offsets,
        mask_cfg=_whole_frame_mask(),
    )

    assert pairs == (("a", "b", 9.5, 22),)


def test_secondary_static_peak_ignores_weak_distractor_cluster() -> None:
    """Repeated texture with <20 secondary inliers must not count as competing."""
    primary_delta = (20.0, 0.0)
    frame_a = _textured_image(seed=21, size=360)
    frame_b = _translate_image(frame_a, primary_delta)
    # Small repeated patch at a conflicting translation (~40 px).
    patch = frame_a[40:90, 40:90].copy()
    frame_a[200:250, 200:250] = patch
    frame_b[200:250, 160:210] = patch

    secondary = registration_module._secondary_static_peak(
        frame_a,
        frame_b,
        primary_delta,
        _whole_frame_mask(),
        separation_px=3.0,
    )

    assert secondary is None


def test_match_static_translation_rejects_insufficient_inliers() -> None:
    frame_a = np.zeros((200, 200, 3), dtype=np.uint8)
    frame_b = frame_a.copy()
    for index in range(3):
        point = (40 + index * 55, 80)
        cv2.circle(frame_a, point, 5, (255, 255, 255), -1)
        cv2.circle(frame_b, (point[0] - 10, point[1]), 5, (255, 255, 255), -1)

    assert (
        match_static_translation(
            frame_a,
            frame_b,
            seed_delta=(10.0, 0.0),
            mask_cfg=_whole_frame_mask(),
        )
        is None
    )


def test_build_constraints_uses_correct_name_translation_sign() -> None:
    frames = {
        "a": np.zeros((100, 100, 3), dtype=np.uint8),
        "b": np.zeros((100, 100, 3), dtype=np.uint8),
    }
    landmarks = {
        "a": [NameLandmark("lord123456", 70.0, 45.0, 0.9)],
        "b": [NameLandmark("lord123456", 20.0, 55.0, 0.8)],
    }

    constraints = build_registration_constraints(
        frames,
        seed_offsets={"a": (0.0, 0.0), "b": (50.0, -10.0)},
        landmarks_by_frame=landmarks,
        mask_cfg=_whole_frame_mask(),
    )

    unique_name = next(item for item in constraints if item.source == "unique_name")
    assert unique_name.frame_a == "a"
    assert unique_name.frame_b == "b"
    assert (unique_name.delta_x, unique_name.delta_y) == (50.0, -10.0)
    assert unique_name.weight > max(
        item.weight for item in constraints if item.source == "prior"
    )


def test_build_constraints_excludes_ambiguous_names() -> None:
    frames = {
        "a": np.zeros((100, 100, 3), dtype=np.uint8),
        "b": np.zeros((100, 100, 3), dtype=np.uint8),
    }
    ambiguous = NameLandmark("ambig:alliancewoodmill", 50.0, 50.0, 0.9)

    constraints = build_registration_constraints(
        frames,
        seed_offsets={"a": (0.0, 0.0), "b": (25.0, 0.0)},
        landmarks_by_frame={"a": [ambiguous], "b": [ambiguous]},
        mask_cfg=_whole_frame_mask(),
    )

    assert not any(item.source == "unique_name" for item in constraints)


def test_build_constraints_filters_non_overlapping_seeded_bands() -> None:
    frames = {
        name: np.zeros((100, 100, 3), dtype=np.uint8)
        for name in ("a", "b", "far")
    }

    constraints = build_registration_constraints(
        frames,
        seed_offsets={"a": (0.0, 0.0), "b": (75.0, 0.0), "far": (500.0, 0.0)},
        landmarks_by_frame={},
        mask_cfg=_whole_frame_mask(),
    )

    pairs = {frozenset((item.frame_a, item.frame_b)) for item in constraints}
    assert frozenset(("a", "b")) in pairs
    assert not any("far" in pair for pair in pairs)


def test_seed_priors_connect_twenty_five_overlapping_frames() -> None:
    frames = {
        f"f{x}_{y}": np.zeros((100, 100, 3), dtype=np.uint8)
        for y in range(5)
        for x in range(5)
    }
    seed_offsets = {
        f"f{x}_{y}": (x * 75.0, y * 75.0)
        for y in range(5)
        for x in range(5)
    }

    constraints = build_registration_constraints(
        frames,
        seed_offsets=seed_offsets,
        landmarks_by_frame={},
        mask_cfg=_whole_frame_mask(),
    )
    registration = solve_frame_translations(
        constraints,
        reference_frame="f0_0",
        expected_frames=tuple(frames),
    )

    assert all(item.source == "prior" for item in constraints)
    assert registration.graph is not None
    assert registration.graph.connected_frame_count == 25


def test_aggregate_metrics_prefer_measurement_edges_over_soft_priors() -> None:
    """Aggregate thresholds use static/exact/unique-name residuals, not priors."""
    constraints = (
        _constraint("a", "b", 100.0, 0.0, weight=40.0, source="static", inliers=40),
        _constraint("b", "c", 100.0, 0.0, weight=40.0, source="static", inliers=40),
        _constraint("a", "c", 200.0, 0.0, weight=40.0, source="static", inliers=40),
        # Soft prior residual (~2.9px) would otherwise dominate p95/max.
        _constraint("a", "c", 202.9, 0.0, weight=0.2, source="prior", inliers=0),
    )

    registration = solve_frame_translations(
        constraints,
        reference_frame="a",
        expected_frames=("a", "b", "c"),
    )

    prior = next(item for item in registration.diagnostics if item.source == "prior")
    assert prior.accepted is True
    assert prior.residual_px == pytest.approx(2.9, abs=5e-2)
    assert registration.metrics.max_px < 1.0
    assert registration.metrics.p95_px < 1.0


def test_seed_priors_connect_grid_neighbors_without_pixel_overlap() -> None:
    """Grid-adjacent seed priors must keep the lattice connected.

    Real captures can have seed offsets with barely-overlapping or gapped
    bands; image matching stays gated on overlap, but exact seed priors still
    have to bridge every named grid neighbor.
    """
    frames = {
        "c0_center": np.zeros((100, 100, 3), dtype=np.uint8),
        "g_1_0": np.zeros((100, 100, 3), dtype=np.uint8),
        "g_2_0": np.zeros((100, 100, 3), dtype=np.uint8),
    }
    # Band width is 100; these centers are more than one band apart → no overlap.
    seed_offsets = {
        "c0_center": (0.0, 0.0),
        "g_1_0": (250.0, 0.0),
        "g_2_0": (500.0, 0.0),
    }

    constraints = build_registration_constraints(
        frames,
        seed_offsets=seed_offsets,
        landmarks_by_frame={},
        mask_cfg=_whole_frame_mask(),
    )
    registration = solve_frame_translations(
        constraints,
        reference_frame="c0_center",
        expected_frames=tuple(frames),
    )

    pairs = {frozenset((item.frame_a, item.frame_b)) for item in constraints}
    assert frozenset(("c0_center", "g_1_0")) in pairs
    assert frozenset(("g_1_0", "g_2_0")) in pairs
    assert all(item.source == "prior" for item in constraints)
    assert registration.graph is not None
    assert registration.graph.connected_frame_count == 3
    assert registration.frame_offsets["g_2_0"] == pytest.approx((500.0, 0.0))


def test_solve_frame_translations_exactly_recovers_offsets() -> None:
    constraints = (
        _constraint("center", "east", 10.0, -2.0),
        _constraint("east", "south", -6.0, 9.0),
        _constraint("center", "south", 4.0, 7.0),
    )

    registration = solve_frame_translations(
        constraints,
        reference_frame="center",
        expected_frames=("center", "east", "south"),
    )

    assert registration.frame_offsets["center"] == (0.0, 0.0)
    assert registration.frame_offsets["east"] == pytest.approx((10.0, -2.0))
    assert registration.frame_offsets["south"] == pytest.approx((4.0, 7.0))
    assert registration.metrics.connected_frames == (
        "center",
        "east",
        "south",
    )
    assert registration.metrics.max_px == pytest.approx(0.0, abs=1e-10)
    assert registration.accepted == constraints
    assert registration.rejected == ()


def test_solve_frame_translations_recovers_noisy_offsets() -> None:
    true_offsets = {
        "center": np.array((0.0, 0.0)),
        "east": np.array((12.0, -3.0)),
        "south": np.array((5.0, 8.0)),
        "corner": np.array((16.0, 6.0)),
    }
    edges = (
        ("center", "east", (0.10, -0.05), 4.0),
        ("center", "south", (-0.08, 0.12), 2.0),
        ("center", "corner", (0.04, -0.09), 1.0),
        ("east", "south", (0.03, 0.08), 3.0),
        ("east", "corner", (-0.06, -0.02), 5.0),
        ("south", "corner", (0.07, 0.04), 2.0),
    )
    constraints = tuple(
        _constraint(
            frame_a,
            frame_b,
            *(true_offsets[frame_b] - true_offsets[frame_a] + noise),
            weight=weight,
        )
        for frame_a, frame_b, noise, weight in edges
    )

    registration = solve_frame_translations(
        constraints,
        reference_frame="center",
        expected_frames=tuple(true_offsets),
    )

    for frame, expected_offset in true_offsets.items():
        assert registration.frame_offsets[frame] == pytest.approx(
            expected_offset,
            abs=0.15,
        )
    assert registration.metrics.p95_px < 0.25


def test_solve_frame_translations_rejects_high_weight_outlier() -> None:
    clean_constraints = (
        _constraint("center", "a", 10.0, 0.0),
        _constraint("center", "b", 20.0, 0.0),
        _constraint("center", "c", 30.0, 0.0),
        _constraint("a", "b", 10.0, 0.0),
        _constraint("b", "c", 10.0, 0.0),
        _constraint("a", "c", 20.0, 0.0),
    )
    bad_constraint = _constraint(
        "center",
        "c",
        -50.0,
        40.0,
        weight=1_000_000.0,
        source="bad-anchor",
    )

    registration = solve_frame_translations(
        (*clean_constraints, bad_constraint),
        reference_frame="center",
        expected_frames=("center", "a", "b", "c"),
    )

    assert registration.frame_offsets["c"] == pytest.approx((30.0, 0.0))
    assert registration.accepted == clean_constraints
    assert registration.rejected == (bad_constraint,)
    assert registration.metrics.max_px == pytest.approx(0.0, abs=1e-10)


def test_consensus_rejects_near_cutoff_huge_weight_edge() -> None:
    consensus = tuple(
        _constraint(
            "center" if index % 2 == 0 else "a",
            "a" if index % 2 == 0 else "center",
            0.0,
            0.0,
            source="static",
        )
        for index in range(12)
    )
    conflicting_prior = _constraint(
        "a",
        "center",
        -2.9,
        0.0,
        weight=1_000_000.0,
        source="weak_prior",
        inliers=0,
    )

    registration = solve_frame_translations(
        (*consensus, conflicting_prior),
        reference_frame="center",
        expected_frames=("center", "a"),
    )

    assert registration.frame_offsets["a"] == pytest.approx((0.0, 0.0), abs=1e-9)
    assert conflicting_prior in registration.rejected


def test_pair_local_consensus_does_not_reject_valid_noisy_subgraph() -> None:
    exact_zero_edges = tuple(
        _constraint("center", "a", 0.0, 0.0, source="exact")
        for _ in range(20)
    )
    noisy_cycle = (
        _constraint("a", "b", 0.0, 0.0, source="weak_prior"),
        _constraint("b", "c", 0.0, 0.0, source="weak_prior"),
        _constraint("a", "c", 1.2, 0.0, source="weak_prior"),
    )

    registration = solve_frame_translations(
        (*exact_zero_edges, *noisy_cycle),
        reference_frame="center",
        expected_frames=("center", "a", "b", "c"),
    )

    assert registration.rejected == ()
    assert registration.metrics.max_px == pytest.approx(0.4)


def test_surviving_moderate_weak_edge_receives_huber_attenuation() -> None:
    exact_zero_edges = tuple(
        _constraint("center", "a", 0.0, 0.0, source="exact")
        for _ in range(20)
    )
    moderate_cycle = (
        _constraint("a", "b", 0.0, 0.0, source="weak_prior"),
        _constraint("b", "c", 0.0, 0.0, source="weak_prior"),
        _constraint("a", "c", 5.4, 0.0, source="weak_prior"),
    )

    registration = solve_frame_translations(
        (*exact_zero_edges, *moderate_cycle),
        reference_frame="center",
        expected_frames=("center", "a", "b", "c"),
    )

    moderate_diagnostics = tuple(
        item
        for item in registration.diagnostics
        if item.constraint in moderate_cycle
    )
    assert all(item.accepted for item in moderate_diagnostics)
    assert all(item.residual_px == pytest.approx(1.8) for item in moderate_diagnostics)
    assert all(0.0 < item.effective_weight < 1.0 for item in moderate_diagnostics)


def test_final_weights_preserve_authority_with_bounded_ratio() -> None:
    weak = _constraint(
        "center",
        "a",
        0.0,
        0.0,
        weight=1.0,
        source="exact",
    )
    authoritative = _constraint(
        "center",
        "a",
        0.5,
        0.0,
        weight=1_000_000.0,
        source="exact",
    )

    registration = solve_frame_translations(
        (weak, authoritative),
        reference_frame="center",
        expected_frames=("center", "a"),
    )

    effective_weights = {
        diagnostic.constraint: diagnostic.effective_weight
        for diagnostic in registration.diagnostics
    }
    assert effective_weights[authoritative] / effective_weights[weak] == 100.0
    assert registration.frame_offsets["a"][0] == pytest.approx(50.0 / 101.0)


def test_weak_rejection_remains_in_immutable_diagnostics() -> None:
    exact_constraints = tuple(
        _constraint("center", "a", 0.0, 0.0, source="exact")
        for _ in range(4)
    )
    rejected_ncc = _constraint(
        "center",
        "a",
        8.0,
        0.0,
        source="ncc",
        inliers=0,
    )

    registration = solve_frame_translations(
        (*exact_constraints, rejected_ncc),
        reference_frame="center",
        expected_frames=("center", "a"),
    )

    rejected_diagnostic = next(
        item
        for item in registration.diagnostics
        if item.constraint == rejected_ncc
    )
    assert rejected_diagnostic.accepted is False
    assert rejected_diagnostic.residual_px == pytest.approx(8.0)
    assert rejected_diagnostic.effective_weight == 0.0
    assert rejected_diagnostic.source == "ncc"
    assert rejected_diagnostic.inliers == 0
    assert registration.graph.connected is True
    assert registration.graph.expected_frame_count == 2
    assert registration.graph.connected_frame_count == 2
    assert registration.graph.constraint_count == 5
    assert registration.graph.accepted_count == 4
    assert registration.graph.rejected_count == 1
    with pytest.raises(FrozenInstanceError):
        rejected_diagnostic.accepted = True


@pytest.mark.parametrize(
    ("source", "inliers", "delta"),
    [
        ("exact", 1, 2.9),
        ("unique_name", 1, 2.9),
        ("static", 20, 3.5),
    ],
)
def test_mandatory_constraint_violation_cannot_be_hidden_by_rejection(
    source: str,
    inliers: int,
    delta: float,
) -> None:
    consensus = tuple(
        _constraint("center", "a", 0.0, 0.0, source="synthetic")
        for _ in range(12)
    )
    mandatory = _constraint(
        "center",
        "a",
        delta,
        0.0,
        source=source,
        inliers=inliers,
    )

    with pytest.raises(RegistrationThresholdError) as caught:
        solve_frame_translations(
            (*consensus, mandatory),
            reference_frame="center",
            expected_frames=("center", "a"),
        )

    mandatory_diagnostic = next(
        item
        for item in caught.value.diagnostics
        if item.constraint == mandatory
    )
    assert mandatory_diagnostic.accepted is True
    assert mandatory_diagnostic.residual_px > (2.0 if source != "static" else 3.0)


def test_static_constraint_below_inlier_minimum_may_be_rejected() -> None:
    consensus = tuple(
        _constraint("center", "a", 0.0, 0.0, source="exact")
        for _ in range(4)
    )
    unsupported_static = _constraint(
        "center",
        "a",
        4.0,
        0.0,
        source="static",
        inliers=19,
    )

    registration = solve_frame_translations(
        (*consensus, unsupported_static),
        reference_frame="center",
        expected_frames=("center", "a"),
    )

    assert unsupported_static in registration.rejected


def test_solve_frame_translations_rejects_disconnected_graph() -> None:
    constraints = (
        _constraint("center", "a", 10.0, 0.0),
        _constraint("b", "c", 10.0, 0.0),
    )

    with pytest.raises(
        RegistrationGraphError,
        match="input constraint graph is disconnected.*b.*c",
    ) as caught:
        solve_frame_translations(
            constraints,
            reference_frame="center",
            expected_frames=("center", "a", "b", "c"),
        )

    assert caught.value.graph.connected is False
    assert caught.value.graph.connected_frame_count == 2
    assert caught.value.graph.design_rank < caught.value.graph.design_columns
    assert len(caught.value.diagnostics) == 2
    with pytest.raises(FrozenInstanceError):
        caught.value.graph.connected = True


def test_post_classification_disconnection_has_typed_diagnostics() -> None:
    constraints = (
        _constraint("center", "a", 0.0, 0.0, source="exact"),
        _constraint("center", "b", 0.0, 0.0, source="weak_prior"),
        _constraint("a", "b", 10.0, 0.0, source="ncc"),
    )

    with pytest.raises(
        RegistrationGraphError,
        match="post-classification constraint graph is disconnected",
    ) as caught:
        solve_frame_translations(
            constraints,
            reference_frame="center",
            expected_frames=("center", "a", "b"),
        )

    assert caught.value.graph.connected is False
    assert caught.value.graph.accepted_count == 1
    assert caught.value.graph.rejected_count == 2
    assert len(caught.value.diagnostics) == 3
    assert sum(item.accepted for item in caught.value.diagnostics) == 1


def test_solve_frame_translations_rejects_missing_reference() -> None:
    with pytest.raises(ValueError, match="reference frame.*missing"):
        solve_frame_translations(
            (_constraint("a", "b", 1.0, 2.0),),
            reference_frame="center",
            expected_frames=("a", "b"),
        )


def test_solve_frame_translations_fails_closed_above_residual_thresholds() -> None:
    inconsistent_cycle = (
        _constraint("center", "a", 0.0, 0.0),
        _constraint("a", "b", 0.0, 0.0),
        _constraint("center", "b", 6.0, 0.0),
    )

    with pytest.raises(
        RegistrationThresholdError,
        match="registration residual thresholds exceeded",
    ) as caught:
        solve_frame_translations(
            inconsistent_cycle,
            reference_frame="center",
            expected_frames=("center", "a", "b"),
        )

    assert caught.value.metrics.median_px > 1.0
    assert len(caught.value.diagnostics) == len(inconsistent_cycle)


@pytest.mark.parametrize("weight", [0.0, -1.0, np.inf, np.nan])
def test_solve_frame_translations_rejects_invalid_weights(weight: float) -> None:
    constraint = _constraint("center", "a", 1.0, 2.0, weight=weight)

    with pytest.raises(ValueError, match="finite and positive"):
        solve_frame_translations(
            (constraint,),
            reference_frame="center",
            expected_frames=("center", "a"),
        )


@pytest.mark.parametrize(
    ("source", "inliers", "message"),
    [
        ("", 1, "source must be non-empty"),
        ("   ", 1, "source must be non-empty"),
        ("static", -1, "inliers must be a nonnegative integer"),
        ("static", 1.5, "inliers must be a nonnegative integer"),
        ("static", True, "inliers must be a nonnegative integer"),
    ],
)
def test_solve_frame_translations_rejects_invalid_provenance(
    source: str,
    inliers: object,
    message: str,
) -> None:
    constraint = _constraint(
        "center",
        "a",
        1.0,
        2.0,
        source=source,
        inliers=inliers,
    )

    with pytest.raises(ValueError, match=message):
        solve_frame_translations(
            (constraint,),
            reference_frame="center",
            expected_frames=("center", "a"),
        )


def test_registration_records_are_immutable() -> None:
    constraint = _constraint("center", "a", 1.0, 2.0)
    registration = solve_frame_translations(
        (constraint,),
        reference_frame="center",
        expected_frames=("center", "a"),
    )

    with pytest.raises(FrozenInstanceError):
        constraint.weight = 2.0
    with pytest.raises(TypeError):
        registration.frame_offsets["a"] = (3.0, 4.0)


def test_global_registration_new_metadata_fields_have_compatible_defaults() -> None:
    metrics = RegistrationMetrics(0.0, 0.0, 0.0, ("center",))

    registration = GlobalRegistration(
        frame_offsets={"center": (0.0, 0.0)},
        metrics=metrics,
        accepted=(),
        rejected=(),
    )

    assert registration.diagnostics == ()
    assert registration.graph is None
    assert registration.world_to_pixel_matrix is None


def test_registration_reports_design_rank_and_condition_without_affine_matrix() -> None:
    registration = solve_frame_translations(
        (
            _constraint("center", "a", 1.0, 0.0),
            _constraint("a", "b", 1.0, 0.0),
            _constraint("center", "b", 2.0, 0.0),
        ),
        reference_frame="center",
        expected_frames=("center", "a", "b"),
    )

    assert registration.graph is not None
    assert registration.graph.design_rank == 2
    assert registration.graph.design_columns == 2
    assert np.isfinite(registration.graph.condition_number)
    assert registration.world_to_pixel_matrix is None
