"""Point 1 — the Tkinter graphical editor, plus panels that drive Point 2
(translation) and Point 3 (testing / interleaving enumeration).

Run via ``main.py`` (which needs a Python built with Tk, e.g. macOS system
``/usr/bin/python3``).

Layout
------
    +------------------------------------------------------------------+
    | menubar:  File | Threads | Help                                  |
    +-----------+------------------------------+-----------------------+
    | threads   |  toolbar (block tools)       |  notebook:            |
    | listbox   |  +------------------------+  |   - Translate         |
    | [+][-]    |  |   flowchart canvas     |  |   - Testing           |
    | [rename]  |  |   (scrollable)         |  |                       |
    +-----------+------------------------------+-----------------------+
    | status bar                                                       |
    +------------------------------------------------------------------+
"""
from __future__ import annotations

import os
from typing import List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from . import model as M
from . import tester as T
from .interpreter import Engine
from .translator import translate


# --- appearance -------------------------------------------------------------
COLORS = {
    M.START: "#bff7c0",
    M.END:   "#f7bcbc",
    M.ASSIGN: "#bcd7f7",
    M.INPUT:  "#f7eebc",
    M.PRINT:  "#f7d7bc",
    M.COND:   "#e3bcf7",
}
SELECT_OUTLINE = "#1565c0"
PENDING_OUTLINE = "#ff8f00"


def clip_to_box(fx, fy, cx, cy, hw, hh):
    """Point on the border of the box centred at (cx,cy) with half-extents
    (hw,hh), in the direction of (fx,fy)."""
    dx, dy = fx - cx, fy - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = hw / abs(dx) if dx != 0 else float("inf")
    sy = hh / abs(dy) if dy != 0 else float("inf")
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def dist_to_segment(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    qx, qy = x1 + t * dx, y1 + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


# ============================================================================
# Block property dialog
# ============================================================================
class BlockDialog(tk.Toplevel):
    """Modal editor for one block's fields."""

    def __init__(self, parent, block: M.Block):
        super().__init__(parent)
        self.title("Edit block: " + block.kind)
        self.block = block
        self.result = False
        self.transient(parent)
        self.resizable(False, False)
        self._build()
        self.grab_set()
        self.wait_window(self)

    def _build(self):
        b = self.block
        frm = ttk.Frame(self, padding=12)
        frm.grid(sticky="nsew")
        row = 0

        if b.kind in (M.START, M.END):
            ttk.Label(frm, text="{} block has no parameters.".format(b.kind.upper())
                      ).grid(row=row, column=0, columnspan=3, pady=8)
            row += 1

        if b.kind == M.ASSIGN:
            ttk.Label(frm, text="Destination V:").grid(row=row, column=0, sticky="e")
            self.v_target = tk.StringVar(value=b.target)
            ttk.Entry(frm, textvariable=self.v_target, width=14).grid(row=row, column=1, columnspan=2, sticky="w")
            row += 1
            self.v_srckind = tk.StringVar(value=b.source_kind)
            ttk.Label(frm, text="Source:").grid(row=row, column=0, sticky="e")
            ttk.Radiobutton(frm, text="variable", value=M.SRC_VAR,
                            variable=self.v_srckind).grid(row=row, column=1, sticky="w")
            ttk.Radiobutton(frm, text="constant", value=M.SRC_CONST,
                            variable=self.v_srckind).grid(row=row, column=2, sticky="w")
            row += 1
            ttk.Label(frm, text="Source variable V2:").grid(row=row, column=0, sticky="e")
            self.v_srcvar = tk.StringVar(value=b.source_var)
            ttk.Entry(frm, textvariable=self.v_srcvar, width=14).grid(row=row, column=1, columnspan=2, sticky="w")
            row += 1
            ttk.Label(frm, text="Constant C (0..2^31-1):").grid(row=row, column=0, sticky="e")
            self.v_srcconst = tk.StringVar(value=str(b.source_const))
            ttk.Entry(frm, textvariable=self.v_srcconst, width=14).grid(row=row, column=1, columnspan=2, sticky="w")
            row += 1

        if b.kind in (M.INPUT, M.PRINT):
            ttk.Label(frm, text="Variable V:").grid(row=row, column=0, sticky="e")
            self.v_var = tk.StringVar(value=b.var)
            ttk.Entry(frm, textvariable=self.v_var, width=14).grid(row=row, column=1, columnspan=2, sticky="w")
            row += 1

        if b.kind == M.COND:
            ttk.Label(frm, text="Variable V:").grid(row=row, column=0, sticky="e")
            self.v_var = tk.StringVar(value=b.var)
            ttk.Entry(frm, textvariable=self.v_var, width=14).grid(row=row, column=1, columnspan=2, sticky="w")
            row += 1
            ttk.Label(frm, text="Comparison:").grid(row=row, column=0, sticky="e")
            self.v_cmp = tk.StringVar(value=b.cmp)
            ttk.Radiobutton(frm, text="==", value=M.CMP_EQ, variable=self.v_cmp).grid(row=row, column=1, sticky="w")
            ttk.Radiobutton(frm, text="<", value=M.CMP_LT, variable=self.v_cmp).grid(row=row, column=2, sticky="w")
            row += 1
            ttk.Label(frm, text="Constant C (0..2^31-1):").grid(row=row, column=0, sticky="e")
            self.v_const = tk.StringVar(value=str(b.const))
            ttk.Entry(frm, textvariable=self.v_const, width=14).grid(row=row, column=1, columnspan=2, sticky="w")
            row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=3, pady=(12, 0))
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _parse_const(self, s):
        v = int(s)
        if not M.is_valid_const(v):
            raise ValueError("constant must be in 0..2^31-1")
        return v

    def _ok(self):
        b = self.block
        try:
            if b.kind == M.ASSIGN:
                if not M.is_valid_var_name(self.v_target.get().strip()):
                    raise ValueError("invalid destination variable name")
                b.target = self.v_target.get().strip()
                b.source_kind = self.v_srckind.get()
                if b.source_kind == M.SRC_VAR:
                    if not M.is_valid_var_name(self.v_srcvar.get().strip()):
                        raise ValueError("invalid source variable name")
                    b.source_var = self.v_srcvar.get().strip()
                else:
                    b.source_const = self._parse_const(self.v_srcconst.get().strip())
            elif b.kind in (M.INPUT, M.PRINT):
                if not M.is_valid_var_name(self.v_var.get().strip()):
                    raise ValueError("invalid variable name")
                b.var = self.v_var.get().strip()
            elif b.kind == M.COND:
                if not M.is_valid_var_name(self.v_var.get().strip()):
                    raise ValueError("invalid variable name")
                b.var = self.v_var.get().strip()
                b.cmp = self.v_cmp.get()
                b.const = self._parse_const(self.v_const.get().strip())
        except ValueError as e:
            messagebox.showerror("Invalid value", str(e), parent=self)
            return
        self.result = True
        self.destroy()


