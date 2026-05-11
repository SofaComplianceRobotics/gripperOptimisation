"""
Launch the standalone SOFA scene against the custom SOFA build.

This keeps the lab's current 3.10-based working environment intact while
pointing the scene runner to the separate custom 3.12 build.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QDoubleSpinBox,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from labtests.registry import get_test_spec
from labtests.ui import prompt_for_tests

APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent
ASSETS_ROOT = LAB_ROOT.parent.parent
RUNSOFA_EXE = r"C:\dev\sofa\build\bin\Release\runSofa.exe"
SOFA_ROOT = r"C:\dev\sofa\build"
SOFA_PYTHON_PATH = r"C:\Users\Cesar\AppData\Local\Programs\Python\Python312"
SOFA_SITE_PACKAGES = r"C:\dev\sofa\build\lib\python3\site-packages"

# Color palette (matches labtests.ui)
C_BANNER = "#404867"
C_SEL_TEXT = "#ffffff"
C_BG = "#ffffff"
C_SECTION = "#fafbfc"
C_TEXT = "#000000"
C_BORDER = "#d0d3d8"

DIALOG_STYLE = f"""
QDialog {{ background: {C_BG}; border-radius: 8px; }}
QLabel#banner {{
    background: {C_BANNER}; color: {C_SEL_TEXT};
    padding: 10px 16px; font-size: 13px; font-weight: bold;
    font-family: "Segoe UI";
    border-top-left-radius: 8px; border-top-right-radius: 8px;
}}
QLabel {{ font-family: "Segoe UI"; font-size: 12px; color: {C_TEXT}; }}
QDoubleSpinBox {{
    border: 1px solid {C_BORDER}; border-radius: 4px; padding: 2px 8px;
    background: {C_BG}; font-family: "Segoe UI"; font-size: 12px; color: {C_TEXT};
}}
QDoubleSpinBox:focus {{ border-color: {C_BANNER}; }}
QPushButton {{
    font-family: "Segoe UI"; font-size: 12px; padding: 5px 18px;
    border-radius: 4px; border: 1px solid {C_BORDER};
    background: {C_SECTION}; color: {C_TEXT}; min-width: 72px;
}}
QPushButton:hover {{ background: #eef0f5; border-color: {C_BANNER}; }}
"""


def _prompt_for_weight_integrated(test_name: str) -> float | None:
    """Show weight selection as an integrated step. Returns weight or None if going back."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    dialog = QDialog()
    dialog.setWindowTitle("ShapeOPT - Configure Launch")
    dialog.setMinimumWidth(400)
    dialog.setStyleSheet(DIALOG_STYLE)

    layout = QVBoxLayout()
    layout.setSpacing(12)
    layout.setContentsMargins(16, 16, 16, 16)

    # Banner header
    banner = QLabel(f"<b>Configure: {test_name}</b>")
    banner.setObjectName("banner")
    banner.setStyleSheet(
        f"QLabel#banner {{ background: {C_BANNER}; color: {C_SEL_TEXT}; padding: 10px 12px; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; border-radius: 4px; }}"
    )
    layout.addWidget(banner)

    # Content
    layout.addWidget(QLabel("Cube weight (kg):"))

    spinbox = QDoubleSpinBox()
    spinbox.setMinimum(0.01)
    spinbox.setMaximum(0.5)
    spinbox.setValue(0.1)
    spinbox.setSingleStep(0.01)
    spinbox.setDecimals(3)
    spinbox.setSuffix(" kg")
    spinbox.setToolTip("Cube mass in kilograms")
    spinbox.setMinimumHeight(32)
    layout.addWidget(spinbox)

    layout.addWidget(QLabel(""))
    info_label = QLabel("<i>Will launch SOFA 3 times with sizes: 5cm → 8cm → 20cm</i>")
    info_label.setStyleSheet(
        f"color: {C_BORDER}; font-family: 'Segoe UI'; font-size: 11px;"
    )
    layout.addWidget(info_label)
    layout.addWidget(QLabel(""))

    # Buttons: Back and Continue
    button_layout = QHBoxLayout()
    button_layout.setSpacing(8)
    back_btn = QPushButton("← Back")
    continue_btn = QPushButton("Continue →")
    back_btn.setMinimumHeight(32)
    continue_btn.setMinimumHeight(32)

    button_layout.addWidget(back_btn)
    button_layout.addStretch()
    button_layout.addWidget(continue_btn)
    layout.addLayout(button_layout)

    dialog.setLayout(layout)

    result = None

    def on_continue():
        nonlocal result
        result = spinbox.value()
        dialog.accept()

    def on_back():
        dialog.reject()

    back_btn.clicked.connect(on_back)
    continue_btn.clicked.connect(on_continue)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        return result
    else:
        return None


def main() -> None:
    """Launch the scene with the custom SOFA GUI stack."""
    # Hide console window on Windows
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    env = os.environ.copy()

    # Prevent inherited EmioLabs Python settings from polluting SofaPython3 init.
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
    ):
        env.pop(key, None)

    env["SOFA_ROOT"] = SOFA_ROOT
    env["SOFAPYTHON3_ROOT"] = SOFA_ROOT
    env["SOFA_PYTHON_PATH"] = SOFA_PYTHON_PATH
    env["SOFA_SITE_PACKAGES"] = SOFA_SITE_PACKAGES
    env["PATH"] = (
        os.path.join(SOFA_ROOT, "bin", "Release")
        + ";"
        + os.path.join(SOFA_ROOT, "bin")
        + ";"
        + SOFA_PYTHON_PATH
        + ";"
        + env.get("PATH", "")
    )
    env["PYTHONPATH"] = (
        SOFA_SITE_PACKAGES
        + ";"
        + os.path.join(SOFA_ROOT, "plugins", "STLIB")
        + ";"
        + str(ASSETS_ROOT)
    )

    # Loop to allow going back from configuration
    while True:
        selected_tests = prompt_for_tests(
            "Select ShapeOPT scene test", multi_select=False
        )
        test_name = selected_tests[0]
        test_spec = get_test_spec(test_name)
        env["LAB_SHAPEOPT_TEST"] = test_name
        env["LAB_SHAPEOPT_TESTS"] = test_name

        # For a single test the weight is always 100, but we pass it consistently
        # so optimize_config and any downstream consumer always finds the variable.
        env["LAB_SHAPEOPT_TEST_WEIGHTS"] = json.dumps(selected_tests.weights)

        default_stl = LAB_ROOT / "runtime" / "exports" / "new_gripper_collision.stl"
        if default_stl.exists():
            env.setdefault("OPTUNA_STL_PATH", str(default_stl))

        # Special handling for random_cube_pick: prompt for weight with integrated UI
        manual_weight = None
        if test_name == "random_cube_pick":
            manual_weight = _prompt_for_weight_integrated(test_name)
            if manual_weight is None:
                # User clicked "Back" — loop to test selection
                continue
            env["MANUAL_WEIGHT"] = str(manual_weight)

            print(f"\n{'='*60}")
            print(
                f"Launching random_cube_pick 3 times with weight={manual_weight:.3f}kg"
            )
            print(f"Sizes: 5cm → 8cm → 20cm")
            print(f"{'='*60}\n")

            for slot in range(3):
                env["OPTUNA_RUN_SLOT"] = str(slot)
                size_cm = [5, 8, 20][slot]
                print(f"[{slot+1}/3] Launching with {size_cm}cm cube...")
                # Use subprocess.run to continue even if SOFA exits with non-zero status
                result = subprocess.run(
                    [
                        RUNSOFA_EXE,
                        "-l",
                        "SofaImGui",
                        "-l",
                        "SofaPython3",
                        "-g",
                        "imgui",
                        str(test_spec.scene_file),
                    ],
                    cwd=str(ASSETS_ROOT),
                    env=env,
                    startupinfo=startupinfo,
                )
                if result.returncode != 0:
                    print(f"  ⚠ SOFA exited with status {result.returncode}")
                print(f"Scene completed. Close SOFA to continue to next size.\n")
        else:
            result = subprocess.run(
                [
                    RUNSOFA_EXE,
                    "-l",
                    "SofaImGui",
                    "-l",
                    "SofaPython3",
                    "-g",
                    "imgui",
                    str(test_spec.scene_file),
                ],
                cwd=str(ASSETS_ROOT),
                env=env,
                startupinfo=startupinfo,
            )

        # Exit after successful launch (unless we go back)
        break


if __name__ == "__main__":
    main()
