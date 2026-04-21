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
        result[:] = names
        root.destroy()

    def _cancel() -> None:
        result[:] = list(defaults)
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
