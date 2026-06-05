"""Compute: Mathematical functions for data transformation, aggregation, score calculations."""

from analyze_config import CENTERED_AVG_HALF_WINDOW
from analyze_io import load_all_trials

# ---------------------------------------------------------------------------
# Colour palette — matches UI.py SLICE_COLORS
# ---------------------------------------------------------------------------
TEST_COLORS = [
    "#404867",  # (matches C_BANNER in UI.py)
    "#6b7aad",
    "#9aa3cc",
    "#2c3e6b",
    "#c0392b",
    "#2ecc71",
    "#e67e22",
    "#9b59b6",
]

NEG_ALPHA = 0.40  # alpha for negative-contribution segments
NEG_HATCH = (
    "////"  # hatch for negative segments (note: Plotly doesn't support hatching)
)

C_BANNER = "#404867"
C_BG = "#ffffff"
C_SECTION = "#fafbfc"
C_BORDER = "#d0d3d8"
C_FINAL = "#c0392b"  # final-score tick colour
C_AVG = "#2ecc71"  # rolling average line
C_BEST = "#e74c3c"  # best-so-far line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_all_test_names(records: list[dict]) -> list[str]:
    """Return a stable ordered list of every unique test name seen across all records."""
    seen: list[str] = []
    for r in records:
        for name in (r.get("test_scores") or {}).keys():
            if name not in seen:
                seen.append(name)
    return seen


def _test_color(test_name: str, name_order: list[str]) -> str:
    """Return the hex color assigned to a test, consistent across the whole plot."""
    try:
        idx = name_order.index(test_name)
    except ValueError:
        idx = abs(hash(test_name)) % len(TEST_COLORS)
    return TEST_COLORS[idx % len(TEST_COLORS)]


def _compute_contributions(record: dict) -> dict[str, float]:
    """Compute per-test weighted contribution for one trial record.

    contribution_i = normalize(aggregate_score_i) * weight_pct_i

    Falls back gracefully when test_scores is absent (legacy records).
    """
    test_scores: dict = record.get("test_scores") or {}

    if not test_scores:
        return {"score": float(record.get("final_score", record.get("score", 0.0)))}

    contributions: dict[str, float] = {}
    for test_name, test_info in test_scores.items():
        if not isinstance(test_info, dict):
            continue
        agg = float(test_info.get("aggregate_score", 0.0) or 0.0)
        raw_max = test_info.get("max_score")
        # Treat missing/None as legacy (score already normalised); 0.0 means unknown.
        max_score = float(raw_max) if raw_max is not None else 1.0
        wpct = float(test_info.get("weight_pct", 0.0) or 0.0)
        norm = min(agg / max_score, 1.0) if max_score > 0 else 0.0
        contributions[test_name] = norm * wpct

    return (
        contributions
        if contributions
        else {"score": float(record.get("final_score", record.get("score", 0.0)))}
    )


# ---------------------------------------------------------------------------
# Plot-data builder
# ---------------------------------------------------------------------------


def compute_plot_data(records: list[dict], all_test_names: list[str]) -> dict:
    """Pre-compute all series needed for a full plot redraw.

    Args:
        records: Trial records from analyze_io.load_all_trials().
        all_test_names: Ordered unique test names (from _collect_all_test_names).

    Returns:
        dict with keys: xs, final_scores, failed_mask, is_complete, contributions,
        avg_x, avg_y, best_x, best_y, gen_tick_positions, gen_tick_labels.
    """
    xs = [r["chron"] for r in records]
    contributions = [_compute_contributions(r) for r in records]
    final_scores = [sum(c.values()) for c in contributions]
    failed_mask = [bool(r.get("failed", False)) for r in records]
    is_complete = [bool(r.get("is_complete", True)) for r in records]
    contributions = [_compute_contributions(r) for r in records]

    # Centred rolling average
    avg_x, avg_y = [], []
    for i, r in enumerate(records):
        lo = max(0, i - CENTERED_AVG_HALF_WINDOW)
        hi = min(len(records) - 1, i + CENTERED_AVG_HALF_WINDOW)
        window = records[lo : hi + 1]
        scores = [sum(_compute_contributions(w).values()) for w in window]
        avg_x.append(r["chron"])
        avg_y.append(sum(scores) / len(scores))

    # Best-so-far
    best_x, best_y = [], []
    running_best = None
    for i, r in enumerate(records):
        if not failed_mask[i]:
            fs = final_scores[i]
            if running_best is None or fs > running_best:
                running_best = fs
        if running_best is not None:
            best_x.append(r["chron"])
            best_y.append(running_best)

    # Per-test rolling averages
    per_test_avg: dict[str, tuple[list, list]] = {}
    for test_name in all_test_names:
        avg_x_t, avg_y_t = [], []
        for i, r in enumerate(records):
            lo = max(0, i - CENTERED_AVG_HALF_WINDOW)
            hi = min(len(records) - 1, i + CENTERED_AVG_HALF_WINDOW)
            window_scores = [
                _compute_contributions(records[k]).get(test_name, 0.0)
                for k in range(lo, hi + 1)
            ]
            avg_x_t.append(r["chron"])
            avg_y_t.append(sum(window_scores) / len(window_scores))
        per_test_avg[test_name] = (avg_x_t, avg_y_t)

    # Generation tick marks (one per unique generation boundary)
    gen_tick_positions, gen_tick_labels = [], []
    prev_gen = None
    for r in records:
        if r["gen_index"] != prev_gen:
            gen_tick_positions.append(r["chron"])
            gen_tick_labels.append(str(r["gen_index"]))
        prev_gen = r["gen_index"]

    return {
        "xs": xs,
        "final_scores": final_scores,
        "failed_mask": failed_mask,
        "is_complete": is_complete,
        "contributions": contributions,
        "avg_x": avg_x,
        "avg_y": avg_y,
        "best_x": best_x,
        "best_y": best_y,
        "per_test_avg": per_test_avg,
        "gen_tick_positions": gen_tick_positions,
        "gen_tick_labels": gen_tick_labels,
    }


def _calculate_smart_ticks(
    gen_tick_positions: list, gen_tick_labels: list, visible_range: tuple = None
) -> tuple[list, list]:
    """Calculate smart generation ticks with stride to avoid crowding.

    Args:
        gen_tick_positions: X positions of generation boundaries
        gen_tick_labels: Generation numbers as strings
        visible_range: (x_min, x_max) of currently visible area. If None, uses full range.

    Returns:
        (filtered_positions, filtered_labels) for use in tickvals/ticktext
    """
    if not gen_tick_positions:
        return [], []

    if visible_range:
        x_min, x_max = visible_range
    else:
        x_min = gen_tick_positions[0]
        x_max = gen_tick_positions[-1]

    # Find ticks within visible range
    visible_indices = [
        i for i, pos in enumerate(gen_tick_positions) if x_min <= pos <= x_max
    ]

    if not visible_indices:
        return [], []

    num_visible = len(visible_indices)
    max_comfortable_labels = 15

    if num_visible <= max_comfortable_labels:
        stride = 1
    else:
        min_stride = num_visible / max_comfortable_labels
        standard_intervals = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
        stride = next(
            (s for s in standard_intervals if s >= min_stride), standard_intervals[-1]
        )

    # Filter by stride, starting from first visible index
    first_idx = visible_indices[0]
    filtered_indices = [i for i in visible_indices if (i - first_idx) % stride == 0]

    filtered_positions = [gen_tick_positions[i] for i in filtered_indices]
    filtered_labels = [gen_tick_labels[i] for i in filtered_indices]

    return filtered_positions, filtered_labels
