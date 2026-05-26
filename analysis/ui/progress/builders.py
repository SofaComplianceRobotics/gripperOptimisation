"""Progress builders — UI rendering functions."""

from dash import html

from data.cache import _load_trial_state
from plotting.colors import C_BANNER, C_BORDER, C_FINAL

from .helpers import (
    _get_test_max_score,
    _state_color,
    _get_live_score,
    _get_trial_actual_state,
    _weight_segment_style,
)


def _build_weight_segment_bar(segments: list[dict]) -> html.Div:
    """Build a segmented bar for a binary-search ladder."""
    if not segments:
        return html.Div()

    segment_nodes = []
    for segment in segments:
        label = str(segment.get("label", ""))
        title = str(segment.get("title", label))
        state = str(segment.get("state", "unknown")).lower()
        node_style = {
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "fontSize": "0.68rem",
            "lineHeight": "1",
            "borderRadius": "4px",
            "transition": "transform 180ms ease, opacity 180ms ease",
            "opacity": (
                1.0 if state.startswith("tested") or state == "pending" else 0.88
            ),
            **_weight_segment_style(segment),
        }
        segment_nodes.append(
            html.Div(
                label if len(segments) <= 12 else "",
                title=title,
                style=node_style,
            )
        )

    return html.Div(
        segment_nodes,
        style={
            "display": "grid",
            "gridTemplateColumns": f"repeat({len(segments)}, minmax(0, 1fr))",
            "gap": "3px",
            "height": "20px",
            "width": "100%",
        },
    )


def _build_progress_card(trial_record: dict) -> html.Div:
    """Build a compact progress card UI element for a single trial.

    Args:
        trial_record: Trial metadata record.

    Returns:
        A Dash `Div` representing the trial's progress and run bars.
    """
    trial_state = _load_trial_state(trial_record) or {}
    runs = trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []
    trial_index = trial_record.get("trial_index", 0)
    final_score = trial_record.get("final_score")

    state = _get_trial_actual_state(trial_record)

    run_rows = []
    if runs:
        for run in runs:
            if not isinstance(run, dict):
                continue
            run_state = str(run.get("state", "not-started")).lower()
            bar_color = _state_color(run_state)

            test_name = run.get("test_name") or run.get("run_label") or "run"
            max_score = _get_test_max_score(test_name)
            segments = run.get("weight_segments")
            weight_points = run.get("weight_points")
            selected_weight = run.get("weight_selected_value")
            segment_summary = str(run.get("weight_segment_summary") or "").strip()

            live_val, is_final = _get_live_score(run)
            if live_val is not None and run_state not in {"not-started"}:
                bar_pct = (
                    max(0.0, min(100.0, live_val / max_score * 100))
                    if max_score > 0
                    else 0.0
                )
                score_label = f"{live_val:.3f}" if is_final else f"~{live_val:.3f}"
            else:
                bar_pct = 0.0
                score_label = "--"

            run_idx = run.get("test_run_index")
            run_total = run.get("test_run_total")
            count_str = (
                f" {run_idx}/{run_total} |"
                if run_idx is not None and run_total is not None and run_total > 1
                else ""
            )
            weight_text = ""
            if isinstance(selected_weight, (int, float)):
                weight_text = f" w={float(selected_weight):.3f}"
            if isinstance(weight_points, (int, float)):
                weight_text += f" pts={int(weight_points)}/10"
            label_text = (
                f"{test_name} |{count_str}{weight_text} {score_label} | {run_state}"
            )

            run_rows.append(
                html.Div(
                    [
                        html.Div(
                            label_text,
                            style={
                                "fontSize": "0.82rem",
                                "color": bar_color,
                                "fontWeight": 600,
                                "whiteSpace": "normal",
                                "overflowWrap": "anywhere",
                            },
                        ),
                        html.Div(
                            (
                                _build_weight_segment_bar(segments)
                                if isinstance(segments, list) and segments
                                else html.Div(
                                    html.Div(
                                        style={
                                            "width": f"{bar_pct:.1f}%",
                                            "height": "100%",
                                            "background": bar_color,
                                            "borderRadius": "999px",
                                            "transition": "width 600ms ease",
                                            "willChange": "width",
                                            "minWidth": "0",
                                        }
                                    ),
                                    style={
                                        "flexGrow": 1,
                                        "height": "20px",
                                        "background": "#e9ecef",
                                        "borderRadius": "999px",
                                        "overflow": "hidden",
                                    },
                                )
                            ),
                            style={
                                "flexGrow": 1,
                                "minWidth": 0,
                            },
                        ),
                        html.Div(
                            (
                                segment_summary
                                if isinstance(segments, list) and segments
                                else ""
                            ),
                            style={
                                "fontSize": "0.72rem",
                                "color": "#6c757d",
                                "whiteSpace": "normal",
                                "overflowWrap": "anywhere",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "flexDirection": "column",
                        "gap": "4px",
                        "marginBottom": "6px",
                    },
                )
            )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Trial", className="text-muted"),
                            html.Div(str(trial_index), className="fw-semibold"),
                        ],
                        className="col-12 col-md-4",
                    ),
                    html.Div(
                        [
                            html.Div("State", className="text-muted"),
                            html.Div(
                                state,
                                style={"color": _state_color(state), "fontWeight": 600},
                            ),
                        ],
                        className="col-12 col-md-4",
                    ),
                    html.Div(
                        [
                            html.Div("Score", className="text-muted"),
                            html.Div(
                                (
                                    f"{final_score:.4f}"
                                    if isinstance(final_score, (int, float))
                                    else "--"
                                ),
                                className="fw-semibold",
                            ),
                        ],
                        className="col-12 col-md-4",
                    ),
                ],
                className="row g-3 mb-3",
            ),
            html.Div(
                run_rows
                or [html.Div("No run details available yet.", className="text-muted")]
            ),
            html.Hr(),
        ],
        id=f"trial-card-{trial_record.get('gen_index', 0):04d}-{trial_record.get('trial_index', 0):04d}",
        className="p-3 border rounded",
        style={"background": "#fafbfc"},
    )


