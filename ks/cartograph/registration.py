"""Robust global translation registration for cartograph frames."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from numbers import Integral
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from ks.cartograph.landmarks import NameLandmark, is_registration_landmark_name
from ks.cartograph.mask import (
    MaskConfig,
    bluestacks_mask_config,
    mask_and_crop,
)

MEDIAN_RESIDUAL_LIMIT_PX = 1.0
P95_RESIDUAL_LIMIT_PX = 2.0
MAX_RESIDUAL_LIMIT_PX = 3.0
MAD_SCALE_FACTOR = 1.4826
MIN_CONSENSUS_CUTOFF_PX = 0.25
MAX_ACCEPTED_WEIGHT_RATIO = 100.0
EXACT_RESIDUAL_LIMIT_PX = 2.0
STATIC_RESIDUAL_LIMIT_PX = 3.0
HUBER_DELTA_FRACTION = 0.5
HUBER_MAX_ITERATIONS = 25
HUBER_CONVERGENCE_PX = 1e-9
SIFT_RATIO_LIMIT = 0.72
STATIC_SEED_RADIUS_PX = 80.0
STATIC_INLIER_RADIUS_PX = 3.0
MIN_STATIC_INLIERS = 8
# Competing peaks must be strong enough to threaten stitch uniqueness.
# Aligns with design: residual gates apply when an overlap has ≥20 inliers.
MIN_COMPETING_SECONDARY_INLIERS = 20
MAX_STATIC_WEIGHT_INLIERS = 50
MIN_OVERLAP_AREA_FRACTION = 0.10
MIN_OVERLAP_DIMENSION_PX = 16.0
UNIQUE_NAME_WEIGHT = 40.0
PRIOR_WEIGHT = 0.2
WorldToPixelMatrix = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
]


@dataclass(frozen=True)
class PairTranslation:
    """Measured translation from one frame offset to another."""

    frame_a: str
    frame_b: str
    delta_x: float
    delta_y: float
    weight: float
    source: str
    inliers: int


def _frame_image(frame: Any) -> np.ndarray:
    image = frame if isinstance(frame, np.ndarray) else getattr(frame, "image", None)
    if not isinstance(image, np.ndarray):
        raise TypeError("frame must be an image array or expose an image array")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"frame image must be HxWx3; got {image.shape}")
    return image


def _frame_name(frame: Any, fallback: str) -> str:
    name = getattr(frame, "name", fallback)
    return name if isinstance(name, str) and name else fallback


def _static_feature_mask(band: np.ndarray, fill: tuple[int, int, int]) -> np.ndarray:
    """Keep map texture while suppressing fill, crop edges, and tiny transients."""
    fill_color = np.asarray(fill, dtype=band.dtype)
    valid = (~np.all(band == fill_color, axis=2)).astype(np.uint8) * 255
    valid = cv2.erode(valid, np.ones((5, 5), dtype=np.uint8), iterations=1)
    edge = min(8, band.shape[0] // 8, band.shape[1] // 8)
    if edge:
        valid[:edge] = 0
        valid[-edge:] = 0
        valid[:, :edge] = 0
        valid[:, -edge:] = 0
    return valid


def _ratio_matches(
    descriptors_a: np.ndarray,
    descriptors_b: np.ndarray,
) -> list[cv2.DMatch]:
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    forward = matcher.knnMatch(descriptors_a, descriptors_b, k=2)
    reverse = matcher.knnMatch(descriptors_b, descriptors_a, k=2)
    reverse_best = {
        pair[0].queryIdx: pair[0].trainIdx
        for pair in reverse
        if len(pair) == 2
        and pair[0].distance <= SIFT_RATIO_LIMIT * pair[1].distance
    }
    return [
        best
        for pair in forward
        if len(pair) == 2
        for best, second in (pair,)
        if best.distance <= SIFT_RATIO_LIMIT * second.distance
        and reverse_best.get(best.trainIdx) == best.queryIdx
    ]


def match_static_translation(
    frame_a: Any,
    frame_b: Any,
    seed_delta: tuple[float, float],
    mask_cfg: MaskConfig | None,
) -> PairTranslation | None:
    """Match static map texture as ``offset_b - offset_a`` near a seed."""
    if len(seed_delta) != 2 or not np.isfinite(seed_delta).all():
        raise ValueError(f"seed_delta must contain two finite values; got {seed_delta!r}")
    config = mask_cfg or bluestacks_mask_config()
    band_a = mask_and_crop(_frame_image(frame_a), config)
    band_b = mask_and_crop(_frame_image(frame_b), config)
    gray_a = cv2.cvtColor(band_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(band_b, cv2.COLOR_BGR2GRAY)
    sift = cv2.SIFT_create()
    keypoints_a, descriptors_a = sift.detectAndCompute(
        gray_a,
        _static_feature_mask(band_a, config.fill),
    )
    keypoints_b, descriptors_b = sift.detectAndCompute(
        gray_b,
        _static_feature_mask(band_b, config.fill),
    )
    if descriptors_a is None or descriptors_b is None:
        return None

    matches = _ratio_matches(descriptors_a, descriptors_b)
    if not matches:
        return None
    translations = np.asarray(
        [
            np.asarray(keypoints_a[match.queryIdx].pt)
            - np.asarray(keypoints_b[match.trainIdx].pt)
            for match in matches
        ],
        dtype=float,
    )
    seed = np.asarray(seed_delta, dtype=float)
    translations = translations[
        np.linalg.norm(translations - seed, axis=1) <= STATIC_SEED_RADIUS_PX
    ]
    if len(translations) < MIN_STATIC_INLIERS:
        return None

    translation = np.median(translations, axis=0)
    residuals = np.linalg.norm(translations - translation, axis=1)
    inlier_mask = residuals <= STATIC_INLIER_RADIUS_PX
    inlier_count = int(inlier_mask.sum())
    if inlier_count < MIN_STATIC_INLIERS:
        return None
    inlier_translations = translations[inlier_mask]
    translation = np.median(inlier_translations, axis=0)
    inlier_residuals = np.linalg.norm(inlier_translations - translation, axis=1)
    quality = 1.0 / (1.0 + float(np.median(inlier_residuals)))
    weight = min(inlier_count, MAX_STATIC_WEIGHT_INLIERS) * quality / 5.0
    return PairTranslation(
        frame_a=_frame_name(frame_a, "frame_a"),
        frame_b=_frame_name(frame_b, "frame_b"),
        delta_x=float(translation[0]),
        delta_y=float(translation[1]),
        weight=max(weight, 0.1),
        source="static",
        inliers=inlier_count,
    )


def competing_feature_track_pairs(
    frames: Mapping[str, Any] | Sequence[Any],
    frame_offsets: Mapping[str, tuple[float, float]],
    *,
    mask_cfg: MaskConfig | None = None,
    separation_px: float = STATIC_RESIDUAL_LIMIT_PX,
) -> tuple[tuple[str, str, float, int], ...]:
    """Find overlapping pairs with a second strong translation cluster.

    Returns ``(frame_a, frame_b, separation_px, secondary_inliers)`` for pairs
    whose secondary peak is farther than ``separation_px`` from the primary
    and still has at least ``MIN_COMPETING_SECONDARY_INLIERS`` support.
    """
    if separation_px <= 0:
        raise ValueError(f"separation_px must be positive; got {separation_px}")
    named_frames = _named_frames(frames)
    if set(named_frames) != set(frame_offsets):
        missing = sorted(set(named_frames) - set(frame_offsets))
        extra = sorted(set(frame_offsets) - set(named_frames))
        raise ValueError(
            f"frame_offsets must match frames; missing={missing}, extra={extra}"
        )
    config = mask_cfg or bluestacks_mask_config()
    band_shapes = {
        name: mask_and_crop(_frame_image(frame), config).shape[:2]
        for name, frame in named_frames.items()
    }
    competing: list[tuple[str, str, float, int]] = []
    for frame_a, frame_b in combinations(named_frames, 2):
        offset_a = frame_offsets[frame_a]
        offset_b = frame_offsets[frame_b]
        if not _bands_overlap_enough(
            offset_a,
            band_shapes[frame_a],
            offset_b,
            band_shapes[frame_b],
        ):
            continue
        seed_delta = (
            float(offset_b[0] - offset_a[0]),
            float(offset_b[1] - offset_a[1]),
        )
        secondary = _secondary_static_peak(
            named_frames[frame_a],
            named_frames[frame_b],
            seed_delta,
            config,
            separation_px=separation_px,
        )
        if secondary is not None:
            competing.append((frame_a, frame_b, secondary[0], secondary[1]))
    return tuple(competing)


def _secondary_static_peak(
    frame_a: Any,
    frame_b: Any,
    seed_delta: tuple[float, float],
    mask_cfg: MaskConfig,
    *,
    separation_px: float,
) -> tuple[float, int] | None:
    """Return (distance, inliers) for a competing translation cluster, if any.

    Weak secondaries (repeated trees/rocks with ~MIN_STATIC_INLIERS support)
    are ignored; only clusters that could threaten uniqueness (≥
    ``MIN_COMPETING_SECONDARY_INLIERS``) fail closed.
    """
    band_a = mask_and_crop(_frame_image(frame_a), mask_cfg)
    band_b = mask_and_crop(_frame_image(frame_b), mask_cfg)
    gray_a = cv2.cvtColor(band_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(band_b, cv2.COLOR_BGR2GRAY)
    sift = cv2.SIFT_create()
    keypoints_a, descriptors_a = sift.detectAndCompute(
        gray_a,
        _static_feature_mask(band_a, mask_cfg.fill),
    )
    keypoints_b, descriptors_b = sift.detectAndCompute(
        gray_b,
        _static_feature_mask(band_b, mask_cfg.fill),
    )
    if descriptors_a is None or descriptors_b is None:
        return None
    matches = _ratio_matches(descriptors_a, descriptors_b)
    if not matches:
        return None
    translations = np.asarray(
        [
            np.asarray(keypoints_a[match.queryIdx].pt)
            - np.asarray(keypoints_b[match.trainIdx].pt)
            for match in matches
        ],
        dtype=float,
    )
    seed = np.asarray(seed_delta, dtype=float)
    translations = translations[
        np.linalg.norm(translations - seed, axis=1) <= STATIC_SEED_RADIUS_PX
    ]
    if len(translations) < MIN_COMPETING_SECONDARY_INLIERS * 2:
        return None
    primary = np.median(translations, axis=0)
    primary_inliers = translations[
        np.linalg.norm(translations - primary, axis=1) <= STATIC_INLIER_RADIUS_PX
    ]
    if len(primary_inliers) < MIN_STATIC_INLIERS:
        return None
    primary = np.median(primary_inliers, axis=0)
    remainder = translations[
        np.linalg.norm(translations - primary, axis=1) > separation_px
    ]
    if len(remainder) < MIN_COMPETING_SECONDARY_INLIERS:
        return None
    secondary = np.median(remainder, axis=0)
    secondary_inliers = remainder[
        np.linalg.norm(remainder - secondary, axis=1) <= STATIC_INLIER_RADIUS_PX
    ]
    if len(secondary_inliers) < MIN_COMPETING_SECONDARY_INLIERS:
        return None
    distance = float(np.linalg.norm(secondary - primary))
    if distance <= separation_px:
        return None
    return distance, int(len(secondary_inliers))


def _named_frames(frames: Mapping[str, Any] | Sequence[Any]) -> dict[str, Any]:
    if isinstance(frames, Mapping):
        named = dict(frames)
    else:
        named = {
            _frame_name(frame, f"frame_{index}"): frame
            for index, frame in enumerate(frames)
        }
    if not named:
        raise ValueError("frames must not be empty")
    if any(not isinstance(name, str) or not name for name in named):
        raise ValueError("frame names must be non-empty strings")
    return named


def _bands_overlap_enough(
    offset_a: tuple[float, float],
    shape_a: tuple[int, int],
    offset_b: tuple[float, float],
    shape_b: tuple[int, int],
) -> bool:
    """Return whether bands *centered* at the offsets overlap enough for matching."""
    ax, ay = offset_a
    bx, by = offset_b
    height_a, width_a = shape_a
    height_b, width_b = shape_b
    left_a, top_a = ax - width_a / 2.0, ay - height_a / 2.0
    left_b, top_b = bx - width_b / 2.0, by - height_b / 2.0
    overlap_width = min(left_a + width_a, left_b + width_b) - max(left_a, left_b)
    overlap_height = min(top_a + height_a, top_b + height_b) - max(top_a, top_b)
    if (
        overlap_width < MIN_OVERLAP_DIMENSION_PX
        or overlap_height < MIN_OVERLAP_DIMENSION_PX
    ):
        return False
    overlap_area = overlap_width * overlap_height
    smaller_area = min(width_a * height_a, width_b * height_b)
    return overlap_area / smaller_area >= MIN_OVERLAP_AREA_FRACTION


def _are_grid_neighbors(frame_a: str, frame_b: str) -> bool:
    """Return whether frame names are 4-connected screen-grid neighbors."""
    from ks.cartograph.mosaic import parse_grid_cell

    cell_a = parse_grid_cell(frame_a)
    cell_b = parse_grid_cell(frame_b)
    if cell_a is None or cell_b is None:
        return False
    return abs(cell_a[0] - cell_b[0]) + abs(cell_a[1] - cell_b[1]) == 1


def _unique_landmarks_by_name(
    landmarks: Sequence[NameLandmark],
) -> dict[str, NameLandmark]:
    grouped: dict[str, list[NameLandmark]] = {}
    for landmark in landmarks:
        if is_registration_landmark_name(landmark.name):
            grouped.setdefault(landmark.name, []).append(landmark)
    return {
        name: occurrences[0]
        for name, occurrences in grouped.items()
        if len(occurrences) == 1
    }


def build_registration_constraints(
    frames: Mapping[str, Any] | Sequence[Any],
    seed_offsets: Mapping[str, tuple[float, float]],
    landmarks_by_frame: Mapping[str, Sequence[NameLandmark]],
    *,
    mask_cfg: MaskConfig | None = None,
) -> tuple[PairTranslation, ...]:
    """Build static, unique-name, and weak prior edges for overlapping bands."""
    named_frames = _named_frames(frames)
    if set(named_frames) != set(seed_offsets):
        missing = sorted(set(named_frames) - set(seed_offsets))
        extra = sorted(set(seed_offsets) - set(named_frames))
        raise ValueError(f"seed_offsets must match frames; missing={missing}, extra={extra}")
    config = mask_cfg or bluestacks_mask_config()
    band_shapes = {
        name: mask_and_crop(_frame_image(frame), config).shape[:2]
        for name, frame in named_frames.items()
    }
    unique_landmarks = {
        name: _unique_landmarks_by_name(landmarks_by_frame.get(name, ()))
        for name in named_frames
    }
    constraints: list[PairTranslation] = []
    for frame_a, frame_b in combinations(named_frames, 2):
        offset_a = seed_offsets[frame_a]
        offset_b = seed_offsets[frame_b]
        overlaps = _bands_overlap_enough(
            offset_a,
            band_shapes[frame_a],
            offset_b,
            band_shapes[frame_b],
        )
        grid_neighbors = _are_grid_neighbors(frame_a, frame_b)
        # Exact seed priors must keep the named lattice connected even when
        # swipe gaps leave too little texture overlap for image matching.
        if not overlaps and not grid_neighbors:
            continue
        seed_delta = (
            float(offset_b[0] - offset_a[0]),
            float(offset_b[1] - offset_a[1]),
        )
        constraints.append(
            PairTranslation(
                frame_a=frame_a,
                frame_b=frame_b,
                delta_x=seed_delta[0],
                delta_y=seed_delta[1],
                weight=PRIOR_WEIGHT,
                source="prior",
                inliers=0,
            )
        )
        if not overlaps:
            continue
        static = match_static_translation(
            named_frames[frame_a],
            named_frames[frame_b],
            seed_delta,
            config,
        )
        if static is not None:
            constraints.append(
                PairTranslation(
                    frame_a=frame_a,
                    frame_b=frame_b,
                    delta_x=static.delta_x,
                    delta_y=static.delta_y,
                    weight=static.weight,
                    source="static",
                    inliers=static.inliers,
                )
            )
        shared_names = (
            unique_landmarks[frame_a].keys() & unique_landmarks[frame_b].keys()
        )
        for name in sorted(shared_names):
            landmark_a = unique_landmarks[frame_a][name]
            landmark_b = unique_landmarks[frame_b][name]
            name_delta = (
                float(landmark_a.x - landmark_b.x),
                float(landmark_a.y - landmark_b.y),
            )
            # Fail-closed unique-name edges only when they corroborate the seed;
            # OCR label jitter otherwise becomes a mandatory 2 px failure.
            seed_disagreement = math.hypot(
                name_delta[0] - seed_delta[0],
                name_delta[1] - seed_delta[1],
            )
            if seed_disagreement > EXACT_RESIDUAL_LIMIT_PX:
                continue
            constraints.append(
                PairTranslation(
                    frame_a=frame_a,
                    frame_b=frame_b,
                    delta_x=name_delta[0],
                    delta_y=name_delta[1],
                    weight=UNIQUE_NAME_WEIGHT
                    * min(landmark_a.conf, landmark_b.conf),
                    source="unique_name",
                    inliers=1,
                )
            )
    return tuple(constraints)


@dataclass(frozen=True)
class RegistrationMetrics:
    """Residual diagnostics for accepted translation constraints."""

    median_px: float
    p95_px: float
    max_px: float
    connected_frames: tuple[str, ...]


@dataclass(frozen=True)
class EdgeRegistrationDiagnostic:
    """Final residual and fit treatment for one input constraint."""

    constraint: PairTranslation
    residual_px: float
    accepted: bool
    effective_weight: float
    source: str
    inliers: int


@dataclass(frozen=True)
class RegistrationGraphDiagnostics:
    """Connectivity and edge counts for the solved graph."""

    connected: bool
    expected_frame_count: int
    connected_frame_count: int
    constraint_count: int
    accepted_count: int
    rejected_count: int
    design_rank: int = 0
    design_columns: int = 0
    condition_number: float = 1.0


@dataclass(frozen=True)
class GlobalRegistration:
    """Immutable frame offsets and their registration diagnostics."""

    frame_offsets: Mapping[str, tuple[float, float]]
    metrics: RegistrationMetrics
    accepted: tuple[PairTranslation, ...]
    rejected: tuple[PairTranslation, ...]
    diagnostics: tuple[EdgeRegistrationDiagnostic, ...] = ()
    graph: RegistrationGraphDiagnostics | None = None
    world_to_pixel_matrix: WorldToPixelMatrix | None = None

    def __post_init__(self) -> None:
        immutable_offsets = MappingProxyType(dict(self.frame_offsets))
        object.__setattr__(self, "frame_offsets", immutable_offsets)


class RegistrationThresholdError(ValueError):
    """Registration failed mandatory source or aggregate residual limits."""

    def __init__(
        self,
        message: str,
        *,
        metrics: RegistrationMetrics,
        diagnostics: tuple[EdgeRegistrationDiagnostic, ...],
    ) -> None:
        super().__init__(message)
        self.metrics = metrics
        self.diagnostics = diagnostics


class CompetingFeatureTrackError(ValueError):
    """Cross-frame feature tracks show a competing translation peak."""

    def __init__(
        self,
        message: str,
        *,
        competing_pairs: tuple[tuple[str, str, float, int], ...],
    ) -> None:
        super().__init__(message)
        if not competing_pairs:
            raise ValueError("competing_pairs must be non-empty for this error")
        self.competing_pairs = competing_pairs


class RegistrationGraphError(ValueError):
    """Registration graph is disconnected before or after classification."""

    def __init__(
        self,
        message: str,
        *,
        graph: RegistrationGraphDiagnostics,
        diagnostics: tuple[EdgeRegistrationDiagnostic, ...],
    ) -> None:
        super().__init__(message)
        self.graph = graph
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class _SourceAcceptance:
    residual_limit_px: float
    mandatory: bool


def _source_acceptance(constraint: PairTranslation) -> _SourceAcceptance:
    """Return the single source of truth for edge acceptance semantics."""
    if constraint.source in {"exact", "unique_name"}:
        return _SourceAcceptance(EXACT_RESIDUAL_LIMIT_PX, True)
    if constraint.source == "static":
        return _SourceAcceptance(
            STATIC_RESIDUAL_LIMIT_PX,
            constraint.inliers >= 20,
        )
    return _SourceAcceptance(MAX_RESIDUAL_LIMIT_PX, False)


def _validate_inputs(
    constraints: tuple[PairTranslation, ...],
    reference_frame: str,
    expected_frames: tuple[str, ...],
) -> None:
    if not expected_frames:
        raise ValueError("expected_frames must contain at least one frame")
    if len(set(expected_frames)) != len(expected_frames):
        raise ValueError("expected_frames must not contain duplicates")
    if any(not isinstance(frame, str) or not frame for frame in expected_frames):
        raise ValueError("expected frame names must be non-empty strings")
    if reference_frame not in expected_frames:
        raise ValueError(
            f"reference frame {reference_frame!r} is missing from expected_frames"
        )
    if not constraints and len(expected_frames) > 1:
        raise ValueError("translation constraints are required for multiple frames")

    expected_set = set(expected_frames)
    for index, constraint in enumerate(constraints):
        if not isinstance(constraint.source, str) or not constraint.source.strip():
            raise ValueError(f"constraint {index} source must be non-empty")
        if (
            isinstance(constraint.inliers, bool)
            or not isinstance(constraint.inliers, Integral)
            or constraint.inliers < 0
        ):
            raise ValueError(
                f"constraint {index} inliers must be a nonnegative integer; "
                f"got {constraint.inliers!r}"
            )
        if (
            constraint.frame_a not in expected_set
            or constraint.frame_b not in expected_set
        ):
            raise ValueError(
                f"constraint {index} references a frame outside expected_frames: "
                f"{constraint.frame_a!r} -> {constraint.frame_b!r}"
            )
        if constraint.frame_a == constraint.frame_b:
            raise ValueError(f"constraint {index} must connect two different frames")
        values = (constraint.delta_x, constraint.delta_y, constraint.weight)
        if not np.isfinite(values).all():
            if not np.isfinite(constraint.weight):
                raise ValueError(
                    f"constraint {index} weight must be finite and positive; "
                    f"got {constraint.weight!r}"
                )
            raise ValueError(
                f"constraint {index} translation must contain finite values"
            )
        if constraint.weight <= 0:
            raise ValueError(
                f"constraint {index} weight must be finite and positive; "
                f"got {constraint.weight!r}"
            )


def _connected_frames(
    constraints: Sequence[PairTranslation],
    reference_frame: str,
) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for constraint in constraints:
        adjacency.setdefault(constraint.frame_a, set()).add(constraint.frame_b)
        adjacency.setdefault(constraint.frame_b, set()).add(constraint.frame_a)

    connected = {reference_frame}
    pending = [reference_frame]
    while pending:
        frame = pending.pop()
        for neighbor in adjacency.get(frame, ()):
            if neighbor not in connected:
                connected.add(neighbor)
                pending.append(neighbor)
    return connected


def _design_matrix(
    constraints: Sequence[PairTranslation],
    reference_frame: str,
    expected_frames: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    variable_frames = [frame for frame in expected_frames if frame != reference_frame]
    frame_columns = {frame: index for index, frame in enumerate(variable_frames)}
    design = np.zeros((len(constraints), len(variable_frames)), dtype=float)
    deltas = np.empty((len(constraints), 2), dtype=float)
    for row, constraint in enumerate(constraints):
        if constraint.frame_a != reference_frame:
            design[row, frame_columns[constraint.frame_a]] = -1.0
        if constraint.frame_b != reference_frame:
            design[row, frame_columns[constraint.frame_b]] = 1.0
        deltas[row] = (constraint.delta_x, constraint.delta_y)
    return design, deltas, frame_columns


def _weighted_fit(
    design: np.ndarray,
    deltas: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    if design.shape[1] == 0:
        return np.empty((0, 2), dtype=float)
    square_root_weights = np.sqrt(weights)
    weighted_design = design * square_root_weights[:, None]
    weighted_deltas = deltas * square_root_weights[:, None]
    offsets, _, rank, _ = np.linalg.lstsq(
        weighted_design,
        weighted_deltas,
        rcond=None,
    )
    if rank < design.shape[1]:
        raise ValueError("translation constraints do not determine every frame offset")
    return offsets


def _residuals(
    design: np.ndarray,
    deltas: np.ndarray,
    offsets: np.ndarray,
) -> np.ndarray:
    return np.linalg.norm(design @ offsets - deltas, axis=1)


def _canonical_pair_vector(
    constraint: PairTranslation,
) -> tuple[tuple[str, str], tuple[float, float]]:
    pair = tuple(sorted((constraint.frame_a, constraint.frame_b)))
    direction = 1.0 if constraint.frame_a == pair[0] else -1.0
    return pair, (
        direction * constraint.delta_x,
        direction * constraint.delta_y,
    )


def _pair_consensus_mask(
    constraints: tuple[PairTranslation, ...],
) -> tuple[np.ndarray, np.ndarray]:
    """Classify duplicate measurements only against their unordered pair."""
    accepted = np.ones(len(constraints), dtype=bool)
    pair_residuals = np.zeros(len(constraints), dtype=float)
    groups: dict[tuple[str, str], list[tuple[int, tuple[float, float]]]] = {}
    for index, constraint in enumerate(constraints):
        pair, vector = _canonical_pair_vector(constraint)
        groups.setdefault(pair, []).append((index, vector))

    for pair, measurements in groups.items():
        if len(measurements) == 1:
            continue
        vectors = np.asarray([vector for _, vector in measurements], dtype=float)
        group_indexes = {index for index, _ in measurements}
        external_consensus = _pair_prediction_from_other_edges(
            constraints,
            group_indexes,
            pair,
        )
        consensus = (
            external_consensus
            if external_consensus is not None
            else np.median(vectors, axis=0)
        )
        deviations = np.linalg.norm(vectors - consensus, axis=1)
        median_deviation = float(np.median(deviations))
        mad = float(np.median(np.abs(deviations - median_deviation)))
        cutoff = max(
            MIN_CONSENSUS_CUTOFF_PX,
            median_deviation + 3.0 * MAD_SCALE_FACTOR * mad,
        ) + 1e-9
        for (index, _), deviation in zip(
            measurements,
            deviations,
            strict=True,
        ):
            pair_residuals[index] = float(deviation)
            policy = _source_acceptance(constraints[index])
            acceptance_limit = (
                policy.residual_limit_px
                if external_consensus is not None
                else cutoff
            )
            accepted[index] = policy.mandatory or deviation <= acceptance_limit
    return accepted, pair_residuals


def _pair_prediction_from_other_edges(
    constraints: tuple[PairTranslation, ...],
    excluded_indexes: set[int],
    pair: tuple[str, str],
) -> np.ndarray | None:
    other_constraints = tuple(
        constraint
        for index, constraint in enumerate(constraints)
        if index not in excluded_indexes
    )
    component = _connected_frames(other_constraints, pair[0])
    if pair[1] not in component:
        return None
    component_frames = (pair[0], *sorted(component - {pair[0]}))
    component_constraints = tuple(
        constraint
        for constraint in other_constraints
        if constraint.frame_a in component and constraint.frame_b in component
    )
    design, deltas, columns = _design_matrix(
        component_constraints,
        pair[0],
        component_frames,
    )
    offsets = _weighted_fit(
        design,
        deltas,
        np.ones(len(component_constraints), dtype=float),
    )
    return offsets[columns[pair[1]]]


def _global_acceptance_mask(
    constraints: tuple[PairTranslation, ...],
    pair_mask: np.ndarray,
    residuals: np.ndarray,
) -> np.ndarray:
    accepted: list[bool] = []
    for constraint, pair_accepted, residual in zip(
        constraints,
        pair_mask,
        residuals,
        strict=True,
    ):
        policy = _source_acceptance(constraint)
        within_limit = residual <= policy.residual_limit_px + 1e-9
        accepted.append(
            bool(pair_accepted) and (policy.mandatory or within_limit)
        )
    return np.asarray(accepted, dtype=bool)


def _partition_by_mask(
    constraints: tuple[PairTranslation, ...],
    accepted_mask: np.ndarray,
) -> tuple[tuple[PairTranslation, ...], tuple[PairTranslation, ...]]:
    accepted = tuple(
        constraint
        for constraint, keep in zip(constraints, accepted_mask, strict=True)
        if keep
    )
    rejected = tuple(
        constraint
        for constraint, keep in zip(constraints, accepted_mask, strict=True)
        if not keep
    )
    return accepted, rejected


def _normalized_accepted_weights(
    constraints: Sequence[PairTranslation],
) -> np.ndarray:
    raw_weights = np.asarray([item.weight for item in constraints], dtype=float)
    if not len(raw_weights):
        return raw_weights
    normalized = raw_weights / float(np.max(raw_weights))
    return np.maximum(normalized, 1.0 / MAX_ACCEPTED_WEIGHT_RATIO)


def _huber_delta(constraint: PairTranslation) -> float:
    """Use half the hard source limit so moderate valid edges attenuate early."""
    return (
        HUBER_DELTA_FRACTION
        * _source_acceptance(constraint).residual_limit_px
    )


def _huber_weighted_fit(
    design: np.ndarray,
    deltas: np.ndarray,
    constraints: tuple[PairTranslation, ...],
    base_weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply Huber multipliers on top of bounded authority-preserving weights."""
    effective_weights = base_weights.copy()
    offsets = _weighted_fit(design, deltas, effective_weights)
    robust_deltas = np.asarray(
        [_huber_delta(constraint) for constraint in constraints],
        dtype=float,
    )

    for _ in range(HUBER_MAX_ITERATIONS):
        residuals = _residuals(design, deltas, offsets)
        attenuation = np.ones(len(constraints), dtype=float)
        above_delta = residuals > robust_deltas
        attenuation[above_delta] = (
            robust_deltas[above_delta] / residuals[above_delta]
        )
        updated_weights = base_weights * attenuation
        updated_offsets = _weighted_fit(
            design,
            deltas,
            updated_weights,
        )
        effective_weights = updated_weights
        if np.allclose(
            updated_offsets,
            offsets,
            atol=HUBER_CONVERGENCE_PX,
            rtol=0.0,
        ):
            offsets = updated_offsets
            break
        offsets = updated_offsets

    return offsets, effective_weights


