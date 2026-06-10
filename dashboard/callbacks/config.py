"""Dashboard callbacks for the Config tab."""

from __future__ import annotations

import json
import re

from dash import Input, Output, State, html

from dashboard.process.process_manager import CONFIG_FILE


def register_config_callbacks(app) -> None:
    """Register config tab callbacks: save button handler."""

    @app.callback(
        Output("config-save-status", "children"),
        Input("config-save-btn", "n_clicks"),
        State("config-textarea", "value"),
        prevent_initial_call=True,
    )
    def save_config(_, text):
        """Validate and persist the config textarea content to disk.

        Strips JSONC ``//`` comments before parsing so the editor can display
        them without breaking JSON serialisation.

        Args:
            _: Unused click count from the save button.
            text: Raw config text from the textarea, may contain ``//`` comments.

        Returns:
            A green ``"Saved."`` Span on success, or a red error Span if the
            JSON is invalid or the write fails.
        """
        if not text:
            return "Nothing to save."
        try:
            clean = re.sub(r"//[^\n]*", "", text)  # strip JSONC // comments before parsing
            data = json.loads(clean)
            CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return html.Span("Saved.", style={"color": "#2f9e44"})
        except json.JSONDecodeError as exc:
            return html.Span(f"Invalid JSON: {exc}", style={"color": "#e03131"})
        except Exception as exc:
            return html.Span(f"Error: {exc}", style={"color": "#e03131"})