def _build_trial_detail(state: dict, gen_name: str, trial_name: str) -> html.Div:
    """Render detailed trial information including per-test contributions.

    Args:
        state: Parsed trial state dict.
        gen_name: Generation directory name.
        trial_name: Trial directory name.

    Returns:
        A Dash `Div` with detailed scoring breakdown.
    """
    final_score = state.get("final_score", 0.0) or 0.0
    test_scores: dict = state.get("test_scores") or {}

    header = html.Div(
        [
            html.Span(f"{gen_name} / {trial_name}", className="fw-semibold me-3"),
            html.Span(
                f"Final score: {final_score:.2f} / 100",
                style={"color": C_FINAL, "fontWeight": 700},
            ),
        ],
        className="d-flex align-items-center mb-3",
        style={"fontSize": "1.05rem"},
    )

    rows = []
    for test_name, info in sorted(
        test_scores.items(), key=lambda kv: kv[1].get("weight_pct", 0), reverse=True
    ):
        if not isinstance(info, dict):
            continue
        agg = float(info.get("aggregate_score", 0.0) or 0.0)
        max_s = float(info.get("max_score", 1.0) or 1.0)
        weight = float(info.get("weight_pct", 0.0) or 0.0)
        norm = min(agg / max_s, 1.0) if max_s > 0 else 0.0
        contribution = norm * weight
        success_pct = norm * 100
        run_scores: list = info.get("run_scores") or []
        run_total = int(info.get("run_total", 1))

        bar_pct = min(norm * 100, 100)

        run_cells = []
        if run_total > 1 and run_scores:
            for idx, rs in enumerate(run_scores):
                if rs == float("-inf") or rs is None:
                    label, color = "FAIL", "#e03131"
                else:
                    label, color = f"{rs:.3f}", "#2f9e44"
                run_cells.append(
                    html.Span(
                        f"run {idx + 1}: {label}",
                        style={
                            "color": color,
                            "background": "#f1f3f5",
                            "borderRadius": "4px",
                            "padding": "2px 8px",
                            "fontSize": "0.78rem",
                            "fontWeight": 600,
                            "marginRight": "6px",
                        },
                    )
                )

        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(test_name, className="fw-semibold me-2"),
                            html.Span(
                                f"{weight:.0f}% of score",
                                style={
                                    "background": "#e7f5ff",
                                    "color": "#1971c2",
                                    "borderRadius": "999px",
                                    "padding": "1px 10px",
                                    "fontSize": "0.78rem",
                                    "fontWeight": 600,
                                },
                            ),
                        ],
                        className="d-flex align-items-center mb-1",
                    ),
                    html.Div(
                        html.Div(
                            style={
                                "width": f"{bar_pct:.1f}%",
                                "height": "100%",
                                "background": C_BANNER,
                                "borderRadius": "999px",
                                "transition": "width 400ms ease",
                            }
                        ),
                        style={
                            "height": "10px",
                            "background": "#dee2e6",
                            "borderRadius": "999px",
                            "overflow": "hidden",
                            "marginBottom": "4px",
                        },
                    ),
                    html.Div(
                        [
                            html.Span(
                                f"{agg:.3f} / {max_s:.3f}",
                                style={"fontWeight": 600, "marginRight": "6px"},
                            ),
                            html.Span(
                                f"-> {success_pct:.1f}% success rate",
                                className="text-muted me-3",
                            ),
                            html.Span(
                                f"earned {contribution:.2f} / {weight:.1f} pts",
                                style={"color": C_FINAL, "fontWeight": 600},
                            ),
                        ],
                        style={"fontSize": "0.82rem"},
                        className="mb-1",
                    ),
                    (
                        html.Div(run_cells, className="d-flex flex-wrap")
                        if run_cells
                        else html.Div()
                    ),
                ],
                className="mb-3 pb-3",
                style={"borderBottom": f"1px solid {C_BORDER}"},
            )
        )

    return html.Div(
        [header] + rows,
        style={
            "background": "#f8f9fa",
            "border": f"1px solid {C_BORDER}",
            "borderRadius": "8px",
            "padding": "16px 20px",
        },
    )