def _frame_offsets(
    offsets: np.ndarray,
    frame_columns: Mapping[str, int],
    reference_frame: str,
    expected_frames: tuple[str, ...],
) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    for frame in expected_frames:
        if frame == reference_frame:
            result[frame] = (0.0, 0.0)
        else:
            offset = offsets[frame_columns[frame]]
            result[frame] = (float(offset[0]), float(offset[1]))
    return result


def _registration_metrics(
    residuals: np.ndarray,
    expected_frames: tuple[str, ...],
) -> RegistrationMetrics:
    return RegistrationMetrics(
        median_px=float(np.median(residuals)) if len(residuals) else 0.0,
        p95_px=float(np.percentile(residuals, 95)) if len(residuals) else 0.0,
        max_px=float(np.max(residuals)) if len(residuals) else 0.0,
        connected_frames=expected_frames,
    )


def _measurement_residuals(
    accepted: Sequence[PairTranslation],
    accepted_residuals: np.ndarray,
) -> np.ndarray:
    """Prefer static/exact/unique-name residuals for aggregate thresholds."""
    if len(accepted_residuals) != len(accepted):
        raise ValueError(
            "accepted residuals must align with accepted constraints; "
            f"got {len(accepted_residuals)} residuals for {len(accepted)} edges"
        )
    measurement = np.asarray(
        [
            residual
            for constraint, residual in zip(accepted, accepted_residuals, strict=True)
            if constraint.source != "prior"
        ],
        dtype=float,
    )
    if len(measurement):
        return measurement
    return np.asarray(accepted_residuals, dtype=float)


