"""Tk-based selection dialog for ShapeOPT tests."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .registry import get_default_test_names, get_test_catalog


def prompt_for_tests(
    title: str,
    multi_select: bool = False,
    prompt: str | None = None,
) -> tuple[str, ...]:
    """Prompt the user to pick one or more registered tests.

    Returns the default selection if the dialog cannot be shown or is cancelled.
    """
    catalog = get_test_catalog()
    items = list(catalog.values())
    defaults = get_default_test_names()

    try:
        root = tk.Tk()
    except Exception as exc:
        print(f"[labtests.ui] Could not open test picker dialog: {exc}")
        return defaults

    root.title(title)
    root.geometry("560x360")
    root.minsize(480, 300)
    root.configure(bg="white")
    root.resizable(True, True)
    root.attributes("-topmost", True)

    result: list[str] = []
    weights: dict[str, tk.StringVar] = {}
    selected_indices = [idx for idx, item in enumerate(items) if item.name in defaults]

    container = ttk.Frame(root, padding=14)
    container.pack(fill="both", expand=True)

    header = ttk.Label(
        container,
        text=(
            prompt
            if prompt
            else ("Choose one test" if not multi_select else "Choose one or more tests")
        ),
        font=("Segoe UI", 11, "bold"),
    )
    header.pack(anchor="w")

    hint = ttk.Label(
        container,
        text=(
            "Use the scrollbar to browse and Ctrl/Shift to multi-select."
            if multi_select
            else "Pick one test and press OK."
        ),
        foreground="#555",
    )
    hint.pack(anchor="w", pady=(2, 10))

    list_frame = ttk.Frame(container)
    list_frame.pack(fill="both", expand=True)

    listbox = tk.Listbox(
        list_frame,
        selectmode=tk.MULTIPLE if multi_select else tk.BROWSE,
        activestyle="dotbox",
        exportselection=False,
        height=8,
    )
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    for item in items:
        listbox.insert(tk.END, item.display_label)

    if selected_indices:
        for index in selected_indices:
            listbox.selection_set(index)
        listbox.see(selected_indices[0])

    # --- Weights UI ---
    weights_frame = ttk.Frame(container)
    weights_frame.pack(fill="x", pady=(10, 0))

    weights_labels: dict[str, ttk.Label] = {}
    weights_entries: dict[str, ttk.Entry] = {}

    def update_weights_fields(*_):
        # Clear previous widgets
        for widget in weights_frame.winfo_children():
            widget.destroy()
        weights.clear()
        weights_labels.clear()
        weights_entries.clear()
        # Get selected test names
        selected = [listbox.get(i) for i in listbox.curselection()]
        selected_items = [item for item in items if item.display_label in selected]
        if not selected_items:
            return
        # Default: equal weights
        default_weight = 100 // len(selected_items) if selected_items else 100
        remainder = 100 - default_weight * len(selected_items)
        for idx, item in enumerate(selected_items):
            var = tk.StringVar()
            val = str(default_weight + (1 if idx == 0 and remainder else 0))
            var.set(val)
            weights[item.name] = var
            lbl = ttk.Label(
                weights_frame, text=f"Weight for {item.display_label} (%) :"
            )
            lbl.grid(row=idx, column=0, sticky="w", padx=(0, 6), pady=2)
            entry = ttk.Entry(weights_frame, textvariable=var, width=5)
            entry.grid(row=idx, column=1, sticky="w", pady=2)
            weights_labels[item.name] = lbl
            weights_entries[item.name] = entry
        # Info label
        info = ttk.Label(weights_frame, text="Sum must be 100%", foreground="#555")
        info.grid(
            row=len(selected_items), column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

    listbox.bind("<<ListboxSelect>>", update_weights_fields)
    # Initialize weights fields for default selection
    root.after(100, update_weights_fields)

    button_row = ttk.Frame(container)
    button_row.pack(fill="x", pady=(12, 0))

    def _accept() -> None:
        chosen = [listbox.get(index) for index in listbox.curselection()]
        names: list[str] = []
        for label in chosen:
            for item in items:
                if item.display_label == label:
                    names.append(item.name)
                    break
        if not names:
            names.extend(defaults)
        # Validate weights
        if names:
            try:
                total = sum(int(weights[n].get()) for n in names)
            except Exception:
                tk.messagebox.showerror(
                    "Invalid input", "All weights must be integers."
                )
                return
            if total != 100:
                tk.messagebox.showerror(
                    "Invalid weights", f"Sum of weights must be 100% (got {total}%)"
                )
                return
        result[:] = names
        # Attach weights as attribute for downstream use
        result.weights = {n: int(weights[n].get()) for n in names} if names else {}
        root.destroy()

    def _cancel() -> None:
        result[:] = list(defaults)
        result.weights = {n: 100 // len(defaults) for n in defaults} if defaults else {}
        root.destroy()

    ok_button = ttk.Button(button_row, text="OK", command=_accept)
    ok_button.pack(side="right")
    cancel_button = ttk.Button(button_row, text="Cancel", command=_cancel)
    cancel_button.pack(side="right", padx=(0, 8))

    root.protocol("WM_DELETE_WINDOW", _cancel)
    root.bind("<Return>", lambda _event: _accept())
    root.bind("<Escape>", lambda _event: _cancel())

    if not multi_select and selected_indices:
        listbox.activate(selected_indices[0])

    root.mainloop()
    return tuple(result) if result else defaults
