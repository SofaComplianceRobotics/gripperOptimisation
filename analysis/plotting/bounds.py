"""Parameter bounds visualization."""

import json
import re
from pathlib import Path

import plotly.graph_objects as go

from .colors import C_BG

# ── Paths ──────────────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[2]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"


def _build_param_bounds_graph(show_heatmap: bool = False) -> go.Figure:
    """Build a parameter-bounds visualization, optionally with heatmap.

    Args:
        show_heatmap: If True, include a density heatmap of historic samples.

    Returns:
        A Plotly `Figure` visualizing parameter distributions and markers.
    """
    try:
        from optimization.optimize_config import PARAM_SPECS

        active_specs = [p for p in PARAM_SPECS if p["min"] < p["max"]]

        if not active_specs:
            return go.Figure().add_annotation(text="No active parameters to display")

        def _parse_jsonc(text: str) -> dict:
            clean = re.sub(r"//[^\n]*", "", text)
            return json.loads(clean)

        trial_config_paths = []
        try:
            for gen_dir in sorted(
                TRIALS_DIR.glob("gen_*"),
                key=lambda d: (
                    int(d.name.split("_")[1]) if len(d.name.split("_")) > 1 else 0
                ),
            ):
                for trial_dir in sorted(
                    gen_dir.glob("trial_*"),
                    key=lambda d: (
                        int(d.name.split("_")[1]) if len(d.name.split("_")) > 1 else 0
                    ),
                ):
                    cfg = trial_dir / "lab_config.jsonc"
                    if cfg.exists():
                        trial_config_paths.append(cfg)
        except Exception:
            pass

        trial_configs = []
        for cfg_path in trial_config_paths[-40:]:
            try:
                trial_configs.append(_parse_jsonc(cfg_path.read_text(encoding="utf-8")))
            except Exception:
                pass

        latest_config = trial_configs[-1] if trial_configs else None
        param_names = [spec["name"] for spec in active_specs]
        fig = go.Figure()

        n_hist = len(trial_configs)
        if n_hist > 0:
            nbins = 64
            bin_centers = [(i + 0.5) / nbins for i in range(nbins)]

            z_rows = []
            for spec in active_specs:
                name = spec["name"]
                span = (spec["max"] - spec["min"]) or 1.0
                counts = [0] * nbins
                total = 0
                for cfg in trial_configs:
                    v = cfg.get(name)
                    if isinstance(v, (int, float)):
                        norm = max(0.0, min(1.0, (v - spec["min"]) / span))
                        idx = int(norm * nbins)
                        if idx >= nbins:
                            idx = nbins - 1
                        counts[idx] += 1
                        total += 1

                if total > 0:
                    maxc = max(counts)
                    row = [c / maxc if maxc > 0 else 0.0 for c in counts]
                else:
                    row = [0.0 for _ in counts]
                z_rows.append(row)

            fig.add_trace(
                go.Heatmap(
                    x=bin_centers,
                    y=param_names,
                    z=z_rows,
                    colorscale="YlOrRd",
                    showscale=False,
                    hovertemplate="%{y}<br>Value: %{x:.2f}<br>Rel. density: %{z:.2f}<extra></extra>",
                    zmin=0,
                    zmax=1,
                )
            )

        for spec in active_specs:
            name = spec["name"]
            param_min, param_max = spec["min"], spec["max"]
            span = (param_max - param_min) or 1.0

            values = []
            if latest_config is None:
                values = []
            else:
                v = latest_config.get(name)
                if isinstance(v, (int, float)):
                    values = [float(v)]
                elif isinstance(v, (list, tuple)):
                    values = [float(x) for x in v if isinstance(x, (int, float))]

            if not values:
                values = [(param_min + param_max) / 2]

            side_texts = []
            marker_xs = []
            for val in values:
                norm = max(0.0, min(1.0, (val - param_min) / span))
                marker_xs.append(norm)
                side_texts.append(f"{val:.3f}")

            if marker_xs:
                fig.add_trace(
                    go.Scatter(
                        x=marker_xs,
                        y=[name] * len(marker_xs),
                        mode="markers",
                        marker=dict(
                            symbol="diamond",
                            size=12,
                            color="#ffffff",
                            line=dict(width=2, color="#212121"),
                        ),
                        hovertemplate=(
                            f"<b>{name}</b><br>Current: "
                            + ", ".join(side_texts)
                            + f"<br>Min: {param_min:.3f} | Max: {param_max:.3f}<extra></extra>"
                        ),
                        showlegend=False,
                    )
                )

                fig.add_annotation(
                    x=1.02,
                    y=name,
                    text="[" + ", ".join(side_texts) + "]",
                    showarrow=False,
                    xanchor="left",
                    yanchor="middle",
                    font=dict(size=11, color="#111"),
                )

        row_h = 70 if show_heatmap else 52
        fig.update_layout(
            title="Parameter Bounds Monitor (Latest Trial)",
            xaxis=dict(
                title="Position in Range (0 = Min, 1 = Max)",
                range=[0, 1],
                fixedrange=True,
            ),
            yaxis=dict(
                categoryorder="array",
                categoryarray=list(reversed(param_names)),
                fixedrange=True,
            ),
            barmode="overlay",
            height=max(400, 90 + len(active_specs) * row_h),
            showlegend=False,
            margin={"l": 160, "r": 70, "t": 50, "b": 50},
            plot_bgcolor=C_BG,
            paper_bgcolor=C_BG,
        )

        for spec in active_specs:
            fig.add_annotation(
                x=0.0,
                y=spec["name"],
                text=f"{spec['min']:.3f}",
                xanchor="left",
                yanchor="top",
                showarrow=False,
                yshift=-18,
                font=dict(size=9, color="#888"),
            )
            fig.add_annotation(
                x=1.0,
                y=spec["name"],
                text=f"{spec['max']:.3f}",
                xanchor="right",
                yanchor="top",
                showarrow=False,
                yshift=-18,
                font=dict(size=9, color="#888"),
            )

        return fig
    except Exception as exc:
        print(f"[warn] Error building param bounds: {exc}")
        return go.Figure().add_annotation(text=f"Error: {exc}")