def _edge_diagnostics(
    constraints: tuple[PairTranslation, ...],
    residuals: np.ndarray,
    accepted_mask: np.ndarray,
    accepted_weights: np.ndarray,
) -> tuple[EdgeRegistrationDiagnostic, ...]:
    effective_weights = np.zeros(len(constraints), dtype=float)
    effective_weights[accepted_mask] = accepted_weights
    return tuple(
        EdgeRegistrationDiagnostic(
            constraint=constraint,
            residual_px=float(residual),
            accepted=bool(accepted),
            effective_weight=float(effective_weight),
            source=constraint.source,
            inliers=int(constraint.inliers),
        )
        for constraint, residual, accepted, effective_weight in zip(
            constraints,
            residuals,
            accepted_mask,
            effective_weights,
            strict=True,
        )
    )


def _graph_diagnostics(
    constraints: tuple[PairTranslation, ...],
    accepted: tuple[PairTranslation, ...],
    expected_frames: tuple[str, ...],
    reference_frame: str,
) -> RegistrationGraphDiagnostics:
    connected_count = len(_connected_frames(accepted, reference_frame))
    design, _, _ = _design_matrix(
        accepted,
        reference_frame,
        expected_frames,
    )
    design_columns = design.shape[1]
    design_rank = (
        int(np.linalg.matrix_rank(design))
        if design.size
        else 0
    )
    if design_columns == 0:
        condition_number = 1.0
    elif design_rank < design_columns:
        condition_number = float("inf")
    else:
        condition_number = float(np.linalg.cond(design))
    return RegistrationGraphDiagnostics(
        connected=connected_count == len(expected_frames),
        expected_frame_count=len(expected_frames),
        connected_frame_count=connected_count,
        constraint_count=len(constraints),
        accepted_count=len(accepted),
        rejected_count=len(constraints) - len(accepted),
        design_rank=design_rank,
        design_columns=design_columns,
        condition_number=condition_number,
    )


