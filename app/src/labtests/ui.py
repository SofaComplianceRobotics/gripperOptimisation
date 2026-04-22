"""PyQt6-based selection dialog for ShapeOPT tests.

Drop-in replacement for the Tkinter version.
Public API is identical: prompt_for_tests() returns tuple[str, ...] and
the tuple carries a `.weights` attribute with {test_name: int} values.
"""

from __future__ import annotations

import math
import sys
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .registry import get_default_test_names, get_test_catalog

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
C_BANNER = "#404867"
C_SEL_TEXT = "#ffffff"
C_BG = "#ffffff"
C_SECTION = "#fafbfc"
C_TEXT = "#000000"
C_BORDER = "#d0d3d8"
C_OK = "#2a7a2a"
C_ERR = "#c0392b"
C_HINT = "#555555"

SLICE_COLORS = [
    "#404867",
    "#6b7aad",
    "#9aa3cc",
    "#c5cadf",
    "#2c3e6b",
    "#8892b8",
    "#4a5580",
    "#b0b7d1",
]

DIALOG_STYLE = f"""
QDialog {{ background: {C_BG}; border-radius: 8px; }}
QLabel#banner {{
    background: {C_BANNER}; color: {C_SEL_TEXT};
    padding: 10px 16px; font-size: 13px; font-weight: bold;
    font-family: "Segoe UI";
    border-top-left-radius: 8px; border-top-right-radius: 8px;
}}
QListWidget {{
    background: {C_SECTION}; border: 1px solid {C_BORDER};
    border-radius: 6px; font-family: "Segoe UI"; font-size: 12px;
    color: {C_TEXT}; outline: none;
}}
QListWidget::item {{ padding: 5px 8px; border-bottom: 1px solid {C_BORDER}; color: {C_TEXT}; }}
QListWidget::item:hover {{ background: #eef0f5; color: {C_TEXT}; }}
QPushButton#pill {{
    background: {C_SECTION}; border: 1px solid {C_BORDER}; border-radius: 4px;
    padding: 3px 12px; font-family: "Segoe UI"; font-size: 11px;
    color: {C_TEXT}; min-width: 0px;
}}
QPushButton#pill:hover {{ background: #eef0f5; border-color: {C_BANNER}; }}
QPushButton#pill:pressed {{ background: {C_BANNER}; color: {C_SEL_TEXT}; }}
QSpinBox {{
    border: 1px solid {C_BORDER}; border-radius: 4px; padding: 2px 8px;
    background: {C_BG}; font-family: "Segoe UI"; font-size: 12px; color: {C_TEXT};
    min-width: 56px;
}}
QSpinBox:focus {{ border-color: {C_BANNER}; }}
QSpinBox::up-button {{ width: 0px; border: none; }}
QSpinBox::down-button {{ width: 0px; border: none; }}
QPushButton {{
    font-family: "Segoe UI"; font-size: 12px; padding: 5px 18px;
    border-radius: 4px; border: 1px solid {C_BORDER};
    background: {C_SECTION}; color: {C_TEXT}; min-width: 72px;
}}
QPushButton:hover {{ background: #eef0f5; border-color: {C_BANNER}; }}
"""

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------
_ROLE_SEL = Qt.ItemDataRole.UserRole + 1  # type: ignore[operator]
_ROLE_NAME = Qt.ItemDataRole.UserRole


