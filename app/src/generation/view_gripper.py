from __future__ import annotations

import argparse
from pathlib import Path

from _gripper_common import LAB_ROOT, ensure_cadquery_runtime, load_jsonc, params_from_config

ensure_cadquery_runtime()

from core.assembly import assemble_model
from core.params import ModelParams, validate_params


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default=str(LAB_ROOT / "config" / "lab_config.jsonc"),
    )
    args = parser.parse_args()

    cfg = load_jsonc(Path(args.config))
    params = params_from_config(cfg, ModelParams())
    validate_params(params)

    result = assemble_model(params)

    from ocp_vscode import show
    show(result)


if __name__ == "__main__":
    main()