def _raise_if_disconnected(
    constraints: tuple[PairTranslation, ...],
    accepted_mask: np.ndarray,
    residuals: np.ndarray,
    expected_frames: tuple[str, ...],
    reference_frame: str,
    *,
    stage: str,
) -> None:
    accepted, _ = _partition_by_mask(constraints, accepted_mask)
    graph = _graph_diagnostics(
        constraints,
        accepted,
        expected_frames,
        reference_frame,
    )
    if graph.connected:
        return
    accepted_weights = _normalized_accepted_weights(accepted)
    diagnostics = _edge_diagnostics(
        constraints,
        residuals,
        accepted_mask,
        accepted_weights,
    )
    connected = _connected_frames(accepted, reference_frame)
    unreachable = ", ".join(
        frame for frame in expected_frames if frame not in connected
    )
    raise RegistrationGraphError(
        f"{stage} constraint graph is disconnected; unreachable: {unreachable}",
        graph=graph,
        diagnostics=diagnostics,
    )


def _mandatory_residual_failures(
    diagnostics: tuple[EdgeRegistrationDiagnostic, ...],
) -> list[str]:
    failures: list[str] = []
    for diagnostic in diagnostics:
        constraint = diagnostic.constraint
        policy = _source_acceptance(constraint)
        if not policy.mandatory:
            continue
        if diagnostic.residual_px > policy.residual_limit_px:
            failures.append(
                f"{constraint.source} {constraint.frame_a!r}->{constraint.frame_b!r} "
                f"residual={diagnostic.residual_px:.3f}px exceeds "
                f"{policy.residual_limit_px:.1f}px"
            )
    return failures