# ============================================================================
# Test-case dialog
# ============================================================================
class TestCaseDialog(tk.Toplevel):
    def __init__(self, parent, tc: T.TestCase):
        super().__init__(parent)
        self.title("Test case")
        self.tc = tc
        self.result = False
        self.transient(parent)
        frm = ttk.Frame(self, padding=12)
        frm.grid(sticky="nsew")
        ttk.Label(frm, text="Name:").grid(row=0, column=0, sticky="e")
        self.v_name = tk.StringVar(value=tc.name)
        ttk.Entry(frm, textvariable=self.v_name, width=30).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(frm, text="Input (stdin, ints):").grid(row=1, column=0, sticky="ne")
        self.t_in = tk.Text(frm, width=30, height=3)
        self.t_in.insert("1.0", " ".join(str(x) for x in tc.input_tokens))
        self.t_in.grid(row=1, column=1, pady=2)
        ttk.Label(frm, text="Expected output (ints):").grid(row=2, column=0, sticky="ne")
        self.t_out = tk.Text(frm, width=30, height=4)
        self.t_out.insert("1.0", "\n".join(str(x) for x in tc.expected_output))
        self.t_out.grid(row=2, column=1, pady=2)
        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        try:
            inp = T.parse_int_tokens(self.t_in.get("1.0", "end"))
            outp = T.parse_int_tokens(self.t_out.get("1.0", "end"))
            T.validate_token_range(inp, "input value")
            T.validate_token_range(outp, "expected output value")
        except ValueError as e:
            messagebox.showerror("Invalid", "Inputs/outputs must be integers in 0..2³¹-1.\n" + str(e), parent=self)
            return
        self.tc.name = self.v_name.get().strip() or "test"
        self.tc.input_tokens = inp
        self.tc.expected_output = outp
        self.result = True
        self.destroy()


