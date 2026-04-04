"""
Foliage Settings Editor
=======================
Per-category sliders for spacing, clustering, Z offset, and canopy collision.
Settings are saved to foliage_config.json, which the generator reads at runtime.

HOW TO RUN:
  • Windows Explorer : double-click this file  (Python must be installed)
  • Command line     : python foliage_settings.py
  • UE Output Log    : import subprocess; subprocess.Popen(["python", r"<full_path_here>"])

Requires standard-library tkinter (included in most Python 3 installers).
"""

import json
import os
import sys

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    print("tkinter is not available in this Python environment.")
    print("Run this script with a standard Python 3 install (not UE's embedded Python).")
    sys.exit(1)

# ── Paths ──────────────────────────────────────────────────────────────────────

_THIS_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_THIS_DIR, "foliage_config.json")

# ── Category metadata ──────────────────────────────────────────────────────────

CATEGORIES = ["LARGE_TREE", "MEDIUM_TREE", "SMALL_TREE", "SHRUB"]

CAT_LABELS = {
    "LARGE_TREE":  "Large Tree",
    "MEDIUM_TREE": "Medium Tree",
    "SMALL_TREE":  "Small Tree / Sapling",
    "SHRUB":       "Shrub / Bush",
}

# Default values (cm) match the plant_planning.pdf Table 3 bounds baked into
# the generator.  Change via sliders — do NOT edit this dict directly.
DEFAULTS = {
    "LARGE_TREE":  {"spacing_cm": 1100, "cluster_count": 4, "cluster_radius_cm": 600, "z_offset_cm":  0},
    "MEDIUM_TREE": {"spacing_cm":  850, "cluster_count": 3, "cluster_radius_cm": 450, "z_offset_cm":  0},
    "SMALL_TREE":  {"spacing_cm":  500, "cluster_count": 1, "cluster_radius_cm":   0, "z_offset_cm":  0},
    "SHRUB":       {"spacing_cm":  220, "cluster_count": 1, "cluster_radius_cm":   0, "z_offset_cm":  0},
}