def _require_acceptable_residuals(
    metrics: RegistrationMetrics,
    diagnostics: tuple[EdgeRegistrationDiagnostic, ...],
) -> None:
    aggregate_failure = (
        metrics.median_px > MEDIAN_RESIDUAL_LIMIT_PX
        or metrics.p95_px > P95_RESIDUAL_LIMIT_PX
        or metrics.max_px > MAX_RESIDUAL_LIMIT_PX
    )
    mandatory_failures = _mandatory_residual_failures(diagnostics)
    if aggregate_failure or mandatory_failures:
        details = (
            f"median={metrics.median_px:.3f}px "
            f"(limit {MEDIAN_RESIDUAL_LIMIT_PX:.1f}px), "
            f"p95={metrics.p95_px:.3f}px "
            f"(limit {P95_RESIDUAL_LIMIT_PX:.1f}px), "
            f"max={metrics.max_px:.3f}px "
            f"(limit {MAX_RESIDUAL_LIMIT_PX:.1f}px)"
        )
        if mandatory_failures:
            details = f"{details}; " + "; ".join(mandatory_failures)
        raise RegistrationThresholdError(
            f"registration residual thresholds exceeded: {details}",
            metrics=metrics,
            diagnostics=diagnostics,
        )


def solve_frame_translations(
    constraints: Sequence[PairTranslation],
    reference_frame: str,
    expected_frames: Sequence[str],
) -> GlobalRegistration:
    """Solve pair equations ``offset_b - offset_a = delta`` robustly."""
    constraint_tuple = tuple(constraints)
    expected_frame_tuple = tuple(expected_frames)
    _validate_inputs(constraint_tuple, reference_frame, expected_frame_tuple)
    input_mask = np.ones(len(constraint_tuple), dtype=bool)
    _raise_if_disconnected(
        constraint_tuple,
        input_mask,
        np.full(len(constraint_tuple), np.nan),
        expected_frame_tuple,
        reference_frame,
        stage="input",
    )

    design, deltas, frame_columns = _design_matrix(
        constraint_tuple,
        reference_frame,
        expected_frame_tuple,
    )
    pair_mask, pair_residuals = _pair_consensus_mask(constraint_tuple)
    _raise_if_disconnected(
        constraint_tuple,
        pair_mask,
        pair_residuals,
        expected_frame_tuple,
        reference_frame,
        stage="post-classification",
    )

    pair_accepted, _ = _partition_by_mask(constraint_tuple, pair_mask)
    pair_design, pair_deltas, _ = _design_matrix(
        pair_accepted,
        reference_frame,
        expected_frame_tuple,
    )
    consensus_offsets = _weighted_fit(
        pair_design,
        pair_deltas,
        np.ones(len(pair_accepted), dtype=float),
    )
    consensus_residuals = _residuals(design, deltas, consensus_offsets)
    accepted_mask = _global_acceptance_mask(
        constraint_tuple,
        pair_mask,
        consensus_residuals,
    )
    _raise_if_disconnected(
        constraint_tuple,
        accepted_mask,
        consensus_residuals,
        expected_frame_tuple,
        reference_frame,
        stage="post-classification",
    )

    accepted, rejected = _partition_by_mask(
        constraint_tuple,
        accepted_mask,
    )
    accepted_design, accepted_deltas, frame_columns = _design_matrix(
        accepted,
        reference_frame,
        expected_frame_tuple,
    )
    base_weights = _normalized_accepted_weights(accepted)
    offsets, accepted_weights = _huber_weighted_fit(
        accepted_design,
        accepted_deltas,
        accepted,
        base_weights,
    )
    all_residuals = _residuals(design, deltas, offsets)
    # Soft priors can drift past their limit once high-weight static edges
    # dominate the Huber fit; re-apply the non-mandatory residual gate.
    final_accepted_mask = _global_acceptance_mask(
        constraint_tuple,
        accepted_mask,
        all_residuals,
    )
    _raise_if_disconnected(
        constraint_tuple,
        final_accepted_mask,
        all_residuals,
        expected_frame_tuple,
        reference_frame,
        stage="post-fit",
    )
    accepted, rejected = _partition_by_mask(
        constraint_tuple,
        final_accepted_mask,
    )
    final_weight_full = np.zeros(len(constraint_tuple), dtype=float)
    final_weight_full[accepted_mask] = accepted_weights
    final_accepted_weights = final_weight_full[final_accepted_mask]
    accepted_residuals = all_residuals[final_accepted_mask]
    metrics = _registration_metrics(
        _measurement_residuals(accepted, accepted_residuals),
        expected_frame_tuple,
    )
    diagnostics = _edge_diagnostics(
        constraint_tuple,
        all_residuals,
        final_accepted_mask,
        final_accepted_weights,
    )
    graph = _graph_diagnostics(
        constraint_tuple,
        accepted,
        expected_frame_tuple,
        reference_frame,
    )
    _require_acceptable_residuals(metrics, diagnostics)
    return GlobalRegistration(
        frame_offsets=_frame_offsets(
            offsets,
            frame_columns,
            reference_frame,
            expected_frame_tuple,
        ),
        metrics=metrics,
        accepted=accepted,
        rejected=rejected,
        diagnostics=diagnostics,
        graph=graph,
    )