# ============================================================================
# Flowchart canvas
# ============================================================================
class FlowchartView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.fc: Optional[M.Flowchart] = None
        self.selected: Optional[int] = None
        self.edge_src: Optional[int] = None
        self._hits = []           # (block_id, cx, cy, hw, hh)
        self._drag = None

        self.canvas = tk.Canvas(self, background="white", width=560, height=560,
                                scrollregion=(0, 0, 2000, 2000))
        hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-2>", self._on_right)
        self.canvas.bind("<Button-3>", self._on_right)

    # ---- public ----------------------------------------------------------
    def set_flowchart(self, fc: Optional[M.Flowchart]):
        self.fc = fc
        self.selected = None
        self.edge_src = None
        self.redraw()

    def delete_selected(self):
        if self.fc is None or self.selected is None:
            return
        self.fc.remove_block(self.selected)
        self.selected = None
        self.app.touch()
        self.redraw()

    # ---- geometry ---------------------------------------------------------
    def _size(self, b: M.Block):
        label = b.label()
        hw = max(45, len(label) * 4 + 18)
        if b.kind in (M.START, M.END):
            return hw, 22
        if b.kind == M.COND:
            return hw + 16, 30
        return hw, 24

    def _hit_block(self, x, y):
        for bid, cx, cy, hw, hh in reversed(self._hits):
            if abs(x - cx) <= hw and abs(y - cy) <= hh:
                return bid
        return None

    # ---- rendering --------------------------------------------------------
    def redraw(self):
        c = self.canvas
        c.delete("all")
        self._hits = []
        if self.fc is None:
            return

        # edges first
        for e in self.fc.edges:
            self._draw_edge(e)

        # blocks on top
        maxx = maxy = 0
        for b in self.fc.blocks.values():
            hw, hh = self._size(b)
            self._hits.append((b.id, b.x, b.y, hw, hh))
            self._draw_block(b, hw, hh)
            maxx = max(maxx, b.x + hw)
            maxy = max(maxy, b.y + hh)
        c.configure(scrollregion=(0, 0, max(800, maxx + 120), max(600, maxy + 120)))

    def _draw_block(self, b: M.Block, hw, hh):
        c = self.canvas
        x, y = b.x, b.y
        fill = COLORS.get(b.kind, "#eeeeee")
        outline = "black"
        width = 1
        if b.id == self.selected:
            outline, width = SELECT_OUTLINE, 3
        if b.id == self.edge_src:
            outline, width = PENDING_OUTLINE, 3

        if b.kind in (M.START, M.END):
            c.create_oval(x - hw, y - hh, x + hw, y + hh, fill=fill, outline=outline, width=width)
        elif b.kind == M.COND:
            c.create_polygon(x, y - hh, x + hw, y, x, y + hh, x - hw, y,
                             fill=fill, outline=outline, width=width)
        elif b.kind in (M.INPUT, M.PRINT):
            sk = 12
            c.create_polygon(x - hw + sk, y - hh, x + hw, y - hh, x + hw - sk, y + hh,
                             x - hw, y + hh, fill=fill, outline=outline, width=width)
        else:  # ASSIGN
            c.create_rectangle(x - hw, y - hh, x + hw, y + hh, fill=fill, outline=outline, width=width)
        c.create_text(x, y, text=b.label(), font=("TkDefaultFont", 9))

    def _draw_edge(self, e: M.Edge):
        if self.fc is None:
            return
        src = self.fc.blocks.get(e.src)
        dst = self.fc.blocks.get(e.dst)
        if src is None or dst is None:
            return
        c = self.canvas
        shw, shh = self._size(src)
        dhw, dhh = self._size(dst)
        if e.src == e.dst:  # self-loop
            pts = self._self_loop_points(src)
            flat = [coord for p in pts for coord in p]
            c.create_line(*flat, smooth=True, arrow="last", fill="#555")
            if e.branch is not None:
                c.create_text(pts[1][0] - 8, pts[1][1] + 8,
                              text="T" if e.branch else "F", fill="#b00")
            return
        sx, sy = clip_to_box(dst.x, dst.y, src.x, src.y, shw, shh)
        ex, ey = clip_to_box(src.x, src.y, dst.x, dst.y, dhw, dhh)
        color = "#555"
        c.create_line(sx, sy, ex, ey, arrow="last", fill=color, width=1.5)
        if e.branch is not None:
            mx, my = sx + (ex - sx) * 0.18, sy + (ey - sy) * 0.18
            c.create_text(mx, my, text="T" if e.branch else "F",
                          fill="#0a7d00" if e.branch else "#b00",
                          font=("TkDefaultFont", 9, "bold"))

    # ---- events -----------------------------------------------------------
    def _cv(self, event):
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _on_click(self, event):
        if self.fc is None:
            return
        x, y = self._cv(event)
        mode = self.app.mode.get()
        bid = self._hit_block(x, y)

        if mode == "select":
            self.selected = bid
            self._drag = (bid, x, y) if bid is not None else None
            self.redraw()
        elif mode == "edge":
            if bid is None:
                self.edge_src = None
                self.redraw()
                return
            if self.edge_src is None:
                self.edge_src = bid
            else:
                self._make_edge(self.edge_src, bid)
                self.edge_src = None
            self.redraw()
        elif mode == "delete":
            if bid is not None:
                self.fc.remove_block(bid)
                if self.edge_src == bid:
                    self.edge_src = None
                self.app.touch()
            else:
                self._delete_edge_near(x, y)
            self.selected = None
            self.redraw()
        else:  # an add-block mode
            self._add_block(mode, x, y)

    def _on_drag(self, event):
        if self.fc is None or self.app.mode.get() != "select" or self._drag is None:
            return
        bid, _, _ = self._drag
        if bid is None:
            return
        x, y = self._cv(event)
        b = self.fc.blocks.get(bid)
        if b:
            b.x, b.y = max(40, x), max(30, y)
            self.redraw()

    def _on_release(self, event):
        if self._drag is not None:
            self.app.touch()
        self._drag = None

    def _on_double(self, event):
        if self.fc is None:
            return
        x, y = self._cv(event)
        bid = self._hit_block(x, y)
        if bid is not None:
            self._edit_block(bid)

    def _on_right(self, event):
        if self.fc is None:
            return
        x, y = self._cv(event)
        bid = self._hit_block(x, y)
        if bid is None:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Edit...", command=lambda: self._edit_block(bid))
        menu.add_command(label="Clear outgoing edges",
                         command=lambda: self._clear_out(bid))
        menu.add_separator()
        menu.add_command(label="Delete block", command=lambda: self._del_block(bid))
        menu.tk_popup(event.x_root, event.y_root)

    # ---- helpers ----------------------------------------------------------
    def _add_block(self, kind, x, y):
        if len(self.fc.blocks) >= M.MAX_BLOCKS:
            messagebox.showwarning("Limit", "A flowchart may have at most {} blocks.".format(M.MAX_BLOCKS))
            return
        if kind == M.START and self.fc.start_block() is not None:
            messagebox.showwarning("START", "This flowchart already has a START block.")
            return
        b = self.fc.new_block(kind, x=x, y=y)
        if kind not in (M.START, M.END):
            dlg = BlockDialog(self, b)
            if not dlg.result:        # cancelled -> revert, leave dirty unchanged
                self.fc.remove_block(b.id)
                self.redraw()
                return
        self.app.touch()              # only mark dirty once a block is committed
        self.selected = b.id
        self.redraw()

    def _edit_block(self, bid):
        b = self.fc.blocks.get(bid)
        if b is None or b.kind in (M.START, M.END):
            if b and b.kind in (M.START, M.END):
                messagebox.showinfo("Block", "{} has no parameters.".format(b.kind.upper()))
            return
        if BlockDialog(self, b).result:
            self.app.touch()
            self.redraw()

    def _del_block(self, bid):
        self.fc.remove_block(bid)
        if self.selected == bid:
            self.selected = None
        if self.edge_src == bid:        # don't leave a dangling edge source
            self.edge_src = None
        self.app.touch()
        self.redraw()

    def _clear_out(self, bid):
        self.fc.edges = [e for e in self.fc.edges if e.src != bid]
        self.app.touch()
        self.redraw()

    def _make_edge(self, src, dst):
        if src not in self.fc.blocks or dst not in self.fc.blocks:
            return                       # source/target was deleted meanwhile
        sb = self.fc.blocks[src]
        branch = None
        if sb.kind == M.END:
            messagebox.showwarning("Edge", "END has no outgoing edges.")
            return
        if sb.kind == M.COND:
            ans = messagebox.askquestion(
                "Branch", "Connect the TRUE branch?\n(Yes = TRUE, No = FALSE)")
            branch = (ans == "yes")
        self.fc.add_edge(src, dst, branch=branch)
        self.app.touch()

    def _self_loop_points(self, s):
        """The polyline used to draw (and now hit-test) a self-loop edge —
        must match _draw_edge."""
        shw, shh = self._size(s)
        return [(s.x + shw, s.y), (s.x + shw + 40, s.y - shh - 20),
                (s.x, s.y - shh - 30), (s.x, s.y - shh)]

    def _delete_edge_near(self, x, y):
        best = None
        bestd = 10.0
        for e in self.fc.edges:
            s = self.fc.blocks.get(e.src)
            d = self.fc.blocks.get(e.dst)
            if not s or not d:
                continue
            if e.src == e.dst:           # self-loop: distance to its drawn polyline
                pts = self._self_loop_points(s)
                dd = min(dist_to_segment(x, y, a[0], a[1], b[0], b[1])
                         for a, b in zip(pts, pts[1:]))
            else:
                shw, shh = self._size(s)
                dhw, dhh = self._size(d)
                sx, sy = clip_to_box(d.x, d.y, s.x, s.y, shw, shh)
                ex, ey = clip_to_box(s.x, s.y, d.x, d.y, dhw, dhh)
                dd = dist_to_segment(x, y, sx, sy, ex, ey)
            if dd < bestd:
                bestd, best = dd, e
        if best is not None:
            self.fc.edges.remove(best)
            self.app.touch()


