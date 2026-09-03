"""Parameter Guide tab — plain-language explanation of each tunable parameter.

A lab-side dashboard tab (sofaopt has no equivalent): one collapsible entry per
documented parameter, holding its description and, side by side, a render of the
model at the parameter's minimum and maximum. Bounds are read live from the
project's ParamSpec list; the prose and images live in PARAM_DOCS below.

Images are optional per parameter. Those that exist sit in docs/params/ as
<param>_low.png / <param>_high.png and are served by the /param-doc-image route
registered via register_param_guide_routes (wired in dashboard/app.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from dash import html

from sofaopt.dashboard import context

LAB_ROOT = Path(__file__).resolve().parents[3]
_PARAM_DOCS_DIR = LAB_ROOT / "docs" / "params"


@dataclass(frozen=True)
class ParamDoc:
    """Human-facing explanation of one parameter. Display only — never affects
    sampling. Every field is optional: a description, the images, or both.

    Args:
        description: One or two plain-language sentences: what the parameter
            controls and what moving it does to the model.
        image_low: Render of the model at or near this parameter's minimum.
        image_high: Render at or near its maximum, shown beside image_low.
        group: Section heading the entry is filed under in the guide.
    """

    description: str = ""
    image_low: Path | None = None
    image_high: Path | None = None
    group: str = ""


# Descriptions are a first draft (written from reading geometry/params.py and
# geometry/leg_params.py, not yet reviewed). Images are added per parameter as
# reference renders land in docs/params/ (named <param>_low.png /
# <param>_high.png); most params have none yet.
PARAM_DOCS: dict[str, ParamDoc] = {
    # --- central ring / body ---------------------------------------------
    "cylinder_radius": ParamDoc(
        "Outer radius of the gripper's central ring — the hub every finger and "
        "leg mounts to. Bigger ring = wider palm and the finger roots sit "
        "further apart.",
        image_low=_PARAM_DOCS_DIR / "cylinder_radius_low.png",
        image_high=_PARAM_DOCS_DIR / "cylinder_radius_high.png",
        group="Ring",
    ),
    "cylinder_hole_thickness": ParamDoc(
        "Wall thickness of the ring (outer radius minus the inner bore). "
        "Thicker = stiffer, heavier hub with a smaller hole through the middle.",
        group="Ring",
    ),
    "cylinder_height_A": ParamDoc(
        "Height of the ring wall at the 0 deg / 180 deg positions (the two "
        "finger sides). The rim's top edge is a smooth wave through the A/B/C "
        "heights; raising A lifts the rim under the fingers.",
        group="Ring",
    ),
    "cylinder_height_B": ParamDoc(
        "Height of the ring wall at the 90 deg / 270 deg positions (between the "
        "fingers). Raising B lifts the rim on the open sides.",
        group="Ring",
    ),
    "cylinder_height_C": ParamDoc(
        "Height of the ring wall at the four 45 deg diagonal positions. Sets "
        "how the rim blends between the A and B high/low points.",
        group="Ring",
    ),
    "cylinder_plateau_A_deg": ParamDoc(
        "Angular width of the flat dwell around the A height point before the "
        "rim starts ramping toward its neighbours. Wider plateau = longer flat "
        "section and a steeper ramp on either side.",
        group="Ring",
    ),
    "cylinder_plateau_B_deg": ParamDoc(
        "Angular width of the flat dwell around the B height point. Same idea "
        "as plateau A, on the between-the-fingers side.",
        group="Ring",
    ),
    "cylinder_plateau_C_deg": ParamDoc(
        "Angular width of the flat dwell around each diagonal C point. Clamped "
        "after sampling so A + B + C stays within the 45 deg budget of one "
        "rim segment.",
        group="Ring",
    ),
    # --- legs --------------------------------------------------------------
    "leg_attachement_tilt_angle": ParamDoc(
        "How far the four leg sockets are tilted outward from vertical. Larger "
        "angle = legs splay out more, widening the stance.",
        group="Legs",
    ),
    "leg_p0_hout_dist": ParamDoc(
        "Length of the handle leaving the leg's base (where it clips onto the "
        "motor). Longer = the leg runs straight up out of the clip before any "
        "bow; shorter = it starts curving right away.",
        group="Legs",
    ),
    "leg_p1_dist": ParamDoc(
        "Overall length of the leg, from its motor clip to the point where the "
        "fixed straight tip run begins. Larger = a taller leg.",
        group="Legs",
    ),
    "leg_p1_angle_deg": ParamDoc(
        "Direction the leg's span reaches toward. 90 deg is dead straight up "
        "(the stock leg); away from 90 bows the leg to one side.",
        group="Legs",
    ),
    "leg_p1_hin_dist": ParamDoc(
        "Length of the handle arriving at the top of the leg's span. Controls "
        "how much the leg curves as it meets the straight section that slides "
        "into the gripper pocket.",
        group="Legs",
    ),
    # --- pincers ---------------------------------------------------------------
    "pincer_profile_width": ParamDoc(
        "Thickness of each finger's cross-section (across the pinch direction). "
        "Wider = chunkier, stiffer fingers that resist twisting.",
        group="Pincers",
    ),
    "pincer_profile_height": ParamDoc(
        "Height of each finger's cross-section (along the pinch direction). "
        "Taller = more bending stiffness, so the finger curls less under load.",
        group="Pincers",
    ),
    "p0_hout_dist": ParamDoc(
        "Length of the Bezier handle leaving the finger root. Short = the "
        "finger bends almost immediately off the body; long = it runs straight "
        "out of the root before curving.",
        group="Pincers",
    ),
    "p0_hout_angle_deg": ParamDoc(
        "Direction of that root handle. Rotates which way the finger initially "
        "heads as it leaves the body (up, straight out, or down).",
        group="Pincers",
    ),
    "p1_dist": ParamDoc(
        "How far the fingertip sits from the finger root, in a straight line. "
        "Larger = longer reach / bigger opening between the fingers.",
        group="Pincers",
    ),
    "p1_angle_deg": ParamDoc(
        "The angle from root to fingertip. More negative = the tip sits lower "
        "and more inward (a more closed, hooked grasp).",
        group="Pincers",
    ),
    "p1_hin_dist": ParamDoc(
        "Length of the Bezier handle arriving at the fingertip. Controls how "
        "gradually the finger straightens out as it approaches the tip.",
        group="Pincers",
    ),
    "p1_hin_angle_deg": ParamDoc(
        "Direction of that tip handle — how hooked the very end of the finger "
        "is, and which way the hook points.",
        group="Pincers",
    ),
}


def _doc_image(param: str, bound: str) -> Path | None:
    doc = PARAM_DOCS.get(param)
    if doc is None or bound not in ("low", "high"):
        return None
    return doc.image_low if bound == "low" else doc.image_high


def _fmt_bound(value: float) -> str:
    return f"{value:g}"


def _figure(param_name: str, bound: str, caption: str) -> html.Figure:
    return html.Figure(
        [
            html.Img(
                src=f"/param-doc-image/{quote(param_name)}/{bound}",
                style={
                    "width": "100%",
                    "border": "1px solid #dee2e6",
                    "borderRadius": "4px",
                    "background": "#f8f9fa",
                },
            ),
            html.Figcaption(caption, className="text-muted small text-center mt-1"),
        ],
        className="m-0",
        style={"flex": "1", "minWidth": "0"},
    )


def _param_entry(spec, doc: ParamDoc) -> html.Details:
    body: list = []
    if doc.description:
        body.append(html.P(doc.description, className="mb-2"))

    figures = []
    if doc.image_low is not None and Path(doc.image_low).is_file():
        figures.append(_figure(spec.name, "low", f"minimum ({_fmt_bound(spec.low)})"))
    if doc.image_high is not None and Path(doc.image_high).is_file():
        figures.append(_figure(spec.name, "high", f"maximum ({_fmt_bound(spec.high)})"))
    if figures:
        body.append(
            html.Div(figures, className="d-flex", style={"gap": "16px", "maxWidth": "680px"})
        )

    if not body:
        body.append(
            html.P("No description or images provided.", className="text-muted small mb-0")
        )

    return html.Details(
        [
            html.Summary(
                html.Code(spec.name, style={"fontSize": "0.95rem"}),
                style={"cursor": "pointer", "padding": "8px 0", "fontWeight": "600"},
            ),
            html.Div(body, className="pb-3 ps-2"),
        ],
        className="border-bottom",
    )


def build_param_guide_tab() -> html.Div:
    """Build the Parameter Guide tab from the live ParamSpec list + PARAM_DOCS."""
    specs = list(context.project().params)
    documented = [s for s in specs if s.name in PARAM_DOCS]

    children: list = [
        html.H3("Parameter Guide", className="mb-2"),
        html.P(
            "What each tunable parameter controls, and how the model changes "
            "between its minimum and maximum. Click a name to expand.",
            className="text-muted mb-3",
        ),
    ]

    if not documented:
        children.append(html.P("No documented parameters.", className="text-muted"))
        return html.Div(children, className="p-3")

    # Group headings in first-seen order, entries in ParamSpec order within each.
    seen: list[str] = []
    for spec in documented:
        group = PARAM_DOCS[spec.name].group or "Other"
        if group not in seen:
            seen.append(group)
    for group in seen:
        children.append(html.H5(group, className="mt-3 mb-1"))
        children.extend(
            _param_entry(spec, PARAM_DOCS[spec.name])
            for spec in documented
            if (PARAM_DOCS[spec.name].group or "Other") == group
        )

    orphans = sorted(name for name in PARAM_DOCS if name not in {s.name for s in specs})
    if orphans:
        children.append(
            html.P(
                "Ignored PARAM_DOCS keys (no matching parameter): " + ", ".join(orphans),
                className="text-warning small mt-3",
            )
        )

    return html.Div(children, className="p-3")


def register_param_guide_routes(app) -> None:
    """Serve the Parameter Guide's low/high images over HTTP.

    /param-doc-image/<param>/<bound> where <bound> is "low" or "high". 404s for
    an unknown parameter, an undocumented bound, or a path missing on disk.
    """
    from flask import abort, send_file

    @app.server.route("/param-doc-image/<param>/<bound>")
    def serve_param_doc_image(param, bound):
        image = _doc_image(param, bound)
        if image is None or not Path(image).is_file():
            abort(404)
        return send_file(str(image))