# Slider definitions: (key, display_label, from, to, resolution, value_formatter)
# cluster_count = 1 means grid mode (no clustering).
SLIDER_DEFS = [
    (
        "spacing_cm",
        "Spacing",
        50, 2000, 10,
        lambda v: f"{float(v) / 100:.1f} m",
    ),
    (
        "cluster_count",
        "Cluster size",
        1, 8, 1,
        lambda v: f"{int(round(float(v)))} {'tree' if round(float(v)) == 1 else 'trees'}  "
                  f"{'(grid / no cluster)' if round(float(v)) == 1 else '(informal group)'}",
    ),
    (
        "cluster_radius_cm",
        "Cluster radius",
        0, 1500, 50,
        lambda v: f"{float(v) / 100:.1f} m",
    ),
    (
        "z_offset_cm",
        "Z offset",
        -500, 500, 5,
        lambda v: f"{int(round(float(v))):+d} cm",
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
#  Application
# ══════════════════════════════════════════════════════════════════════════════

class SettingsApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Foliage Settings")
        self.configure(bg="#2b2b2b")
        self.resizable(False, False)

        self._apply_dark_theme()
        self._load_config()
        self._vars: dict[str, dict[str, tk.DoubleVar]] = {}
        self._build_ui()

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_dark_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        bg  = "#2b2b2b"
        fg  = "#e0e0e0"
        acc = "#4a90d9"
        sel = "#3c3f41"

        style.configure(".",          background=bg, foreground=fg, font=("Segoe UI", 9))
        style.configure("TFrame",     background=bg)
        style.configure("TLabel",     background=bg, foreground=fg)
        style.configure("TLabelframe",      background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=acc, font=("Segoe UI", 9, "bold"))
        style.configure("TNotebook",        background=bg, tabmargins=[2, 5, 2, 0])
        style.configure("TNotebook.Tab",    background=sel, foreground=fg, padding=[10, 4])
        style.map("TNotebook.Tab",          background=[("selected", "#3e6899")],
                                            foreground=[("selected", "#ffffff")])
        style.configure("TCheckbutton",     background=bg, foreground=fg)
        style.map("TCheckbutton",           background=[("active", bg)])
        style.configure("TButton",          background=sel, foreground=fg, padding=[8, 4])
        style.map("TButton",                background=[("active", "#4a90d9")])
        style.configure("TScale",           background=bg, troughcolor="#444444", sliderlength=16)

    # ── Config I/O ─────────────────────────────────────────────────────────────

    def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE) as f:
                    self._cfg = json.load(f)
            else:
                self._cfg = {}
        except Exception:
            self._cfg = {}

        cs = self._cfg.setdefault("category_settings", {})
        for cat in CATEGORIES:
            saved = cs.setdefault(cat, {})
            for key, default in DEFAULTS[cat].items():
                saved.setdefault(key, default)

        # Garden design defaults
        gd = self._cfg.setdefault("garden_design", {})
        gd.setdefault("enabled",          False)
        gd.setdefault("border_width_cm",  300)
        gd.setdefault("border_offset_cm",  40)
        gd.setdefault("border_spacing_cm", 150)
        gd.setdefault("border_rows",         1)
        gd.setdefault("border_sequence",    [])

    def _collect_values(self):
        cs = self._cfg.setdefault("category_settings", {})
        for cat in CATEGORIES:
            s = cs.setdefault(cat, {})
            for key, var in self._vars[cat].items():
                raw = var.get()
                s[key] = int(round(raw)) if key in ("cluster_count",) else int(raw)
        self._cfg["canopy_collision"]       = bool(self._canopy_var.get())
        self._cfg["building_clearance_cm"]  = int(self._clearance_var.get())

        # Garden design values
        gd = self._cfg.setdefault("garden_design", {})
        gd["enabled"]          = bool(self._gd_enabled_var.get())
        gd["border_width_cm"]  = int(self._gd_width_var.get())
        gd["border_offset_cm"] = int(self._gd_offset_var.get())
        gd["border_spacing_cm"]= int(self._gd_spacing_var.get())
        gd["border_rows"]      = int(self._gd_rows_var.get())
        raw_seq = self._gd_sequence_text.get("1.0", "end").strip()
        gd["border_sequence"]  = [
            ln.strip() for ln in raw_seq.splitlines() if ln.strip()
        ]

    def _save_config(self):
        self._collect_values()
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._cfg, f, indent=2)
            messagebox.showinfo(
                "Saved",
                f"Settings saved.\n\nRe-run the generator in UE to apply.",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror("Error", f"Could not save settings:\n{e}", parent=self)

    def _reset_defaults(self):
        for cat in CATEGORIES:
            for key, val in DEFAULTS[cat].items():
                if key in self._vars.get(cat, {}):
                    self._vars[cat][key].set(val)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        cs = self._cfg.get("category_settings", {})

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        for cat in CATEGORIES:
            saved = cs.get(cat, DEFAULTS[cat])
            tab   = ttk.Frame(nb, padding=14)
            nb.add(tab, text=CAT_LABELS[cat])
            self._build_cat_tab(tab, cat, saved)

        # ── Garden Design tab ──────────────────────────────────────────────────
        gd_tab = ttk.Frame(nb, padding=14)
        nb.add(gd_tab, text="Garden Design")
        self._build_garden_tab(gd_tab)

        # ── Global options ─────────────────────────────────────────────────────
        gf = ttk.LabelFrame(self, text="Global Options", padding=10)
        gf.pack(fill="x", padx=12, pady=(0, 8))

        self._canopy_var = tk.BooleanVar(value=self._cfg.get("canopy_collision", False))
        ttk.Checkbutton(
            gf,
            text=(
                "Canopy collision check  —  skip if canopy sphere overlaps any "
                "WorldStatic actor (requires correct collision channels per asset)"
            ),
            variable=self._canopy_var,
        ).pack(anchor="w")

        # Building clearance slider
        clr_row = ttk.Frame(gf)
        clr_row.pack(fill="x", pady=(10, 0))

        ttk.Label(clr_row, text="Building clearance", width=20, anchor="w").pack(side="left")

        self._clearance_lbl = ttk.Label(clr_row, width=14, anchor="w")
        self._clearance_lbl.pack(side="right")

        self._clearance_var = tk.DoubleVar(
            value=float(self._cfg.get("building_clearance_cm", 0))
        )
        self._clearance_var.trace_add(
            "write",
            lambda *_: self._clearance_lbl.config(
                text=(f"{self._clearance_var.get() / 100:.1f} m"
                      if self._clearance_var.get() > 0 else "off")
            ),
        )
        self._clearance_lbl.config(
            text=(f"{self._clearance_var.get() / 100:.1f} m"
                  if self._clearance_var.get() > 0 else "off")
        )
        ttk.Scale(
            clr_row, from_=0, to=2000, variable=self._clearance_var,
            orient="horizontal", length=340,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ttk.Label(
            gf,
            text=(
                "Fires 8 horizontal rays at mid-canopy height.  "
                "Set to roughly half the tree canopy diameter.\n"
                "Works without special collision channel setup — recommended over canopy collision."
            ),
            foreground="#888888",
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # ── Buttons ────────────────────────────────────────────────────────────
        bf = ttk.Frame(self, padding=(12, 0, 12, 12))
        bf.pack(fill="x")

        ttk.Button(bf, text="Save",
                   command=self._save_config, width=18).pack(side="right", padx=(6, 0))
        ttk.Button(bf, text="Reset Defaults",
                   command=self._reset_defaults, width=18).pack(side="right")

    def _build_cat_tab(self, frame: ttk.Frame, cat: str, saved: dict):
        self._vars[cat] = {}

        for key, label, frm, to, res, fmt in SLIDER_DEFS:
            init = saved.get(key, DEFAULTS[cat][key])
            var  = tk.DoubleVar(value=init)
            self._vars[cat][key] = var

            row = ttk.Frame(frame)
            row.pack(fill="x", pady=6)

            ttk.Label(row, text=label, width=17, anchor="w").pack(side="left")

            # Value readout — wide enough for longest formatter string
            val_lbl = ttk.Label(row, text=fmt(init), width=36, anchor="w")
            val_lbl.pack(side="right")

            scale = ttk.Scale(
                row,
                from_=frm, to=to,
                variable=var,
                orient="horizontal",
                length=340,
            )
            scale.pack(side="left", fill="x", expand=True, padx=(0, 8))

            # Live label update via variable trace
            def _on_change(*_, lbl=val_lbl, fn=fmt, v=var):
                lbl.config(text=fn(v.get()))

            var.trace_add("write", _on_change)

        # ── Info block ────────────────────────────────────────────────────────
        info = ttk.Frame(frame)
        info.pack(fill="x", pady=(14, 0))

        notes = {
            "LARGE_TREE":  "Cluster mode: informal groves of 2–4 trees.\n"
                           "Spacing clamped 10–12 m (plant_planning Table 3).",
            "MEDIUM_TREE": "Cluster mode: informal groves of 2–3 trees.\n"
                           "Spacing clamped 7–10 m (plant_planning Table 3).",
            "SMALL_TREE":  "Cluster size = 1 → regular grid with high jitter.\n"
                           "Spacing clamped 4–6 m (plant_planning Table 3).",
            "SHRUB":       "Grid mode with high jitter → natural drift/mass.\n"
                           "Spacing clamped 1.5–3 m (plant_planning Table 3).",
        }
        ttk.Label(
            info,
            text=notes[cat],
            foreground="#888888",
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w")


    def _build_garden_tab(self, frame: ttk.Frame):
        """
        Garden Design tab — configure ordered border rows that follow building fences.

        How it works:
          Cells within 'Border width' of any building wall become BORDER cells.
          Border cells receive neat rows of plants from the sequence list instead
          of random scatter.  The sequence repeats: A-B-A-B or A-B-C-A-B-C etc.
          Interior open-area cells get the normal cluster/naturalistic placement.

        Border sequence format:
          One asset path per line, e.g.
            /Game/Plants/SM_Boxwood_Var1
            /Game/Plants/SM_BirdOfParadise_Var2
            /Game/Plants/SM_Boxwood_Var3
          Right-click any asset in the Content Browser → Copy Reference, then
          paste here.  Remove the leading 'StaticMesh ' prefix if present.
        """
        bg  = "#2b2b2b"
        acc = "#4a90d9"
        gd  = self._cfg.get("garden_design", {})

        # ── Enable toggle ──────────────────────────────────────────────────────
        self._gd_enabled_var = tk.BooleanVar(value=gd.get("enabled", False))
        ttk.Checkbutton(
            frame,
            text="Enable border row planting  (neat fence-following rows)",
            variable=self._gd_enabled_var,
        ).pack(anchor="w", pady=(0, 10))

        # ── Sliders ────────────────────────────────────────────────────────────
        def _slider_row(parent, label, var, lo, hi, fmt_fn):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=label, width=18, anchor="w").pack(side="left")
            lbl = ttk.Label(row, text=fmt_fn(var.get()), width=12, anchor="w")
            lbl.pack(side="right")
            def _upd(*_, l=lbl, v=var, f=fmt_fn): l.config(text=f(v.get()))
            var.trace_add("write", _upd)
            ttk.Scale(row, from_=lo, to=hi, variable=var,
                      orient="horizontal", length=320).pack(
                side="left", fill="x", expand=True, padx=(0, 8))

        self._gd_width_var   = tk.DoubleVar(value=gd.get("border_width_cm",  300))
        self._gd_offset_var  = tk.DoubleVar(value=gd.get("border_offset_cm",  40))
        self._gd_spacing_var = tk.DoubleVar(value=gd.get("border_spacing_cm", 150))
        self._gd_rows_var    = tk.DoubleVar(value=gd.get("border_rows",         1))

        sliders_frame = ttk.LabelFrame(frame, text="Row Parameters", padding=8)
        sliders_frame.pack(fill="x", pady=(0, 10))

        _slider_row(sliders_frame, "Border width",
                    self._gd_width_var, 50, 1500,
                    lambda v: f"{float(v)/100:.1f} m")
        _slider_row(sliders_frame, "Offset from wall",
                    self._gd_offset_var, 10, 300,
                    lambda v: f"{int(float(v))} cm")
        _slider_row(sliders_frame, "Plant spacing",
                    self._gd_spacing_var, 30, 500,
                    lambda v: f"{float(v)/100:.2f} m")
        _slider_row(sliders_frame, "Rows per strip",
                    self._gd_rows_var, 1, 5,
                    lambda v: f"{int(round(float(v)))} row(s)")

        # ── Sequence text box ──────────────────────────────────────────────────
        seq_frame = ttk.LabelFrame(frame, text="Border Sequence  (one /Game/… path per line — cycles A-B-C-A-B-C)", padding=8)
        seq_frame.pack(fill="both", expand=True, pady=(0, 8))

        scroll = tk.Scrollbar(seq_frame)
        scroll.pack(side="right", fill="y")

        self._gd_sequence_text = tk.Text(
            seq_frame,
            height=8,
            bg="#1e1e1e",
            fg="#e0e0e0",
            insertbackground="#e0e0e0",
            font=("Consolas", 9),
            relief="flat",
            wrap="none",
            yscrollcommand=scroll.set,
        )
        self._gd_sequence_text.pack(fill="both", expand=True)
        scroll.config(command=self._gd_sequence_text.yview)

        # Populate from saved config
        existing_seq = gd.get("border_sequence", [])
        if existing_seq:
            self._gd_sequence_text.insert("1.0", "\n".join(existing_seq))

        # ── Help text ──────────────────────────────────────────────────────────
        ttk.Label(
            frame,
            text=(
                "Tip: In UE Content Browser, right-click an asset → Copy Reference.\n"
                "Paste here (one per line).  Remove the leading 'StaticMesh ' word if present.\n"
                "Example:  /Game/Plants/SM_Boxwood_wfypfa3ha_Var3_lod1"
            ),
            foreground="#888888",
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))


# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = SettingsApp()
    app.mainloop()