# ============================================================================
# Main application
# ============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("graph2Thread")
        self.geometry("1180x740")

        self.project = M.Project(flowcharts=[M.Flowchart(name="thread_0")])
        self.path: Optional[str] = None
        self.dirty = False
        self.testset = T.TestSet()
        self.mode = tk.StringVar(value="select")

        # enumeration state
        self._enum: Optional[T.Enumerator] = None
        self._enum_running = False

        self._build_menu()
        self._build_body()
        self._refresh_threads()
        self._select_thread(0)
        self.protocol("WM_DELETE_WINDOW", self._on_quit)
        self.bind("<Delete>", lambda e: self.view.delete_selected())
        self.bind("<BackSpace>", lambda e: self.view.delete_selected())

    # ---- menus ------------------------------------------------------------
    def _build_menu(self):
        mbar = tk.Menu(self)
        filem = tk.Menu(mbar, tearoff=0)
        filem.add_command(label="New", command=self.new_project, accelerator="Ctrl+N")
        filem.add_command(label="Open...", command=self.open_project, accelerator="Ctrl+O")
        filem.add_command(label="Save", command=self.save_project, accelerator="Ctrl+S")
        filem.add_command(label="Save As...", command=self.save_project_as)
        filem.add_separator()
        filem.add_command(label="Export Python...", command=self.export_python)
        filem.add_separator()
        filem.add_command(label="Exit", command=self._on_quit)
        mbar.add_cascade(label="File", menu=filem)

        thm = tk.Menu(mbar, tearoff=0)
        thm.add_command(label="Add thread", command=self.add_thread)
        thm.add_command(label="Remove current thread", command=self.remove_thread)
        thm.add_command(label="Rename current thread", command=self.rename_thread)
        mbar.add_cascade(label="Threads", menu=thm)

        helpm = tk.Menu(mbar, tearoff=0)
        helpm.add_command(label="Quick help", command=self._help)
        mbar.add_cascade(label="Help", menu=helpm)
        self.config(menu=mbar)

        self.bind("<Control-n>", lambda e: self.new_project())
        self.bind("<Control-o>", lambda e: self.open_project())
        self.bind("<Control-s>", lambda e: self.save_project())

    # ---- body -------------------------------------------------------------
    def _build_body(self):
        # toolbar
        tb = ttk.Frame(self, padding=(6, 4))
        tb.pack(side="top", fill="x")
        ttk.Label(tb, text="Tool:").pack(side="left")
        tools = [("Select/Move", "select"), ("START", M.START), ("END", M.END),
                 ("Assign", M.ASSIGN), ("Input", M.INPUT), ("Print", M.PRINT),
                 ("Branch", M.COND), ("Edge", "edge"), ("Delete", "delete")]
        for text, val in tools:
            ttk.Radiobutton(tb, text=text, value=val, variable=self.mode,
                            command=self._mode_changed).pack(side="left", padx=1)

        # main panes
        main = ttk.Frame(self)
        main.pack(side="top", fill="both", expand=True)

        # left: threads
        left = ttk.Frame(main, padding=4)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Threads (flowcharts):").pack(anchor="w")
        self.thread_list = tk.Listbox(left, width=22, height=20, exportselection=False)
        self.thread_list.pack(fill="y", expand=True)
        self.thread_list.bind("<<ListboxSelect>>", self._on_thread_select)
        bb = ttk.Frame(left)
        bb.pack(fill="x", pady=4)
        ttk.Button(bb, text="+", width=3, command=self.add_thread).pack(side="left")
        ttk.Button(bb, text="-", width=3, command=self.remove_thread).pack(side="left")
        ttk.Button(bb, text="Rename", command=self.rename_thread).pack(side="left")

        # center: canvas
        self.view = FlowchartView(main, self)
        self.view.pack(side="left", fill="both", expand=True)

        # right: notebook
        nb = ttk.Notebook(main, width=360)
        nb.pack(side="left", fill="both")
        self._build_translate_tab(nb)
        self._build_test_tab(nb)

        # status bar
        self.status = tk.StringVar(value="Ready.")
        sb = ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w", padding=3)
        sb.pack(side="bottom", fill="x")

    def _build_translate_tab(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Translate")
        ttk.Label(f, text="Point 2 — generate multithreaded Python:").pack(anchor="w")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Generate", command=self.generate_code).pack(side="left")
        ttk.Button(bar, text="Save .py...", command=self.export_python).pack(side="left", padx=4)
        self.code_text = tk.Text(f, wrap="none", font=("TkFixedFont", 9))
        self.code_text.pack(fill="both", expand=True)

    def _build_test_tab(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Testing")

        ttk.Label(f, text="Point 3 — test set:").pack(anchor="w")
        self.test_list = tk.Listbox(f, height=6, exportselection=False)
        self.test_list.pack(fill="x")
        tb = ttk.Frame(f)
        tb.pack(fill="x", pady=2)
        ttk.Button(tb, text="Add", command=self.add_test).pack(side="left")
        ttk.Button(tb, text="Edit", command=self.edit_test).pack(side="left")
        ttk.Button(tb, text="Del", command=self.del_test).pack(side="left")
        ttk.Button(tb, text="Load...", command=self.load_tests).pack(side="left", padx=(8, 0))
        ttk.Button(tb, text="Save...", command=self.save_tests).pack(side="left")

        opts = ttk.Frame(f)
        opts.pack(fill="x", pady=4)
        ttk.Label(opts, text="op-bound:").pack(side="left")
        self.bound_var = tk.IntVar(value=T.DEFAULT_BOUND)
        ttk.Spinbox(opts, from_=1, to=100000, textvariable=self.bound_var, width=8).pack(side="left", padx=(2, 10))

        ttk.Button(f, text="Quick check (one interleaving)", command=self.quick_check).pack(fill="x", pady=1)
        ttk.Button(f, text="Analyze determinism", command=self.analyze_det).pack(fill="x", pady=1)

        enum = ttk.LabelFrame(f, text="Enumerate interleavings (no repeats)", padding=4)
        enum.pack(fill="x", pady=6)
        row = ttk.Frame(enum)
        row.pack(fill="x")
        ttk.Button(row, text="Start", command=self.start_enum).pack(side="left")
        ttk.Button(row, text="Stop", command=self.stop_enum).pack(side="left", padx=4)
        kr = ttk.Frame(enum)
        kr.pack(fill="x", pady=(6, 0))
        ttk.Label(kr, text="K (1..20):").pack(side="left")
        self.k_var = tk.IntVar(value=10)
        ttk.Spinbox(kr, from_=1, to=20, textvariable=self.k_var, width=5).pack(side="left", padx=2)
        ttk.Button(kr, text="Show % verified (≤K ops)", command=self.show_percentage).pack(side="left", padx=4)

        ttk.Label(f, text="Results:").pack(anchor="w")
        self.result_text = tk.Text(f, height=12, wrap="word", font=("TkFixedFont", 9))
        self.result_text.pack(fill="both", expand=True)

    # ---- thread management ------------------------------------------------
    def _refresh_threads(self):
        self.thread_list.delete(0, "end")
        for i, fc in enumerate(self.project.flowcharts):
            self.thread_list.insert("end", "{}: {}".format(i, fc.name))

    def _select_thread(self, idx):
        if not self.project.flowcharts:
            self.view.set_flowchart(None)
            return
        idx = max(0, min(idx, len(self.project.flowcharts) - 1))
        self.thread_list.selection_clear(0, "end")
        self.thread_list.selection_set(idx)
        self.current_index = idx
        self.view.set_flowchart(self.project.flowcharts[idx])
        self._set_status("Editing thread {} ('{}').".format(idx, self.project.flowcharts[idx].name))

    def _on_thread_select(self, event):
        sel = self.thread_list.curselection()
        if sel:
            self._select_thread(sel[0])

    def add_thread(self):
        if len(self.project.flowcharts) >= M.MAX_THREADS:
            messagebox.showwarning("Limit", "At most {} threads.".format(M.MAX_THREADS))
            return
        n = len(self.project.flowcharts)
        self.project.flowcharts.append(M.Flowchart(name="thread_{}".format(n)))
        self.touch()
        self._refresh_threads()
        self._select_thread(n)

    def remove_thread(self):
        if len(self.project.flowcharts) <= 1:
            messagebox.showwarning("Threads", "A project needs at least one thread.")
            return
        idx = self.current_index
        del self.project.flowcharts[idx]
        self.touch()
        self._refresh_threads()
        self._select_thread(max(0, idx - 1))

    def rename_thread(self):
        idx = self.current_index
        from tkinter import simpledialog
        name = simpledialog.askstring("Rename", "Thread name:",
                                      initialvalue=self.project.flowcharts[idx].name, parent=self)
        if name:
            self.project.flowcharts[idx].name = name
            self.touch()
            self._refresh_threads()
            self._select_thread(idx)

    # ---- file ops ---------------------------------------------------------
    def new_project(self):
        if not self._confirm_discard():
            return
        self.project = M.Project(flowcharts=[M.Flowchart(name="thread_0")])
        self.path = None
        self.dirty = False
        self._refresh_threads()
        self._select_thread(0)
        self._update_title()

    def open_project(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(filetypes=[("graph2Thread project", "*.json"), ("All", "*.*")])
        if not path:
            return
        try:
            import json as _json
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
            self.project = M.Project.from_json(raw)
            data = _json.loads(raw)
            if "tests" in data:
                self.testset = T.TestSet.from_json(
                    _json.dumps({"version": 1, "tests": data["tests"]}))
            else:
                self.testset = T.TestSet()
        except Exception as e:
            messagebox.showerror("Open failed", str(e))
            return
        if not self.project.flowcharts:
            self.project.flowcharts.append(M.Flowchart(name="thread_0"))
        self.path = path
        self.dirty = False
        self._refresh_threads()
        self._select_thread(0)
        self._refresh_tests()
        self._update_title()
        self._set_status("Opened " + path)

    def save_project(self):
        if self.path is None:
            return self.save_project_as()
        try:
            import json as _json
            data = _json.loads(self.project.to_json())
            data["tests"] = _json.loads(self.testset.to_json()).get("tests", [])
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(_json.dumps(data, indent=2))
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return
        self.dirty = False
        self._update_title()
        self._set_status("Saved " + self.path)

    def save_project_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("graph2Thread project", "*.json")])
        if not path:
            return
        self.path = path
        self.save_project()

    def export_python(self):
        errs = M.validate_project(self.project)
        if errs:
            messagebox.showerror("Cannot translate", "Fix these first:\n\n" + "\n".join(errs))
            return
        warns = M.lint_project(self.project)
        if warns and not messagebox.askokcancel(
                "Warnings", "\n".join(warns) + "\n\nExport anyway?"):
            return
        path = filedialog.asksaveasfilename(defaultextension=".py",
                                            filetypes=[("Python", "*.py")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(translate(self.project))
        self._set_status("Exported " + path)

    # ---- translate tab ----------------------------------------------------
    def generate_code(self):
        errs = M.validate_project(self.project)
        self.code_text.delete("1.0", "end")
        if errs:
            self.code_text.insert("1.0", "# Validation errors:\n# " + "\n# ".join(errs))
            self._set_status("Validation failed.")
            return
        header = ""
        warns = M.lint_project(self.project)
        if warns:
            header = "# Warnings:\n# " + "\n# ".join(warns) + "\n\n"
        self.code_text.insert("1.0", header + translate(self.project))
        self._set_status("Generated Python for {} thread(s).{}".format(
            len(self.project.flowcharts), "  (with warnings)" if warns else ""))

    # ---- test tab ---------------------------------------------------------
    def _refresh_tests(self):
        self.test_list.delete(0, "end")
        for tc in self.testset.cases:
            self.test_list.insert("end", "{}  in={} exp={}".format(
                tc.name, tc.input_tokens, tc.expected_output))

    def _selected_test(self) -> Optional[T.TestCase]:
        sel = self.test_list.curselection()
        if not sel:
            messagebox.showinfo("Test", "Select a test case first.")
            return None
        return self.testset.cases[sel[0]]

    def add_test(self):
        tc = T.TestCase(name="test {}".format(len(self.testset.cases) + 1))
        if TestCaseDialog(self, tc).result:
            self.testset.cases.append(tc)
            self._refresh_tests()

    def edit_test(self):
        tc = self._selected_test()
        if tc and TestCaseDialog(self, tc).result:
            self._refresh_tests()

    def del_test(self):
        sel = self.test_list.curselection()
        if sel:
            del self.testset.cases[sel[0]]
            self._refresh_tests()

    def load_tests(self):
        path = filedialog.askopenfilename(filetypes=[("Test set", "*.json"), ("All", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self.testset = T.TestSet.from_json(fh.read())
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return
        self._refresh_tests()

    def save_tests(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("Test set", "*.json")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.testset.to_json())

    def _validate_or_warn(self) -> bool:
        errs = M.validate_project(self.project)
        if errs:
            messagebox.showerror("Invalid project", "\n".join(errs))
            return False
        for w in M.lint_project(self.project):
            self._log("[warning] " + w)
        return True

    def _log(self, text):
        self.result_text.insert("end", text + "\n")
        self.result_text.see("end")

    def quick_check(self):
        tc = self._selected_test()
        if tc is None or not self._validate_or_warn():
            return
        eng = Engine(self.project, input_tokens=tc.input_tokens)
        v = T.first_variant(eng, tc.expected_output, bound=self.bound_var.get())
        ok = v.klass == T.COMPLETE and v.passed
        self._log("[quick] '{}': {} class={} output={} (expected {})".format(
            tc.name, "PASS" if ok else "FAIL", v.klass, list(v.output), tc.expected_output))

    def analyze_det(self):
        tc = self._selected_test()
        if not self._validate_or_warn():
            return
        inp = tc.input_tokens if tc else []
        eng = Engine(self.project, input_tokens=inp)
        rep = T.analyze_determinism(eng, bound=self.bound_var.get())
        self._log("[determinism] verdict={} distinct_outputs={} max_branching={} bound_hit={}{}".format(
            rep.verdict, rep.distinct_output_count, rep.max_branching, rep.hit_bound,
            " (analysis truncated)" if rep.truncated else ""))
        for o in rep.distinct_outputs:
            self._log("    output: {}".format(list(o)))

    def start_enum(self):
        tc = self._selected_test()
        if tc is None or not self._validate_or_warn():
            return
        if self._enum_running:
            messagebox.showinfo("Enumeration", "Already running. Stop first.")
            return
        eng = Engine(self.project, input_tokens=tc.input_tokens)
        self._enum = T.Enumerator(eng, tc.expected_output, bound=self.bound_var.get())
        self._enum_tc = tc
        self._enum_running = True
        self._log("[enumerate] started for '{}' (expected {}). Press Stop anytime, "
                  "then choose K.".format(tc.name, tc.expected_output))
        self.after(1, self._enum_tick)

    def _enum_tick(self):
        if not self._enum_running or self._enum is None:
            return
        for _ in range(500):       # batch per tick keeps UI responsive
            v = self._enum.next()
            if v is None:
                self._enum_running = False
                break
        self._set_status(self._enum_stats())
        if self._enum_running:
            self.after(1, self._enum_tick)
        else:
            self._log("[enumerate] exhausted. " + self._enum_stats())

    def _enum_stats(self):
        s = self._enum.summary()
        return ("complete={complete} passed={passed} failed={failed} "
                "deadlock={deadlock} over_bound={over_bound} distinct_outputs={n}"
                .format(n=len(s["distinct_outputs"]), **s))

    def stop_enum(self):
        if self._enum_running:
            self._enum_running = False
            self._log("[enumerate] stopped. " + self._enum_stats())
        else:
            self._log("[enumerate] (not running) " +
                      (self._enum_stats() if self._enum else "no enumeration yet"))

    def show_percentage(self):
        if self._enum is None:
            messagebox.showinfo("K%", "Start an enumeration first.")
            return
        k = self.k_var.get()
        if not (1 <= k <= 20):
            messagebox.showwarning("K", "K must be 1..20.")
            return
        r = self._enum.percentage_for_K(k)
        if r["percent"] is None:
            pct = "N/A (no complete variants of ≤{} operations)".format(k)
        else:
            pct = "{:.4f}%".format(r["percent"])
        self._log("[K={}] verified {} / {} complete variants with ≤K ops  ->  {}"
                  .format(k, r["numerator"], r["denominator"], pct))
        self._log("        (deadlocks seen={}, over-bound seen={}, passed={}, failed={}, "
                  "exhausted={})".format(r["deadlocks_seen"], r["over_bound_seen"],
                                         r["passed"], r["failed"], r["exhausted"]))

    # ---- misc -------------------------------------------------------------
    def _mode_changed(self):
        self.view.edge_src = None
        self.view.redraw()
        hints = {
            "select": "Select/Move: click a block to select, drag to move, Delete to remove.",
            "edge": "Edge: click source block, then target block. For a Branch, choose TRUE/FALSE.",
            "delete": "Delete: click a block to delete it, or click near an edge to delete the edge.",
        }
        self._set_status(hints.get(self.mode.get(),
                                   "Click on the canvas to place a {} block.".format(self.mode.get().upper())))

    def touch(self):
        self.dirty = True
        self._update_title()

    def _update_title(self):
        name = self.path or "(unsaved)"
        self.title("graph2Thread - {}{}".format(name, " *" if self.dirty else ""))

    def _set_status(self, text):
        self.status.set(text)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", "Save changes first?")
        if ans is None:
            return False
        if ans:
            self.save_project()
        return True

    def _on_quit(self):
        if self._confirm_discard():
            self.destroy()

    def _help(self):
        messagebox.showinfo("graph2Thread - quick help",
            "1. Each thread is one flowchart (left list). Add blocks with the toolbar; "
            "use 'Edge' to connect them. Branch blocks need a TRUE and a FALSE edge.\n\n"
            "2. 'Translate' tab generates a runnable multithreaded Python program.\n\n"
            "3. 'Testing' tab: build a test set, then either quick-check one interleaving, "
            "analyze determinism, or enumerate all interleavings without repeats. While "
            "enumerating, press Stop, pick K (1..20), and 'Show % verified' to see the "
            "percentage of complete runs of ≤K operations checked so far.")


def run():
    App().mainloop()
