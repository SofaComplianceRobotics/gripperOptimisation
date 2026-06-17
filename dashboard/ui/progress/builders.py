"""Progress card builders for the monitoring dashboard.

This module focuses on compact, per-trial UI elements. The functions here
take trial records and turn them into small Dash components that show the
trial status, score, and run-level progress information.

Module contents:
    _build_weight_segment_bar: Render a segmented ladder bar.
    _build_progress_card: Render a compact card summarising a trial.
"""

from dash import html

from dashboard.data.cache import _load_trial_state
from dashboard.plotting.colors import C_BANNER

from .helpers import (
    _get_test_max_score,
    _state_color,
    _get_live_score,
    _get_trial_actual_state,
    _run_state_label,
    _weight_segment_style,
)


def _build_weight_segment_bar(segments: list[dict]) -> html.Div:
    """Build a segmented ladder bar from per-segment metadata.

    Each segment represents one candidate in the weight search ladder. The bar
    visualises color, border, label, and state to indicate tested and pending
    candidates.

    Args:
        segments (list[dict]): Segment metadata dictionaries. Each dictionary
            may include keys such as ``label``, ``title``, ``state``,
            ``color``, and ``border_color``.

    Returns:
        dash.html.Div: A Div containing the segmented ladder bar. Returns an
        empty Div when ``segments`` is falsy.
    """
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
        # Keep the label visible only when the ladder is small enough to read.
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
    """Build a compact card that summarises one trial.

    The card shows the trial index, canonical state, final score, and a list
    of runs. Each run entry includes a label, a progress bar (or a segmented
    ladder) and a short summary string.

    Args:
        trial_record (dict): Trial metadata containing fields like
            ``trial_index``, ``gen_index``, and ``final_score``. The function
            uses these fields for labeling and for lookup of the detailed
            trial state in the cache.

    Returns:
        dash.html.Div: A Div with the rendered trial card. If detailed run
        state is present, the Div contains one sub-row per run.
    """
    # Load the detailed trial state so the card can show run-by-run progress.
    trial_state = _load_trial_state(trial_record) or {}
    runs = trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []
    trial_index = trial_record.get("trial_index", 0)
    final_score = trial_record.get("final_score")

    # Resolve the current trial state using the canonical state logic.
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
                f"{test_name} |{count_str}{weight_text} {score_label} "
                f"| {_run_state_label(run_state)}"
            )

            # Surface the run's `reason` (e.g. why it failed, or what phase it
            # is in) on the summary line when there are no ladder segments to
            # show there instead. This is the detail the bare state label lacks.
            run_reason = str(run.get("reason") or "").strip()

            # Each run gets a compact label, a progress bar, and a short summary.
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
                            # Show ladder segments when they exist; otherwise show a
                            # plain progress bar that reflects the live score.
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
                            # Summarize the selected ladder weight and segment
                            # notes; when there are no segments, fall back to the
                            # run's reason so the phase/failure detail is visible.
                            (
                                segment_summary
                                if isinstance(segments, list) and segments
                                else run_reason
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