# ---------------------------------------------------------------------------
# List-row delegate
# ---------------------------------------------------------------------------
class _ToggleRowDelegate(QStyledItemDelegate):
    SEL_BG = QColor(C_BANNER)
    SEL_FG = QColor(C_SEL_TEXT)
    UNSEL_BG = QColor(C_SECTION)
    UNSEL_FG = QColor(C_TEXT)
    HOVER_BG = QColor("#eef0f5")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        sel = index.data(_ROLE_SEL) or False
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        bg = self.SEL_BG if sel else (self.HOVER_BG if hover else self.UNSEL_BG)
        fg = self.SEL_FG if sel else self.UNSEL_FG
        painter.save()
        painter.fillRect(option.rect, bg)
        painter.setPen(QPen(QColor(C_BORDER), 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.setPen(QPen(fg))
        painter.drawText(
            option.rect.adjusted(8, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            index.data(Qt.ItemDataRole.DisplayRole) or "",
        )
        painter.restore()


# ---------------------------------------------------------------------------
# Pie-chart widget
# ---------------------------------------------------------------------------
class _PieChart(QWidget):
    """Interactive pie with draggable boundary handles on the circumference."""

    weightsChanged = pyqtSignal(list)  # list[int] summing to 100

    HANDLE_R = 8  # handle radius px
    HIT_R = 14  # hit-zone radius px (larger than visual for easier grab)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._names: list[str] = []
        self._weights: list[int] = []
        self._dragging: Optional[int] = None
        self._drag_start_weights: list[int] = []
        self._drag_start_boundary_angle: float = 0.0
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    # ── public ────────────────────────────────────────────────────────────
    def set_data(self, names: list[str], weights: list[int]) -> None:
        self._names = list(names)
        self._weights = list(weights)
        self.update()

    def get_weights(self) -> list[int]:
        return list(self._weights)

    # ── geometry ──────────────────────────────────────────────────────────
    def _pie_rect(self) -> QRectF:
        pad = self.HANDLE_R + 4
        s = min(self.width(), self.height()) - 2 * pad
        return QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)

    def _center(self) -> QPointF:
        r = self._pie_rect()
        return QPointF(r.x() + r.width() / 2, r.y() + r.height() / 2)

    def _radius(self) -> float:
        return self._pie_rect().width() / 2

    def _cumulative_angle_deg(self, up_to_idx: int) -> float:
        """Qt pie convention: 0° = 3 o'clock, positive = counter-clockwise.
        We map 0% → 0° and go clockwise (negative direction in Qt)."""
        pct = sum(self._weights[: up_to_idx + 1])
        return pct * 3.6  # 360/100, clockwise → negate when calling Qt

    def _boundary_point(self, boundary_idx: int) -> QPointF:
        """Point on the circumference where slice boundary_idx meets boundary_idx+1."""
        angle_deg = self._cumulative_angle_deg(boundary_idx)
        # Convert: start=90° (12 o'clock), clockwise
        qt_deg = 90.0 - angle_deg  # Qt: CCW from 3 o'clock → we start at 12
        rad = math.radians(qt_deg)
        c = self._center()
        r = self._radius()
        return QPointF(c.x() + r * math.cos(rad), c.y() - r * math.sin(rad))

    def _angle_from_center(self, pos: QPointF) -> float:
        """Clockwise angle in degrees from 12 o'clock (top) for a given point."""
        c = self._center()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        # atan2 in screen coords (y-down): angle from positive-x, CCW
        raw = math.degrees(
            math.atan2(-dy, dx)
        )  # flip y → mathematical angle from right
        # Convert to clockwise-from-top
        cw_from_top = (90.0 - raw) % 360.0
        return cw_from_top

    def _project_to_rim(self, pos: QPointF) -> QPointF:
        """Nearest point on the pie rim to pos."""
        c = self._center()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        dist = math.hypot(dx, dy) or 1e-9
        r = self._radius()
        return QPointF(c.x() + dx / dist * r, c.y() + dy / dist * r)

    # ── hit testing ───────────────────────────────────────────────────────
    def _hit_boundary(self, pos: QPointF) -> Optional[int]:
        n = len(self._weights)
        for i in range(n - 1):  # skip the last (wrap) boundary
            bp = self._boundary_point(i)
            if math.hypot(pos.x() - bp.x(), pos.y() - bp.y()) <= self.HIT_R:
                return i
        return None

    # ── mouse events ──────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and len(self._weights) > 1:
            hit = self._hit_boundary(event.position())
            if hit is not None:
                self._dragging = hit
                self._drag_start_weights = list(self._weights)
                # Record the angle of the boundary at drag start
                self._drag_start_boundary_angle = self._cumulative_angle_deg(hit)
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._dragging is None:
            hit = self._hit_boundary(pos)
            self.setCursor(
                QCursor(Qt.CursorShape.CrossCursor)
                if hit is not None
                else QCursor(Qt.CursorShape.ArrowCursor)
            )
            return

        # Project mouse onto rim → get its clockwise-from-top angle
        rim_pt = self._project_to_rim(pos)
        cur_angle = self._angle_from_center(rim_pt)

        # The new boundary position (clamped between the previous boundary and next)
        idx = self._dragging
        w = self._drag_start_weights

        # Angle of previous boundary (start of slice idx)
        prev_angle = sum(w[:idx]) * 3.6  # clockwise degrees from top
        # Angle of next boundary (start of slice idx+2, i.e. end of slice idx+1)
        next_angle = sum(w[: idx + 2]) * 3.6 if idx + 2 <= len(w) else 360.0

        # Clamp new boundary within [prev+0, next-0]  (allow 0% slices)
        new_angle = max(prev_angle, min(cur_angle, next_angle))

        # Convert angles back to weights
        new_boundary_pct = round(new_angle / 3.6)
        prev_pct = sum(w[:idx])
        next_pct = sum(w[: idx + 2]) if idx + 2 <= len(w) else 100

        new_w_idx = max(0, min(new_boundary_pct - prev_pct, next_pct - prev_pct))
        new_w_next = (next_pct - prev_pct) - new_w_idx

        new_weights = list(w)
        new_weights[idx] = new_w_idx
        new_weights[idx + 1] = new_w_next

        self._weights = new_weights
        self.update()
        self.weightsChanged.emit(self._weights)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    # ── painting ──────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:
        if not self._weights:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._pie_rect()
        c = self._center()
        cx, cy = c.x(), c.y()
        n = len(self._weights)

        # Qt drawPie: startAngle in 1/16°, measured CCW from 3 o'clock.
        # We want to start at 12 o'clock (= 90° in Qt terms) and go CW.
        qt_start = 90 * 16  # 12 o'clock in Qt 1/16° units

        for i, w in enumerate(self._weights):
            color = QColor(SLICE_COLORS[i % len(SLICE_COLORS)])
            span_qt = -int(w * 3.6 * 16)  # negative = clockwise

            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(rect, qt_start, span_qt)

            # White separator line
            painter.setPen(QPen(QColor(C_BG), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPie(rect, qt_start, span_qt)

            # Percentage label (only if slice ≥ 7%)
            if w >= 7:
                mid_cw_deg = sum(self._weights[:i]) * 3.6 + w * 3.6 / 2
                mid_qt_deg = 90.0 - mid_cw_deg
                mid_rad = math.radians(mid_qt_deg)
                lr = self._radius() * 0.62
                lx = cx + lr * math.cos(mid_rad)
                ly = cy - lr * math.sin(mid_rad)
                painter.setPen(QPen(QColor("#ffffff")))
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                painter.drawText(
                    QRectF(lx - 20, ly - 10, 40, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{w}%",
                )

            qt_start += span_qt

        # Draw handles at each inter-slice boundary (not the wrap boundary)
        for i in range(n - 1):
            bp = self._boundary_point(i)
            is_drag = self._dragging == i
            fill = QColor("#ffe066") if is_drag else QColor("#ffffff")
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(C_BANNER), 2))
            painter.drawEllipse(bp, self.HANDLE_R, self.HANDLE_R)

        painter.end()


# ---------------------------------------------------------------------------
# _ResultTuple
# ---------------------------------------------------------------------------
class _ResultTuple(tuple):
    weights: dict[str, int]


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
class _TestPickerDialog(QDialog):

    def __init__(
        self,
        title: str,
        multi_select: bool,
        prompt: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 640)
        self.setMinimumSize(580, 500)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setStyleSheet(DIALOG_STYLE)
        self.raise_()
        self.activateWindow()

        self._catalog = get_test_catalog()
        self._items = list(self._catalog.values())
        self._defaults = get_default_test_names()
        self._multi_select = multi_select
        self._spinboxes: dict[str, QSpinBox] = {}
        self._spin_lock = False

        self._build_ui(prompt)
        self._init_selection()

    # ── build UI ──────────────────────────────────────────────────────────
    def _build_ui(self, prompt: str | None) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        banner = QLabel(
            prompt
            if prompt
            else (
                "Choose one test"
                if not self._multi_select
                else "Choose one or more tests"
            )
        )
        banner.setObjectName("banner")
        banner.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(banner)

        body = QWidget()
        body.setStyleSheet(f"background: {C_BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 14, 16, 12)
        bl.setSpacing(10)
        root.addWidget(body, stretch=1)

        if self._multi_select:
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            for label, slot in (
                ("Select all", self._select_all),
                ("Deselect all", self._deselect_all),
            ):
                btn = QPushButton(label)
                btn.setObjectName("pill")
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.clicked.connect(slot)
                btn_row.addWidget(btn)
            bl.addLayout(btn_row)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setAlternatingRowColors(False)
        self._list.setMinimumHeight(120)
        self._list.setMaximumHeight(190)
        self._list.setMouseTracking(True)
        self._list.setItemDelegate(_ToggleRowDelegate(self._list))
        for it in self._items:
            wi = QListWidgetItem(it.display_label)
            wi.setData(_ROLE_NAME, it.name)
            wi.setData(_ROLE_SEL, False)
            self._list.addItem(wi)
        self._list.itemClicked.connect(self._on_item_clicked)
        bl.addWidget(self._list)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C_BORDER};")
        bl.addWidget(line)

        # Weights area: pie (left) + spinboxes (right)
        weights_row = QHBoxLayout()
        weights_row.setSpacing(16)

        self._pie = _PieChart()
        self._pie.setFixedSize(230, 230)
        self._pie.weightsChanged.connect(self._on_pie_changed)
        weights_row.addWidget(self._pie)

        spin_outer = QWidget()
        spin_outer.setStyleSheet(
            f"background: {C_SECTION}; border: 1px solid {C_BORDER}; border-radius: 6px;"
        )
        self._spin_layout = QVBoxLayout(spin_outer)
        self._spin_layout.setContentsMargins(10, 8, 10, 8)
        self._spin_layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(spin_outer)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {C_SECTION};")
        weights_row.addWidget(scroll, stretch=1)

        bl.addLayout(weights_row, stretch=1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        self._sum_label = QLabel("Select tests above to assign weights.")
        self._sum_label.setStyleSheet(
            f"color: {C_HINT}; font-style: italic; font-size: 12px;"
        )
        bottom_row.addWidget(self._sum_label, stretch=1)

        self._normalize_btn = QPushButton("Normalize")
        self._normalize_btn.setObjectName("pill")
        self._normalize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._normalize_btn.setToolTip("Set all weights to equal values")
        self._normalize_btn.clicked.connect(self._on_normalize)
        bottom_row.addWidget(self._normalize_btn)

        bl.addLayout(bottom_row)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self._on_cancel)
        bl.addWidget(self._buttons)

        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if self._ok_button:
            self._ok_button.setStyleSheet(
                f"background:{C_BANNER}; color:{C_BG}; border-color:{C_BANNER};"
                f"padding:5px 18px; border-radius:4px; font-size:12px; min-width:72px;"
            )
            self._ok_button.setEnabled(False)

    # ── selection ─────────────────────────────────────────────────────────
    def _visual_select(self, item: QListWidgetItem, selected: bool) -> None:
        item.setData(_ROLE_SEL, selected)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if not self._multi_select:
            for i in range(self._list.count()):
                self._visual_select(self._list.item(i), False)
        self._visual_select(item, not (item.data(_ROLE_SEL) or False))
        self._rebuild_weights()

    def _select_all(self) -> None:
        for i in range(self._list.count()):
            self._visual_select(self._list.item(i), True)
        self._rebuild_weights()

    def _deselect_all(self) -> None:
        for i in range(self._list.count()):
            self._visual_select(self._list.item(i), False)
        self._rebuild_weights()

    def _init_selection(self) -> None:
        default_names = set(self._defaults)
        for i in range(self._list.count()):
            item = self._list.item(i)
            self._visual_select(item, item.data(_ROLE_NAME) in default_names)
        self._rebuild_weights()

    def _selected_catalog_items(self):
        result = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(_ROLE_SEL):
                cat = self._catalog.get(item.data(_ROLE_NAME))
                if cat:
                    result.append(cat)
        return result

    # ── rebuild weight panel ───────────────────────────────────────────────
    def _rebuild_weights(self) -> None:
        old: dict[str, int] = {n: sb.value() for n, sb in self._spinboxes.items()}

        while self._spin_layout.count():
            child = self._spin_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._spinboxes.clear()

        selected = self._selected_catalog_items()

        if not selected:
            self._pie.set_data([], [])
            self._sum_label.setText("Select tests above to assign weights.")
            self._sum_label.setStyleSheet(
                f"color: {C_HINT}; font-style: italic; font-size: 12px;"
            )
            if self._ok_button:
                self._ok_button.setEnabled(False)
            return

        # Build weights, reusing old values where possible
        default_w = 100 // len(selected)
        remainder = 100 - default_w * len(selected)
        weights: list[int] = [
            old.get(it.name, default_w + (1 if i == 0 and remainder else 0))
            for i, it in enumerate(selected)
        ]
        # Always normalise to 100 on rebuild
        diff = 100 - sum(weights)
        if diff != 0:
            weights[0] = max(0, min(100, weights[0] + diff))

        # Build spinbox rows
        for i, it in enumerate(selected):
            color_hex = SLICE_COLORS[i % len(SLICE_COLORS)]
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)

            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(
                f"background:{color_hex}; border-radius:2px; border:1px solid {C_BORDER};"
            )
            rl.addWidget(swatch)

            lbl = QLabel(it.name)
            lbl.setStyleSheet(
                f"color:{C_TEXT}; font-size:12px; background:transparent;"
            )
            lbl.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            rl.addWidget(lbl)

            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix(" %")
            spin.setFixedWidth(72)
            spin.setValue(weights[i])
            spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            rl.addWidget(spin)

            self._spin_layout.addWidget(row)
            self._spinboxes[it.name] = spin

        self._spin_layout.addStretch()

        # Connect valueChanged for immediate forward-cascade on every change
        for name, sb in self._spinboxes.items():
            sb.valueChanged.connect(lambda val, n=name: self._on_spin_changed(n, val))

        self._pie.set_data([it.name for it in selected], weights)
        self._update_sum_label()

    # ── sync spinbox ↔ pie ────────────────────────────────────────────────
    def _on_spin_changed(self, changed_name: str, new_val: int) -> None:
        """Called on every valueChanged signal.
        Cascades the delta forward, wrapping around the ring (skipping the
        changed spinbox itself). The neighbour at idx+1 absorbs first, then
        idx+2, … wrapping back to 0, 1, … idx-1.

        Examples with [30, 60, 10]:
          10 → 20  : next is [0] (30), 30 → 20        → [20, 60, 20]
          60 → 80  : next is [2] (10), 10 → 0; still need 10 → [0] (30), 30 → 20  → [20, 80, 0]
        """
        if self._spin_lock:
            return

        names = list(self._spinboxes.keys())
        n = len(names)
        idx = names.index(changed_name)

        cur = [sb.value() for sb in self._spinboxes.values()]

        # Delta vs what the pie last knew
        pie_w = self._pie.get_weights()
        old_val = pie_w[idx] if idx < len(pie_w) else cur[idx]
        delta = cur[idx] - old_val

        if delta == 0:
            return

        # Cascade forward, wrapping around, skipping idx
        remaining = -delta
        for step in range(1, n):
            if remaining == 0:
                break
            j = (idx + step) % n
            give = max(-cur[j], min(remaining, 100 - cur[j]))
            cur[j] += give
            remaining -= give

        # If still not balanced (all neighbours saturated), clamp the source
        if remaining != 0:
            cur[idx] = max(0, min(100, cur[idx] + remaining))

        self._spin_lock = True
        for i, sb in enumerate(self._spinboxes.values()):
            sb.setValue(cur[i])
        self._spin_lock = False

        self._pie.set_data(names, cur)
        self._update_sum_label()

    def _on_pie_changed(self, weights: list[int]) -> None:
        if self._spin_lock:
            return
        self._spin_lock = True
        for i, sb in enumerate(self._spinboxes.values()):
            if i < len(weights):
                sb.setValue(weights[i])
        self._spin_lock = False
        self._update_sum_label()

    def _update_sum_label(self) -> None:
        total = sum(sb.value() for sb in self._spinboxes.values())
        ok = total == 100
        self._sum_label.setText(
            f"Sum: {total}%  {'✓' if ok else '— must equal exactly 100%'}"
        )
        self._sum_label.setStyleSheet(
            f"color:{'#2a7a2a' if ok else '#c0392b'};"
            f"font-weight:{'bold' if ok else 'normal'}; font-size:12px;"
        )
        if self._ok_button:
            self._ok_button.setEnabled(ok)

    def _on_normalize(self) -> None:
        """Distribute weights as evenly as possible (remainder goes to first slot)."""
        n = len(self._spinboxes)
        if n == 0:
            return
        base = 100 // n
        remainder = 100 - base * n
        names = list(self._spinboxes.keys())
        weights = [base + (1 if i < remainder else 0) for i in range(n)]
        self._spin_lock = True
        for i, sb in enumerate(self._spinboxes.values()):
            sb.setValue(weights[i])
        self._spin_lock = False
        self._pie.set_data(names, weights)
        self._update_sum_label()

    # ── accept / cancel ───────────────────────────────────────────────────
    def _on_accept(self) -> None:
        selected = self._selected_catalog_items()
        if not selected:
            QMessageBox.warning(
                self, "No selection", "Please select at least one test."
            )
            return
        total = sum(sb.value() for sb in self._spinboxes.values())
        if total != 100:
            QMessageBox.critical(
                self,
                "Invalid weights",
                f"Sum must be exactly 100% (currently {total}%).",
            )
            return
        self._result_names = [it.name for it in selected]
        self._result_weights = {
            it.name: self._spinboxes[it.name].value() for it in selected
        }
        self.accept()

    def _on_cancel(self) -> None:
        self._result_names = list(self._defaults)
        n = len(self._defaults)
        self._result_weights = {name: 100 // n for name in self._defaults} if n else {}
        self.reject()

    def result_names(self) -> list[str]:
        return getattr(self, "_result_names", list(self._defaults))

    def result_weights(self) -> dict[str, int]:
        return getattr(self, "_result_weights", {})


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def prompt_for_tests(
    title: str,
    multi_select: bool = False,
    prompt: str | None = None,
) -> _ResultTuple:
    defaults = get_default_test_names()
    app = QApplication.instance() or QApplication(sys.argv)

    try:
        dlg = _TestPickerDialog(title=title, multi_select=multi_select, prompt=prompt)
        dlg.exec()
        names = dlg.result_names()
        weights = dlg.result_weights()
    except Exception as exc:
        print(f"[labtests.ui] Could not open test picker dialog: {exc}")
        names = list(defaults)
        n = len(defaults)
        weights = {name: 100 // n for name in defaults} if n else {}

    result = _ResultTuple(names if names else defaults)
    result.weights = weights
    return result