def _build_progress_stats(
    current_records: list[dict], all_records: list[dict]
) -> html.Div:
    """Build a small stats panel for the current generation.

    Args:
        current_records: Records for the current generation.
        all_records: All available records (for computing bests).

    Returns:
        A Dash `Div` summarising generation-level statistics.
    """
    gen_index = current_records[0].get("gen_index", -1) if current_records else -1
    gen_label = f"Gen {gen_index}" if gen_index >= 0 else "—"

    best_record = max(
        [r for r in all_records if not r.get("failed", False)],
        key=lambda x: x.get("final_score", 0),
        default=None,
    )
    best_score = best_record.get("final_score", 0) if best_record else 0
    best_trial = (
        f"{best_record.get('gen_name', '')} / {best_record.get('trial_name', '')}"
        if best_record
        else "N/A"
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H6("Generation", className="text-muted"),
                            html.H4(gen_label, className="text-info"),
                        ],
                        className="col-12 col-md-6",
                    ),
                    html.Div(
                        [
                            html.H6("Best Score", className="text-muted"),
                            html.H4(f"{best_score:.4f}", className="text-warning"),
                            html.Small(best_trial, className="text-muted"),
                        ],
                        className="col-12 col-md-6",
                    ),
                ],
                className="row g-3",
            )
        ],
        className="p-3 bg-light rounded",
    )


def _build_progress_grid(records: list[dict]) -> html.Div:
    """Render the progress grid composed of multiple trial cards.

    Args:
        records: List of trial records for the grid.

    Returns:
        A Dash `Div` containing the grid of trial cards.
    """
    if not records:
        return html.Div("No trial data found.", className="text-muted")
    rows = [_build_progress_card(record) for record in records]
    return html.Div(rows, style={"display": "grid", "gap": "12px"})
