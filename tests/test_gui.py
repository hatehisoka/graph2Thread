#!/usr/bin/env python3
"""Headless GUI smoke tests (no window shown, no mainloop).

Exercises the real Tkinter widgets: building the app, loading a project,
switching threads, drawing the canvas, generating code, driving an enumeration
through the GUI methods, and committing the modal dialogs via the event loop.

Run with a Tk-enabled interpreter:  python3 tests/test_gui.py
Skips cleanly if tkinter is unavailable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter  # noqa: F401
except Exception as ex:
    print("SKIP: tkinter unavailable ({}). Run with a Tk-enabled Python.".format(ex))
    sys.exit(0)

import g2t.editor as e
from g2t import model as M, tester as T

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
_fail = []


def check(name, cond, detail=""):
    print("  [{}] {}{}".format("PASS" if cond else "FAIL", name,
                               "" if cond else "  -- " + str(detail)))
    if not cond:
        _fail.append(name)


def main():
    try:
        app = e.App()
    except Exception as ex:
        print("SKIP: cannot create Tk root in this environment: {}".format(ex))
        return 0
    app.withdraw()

    # --- load project, switch threads, redraw ---
    with open(os.path.join(EX, "race_0_1.json")) as f:
        app.project = M.Project.from_json(f.read())
    app._refresh_threads()
    app._select_thread(0)
    check("two threads listed", app.thread_list.size() == 2, app.thread_list.get(0, "end"))
    app._select_thread(1)
    app.view.redraw()
    check("canvas drew items", len(app.view.canvas.find_all()) > 0)

    # --- Point 2: code generation in the widget ---
    app.generate_code()
    code = app.code_text.get("1.0", "end")
    check("generated threading code", "threading" in code and "def thread_0" in code)

    # --- Point 3: enumeration via GUI methods ---
    with open(os.path.join(EX, "race_0_1_tests.json")) as f:
        app.testset = T.TestSet.from_json(f.read())
    app._refresh_tests()
    app.test_list.selection_set(0)
    app.start_enum()
    while app._enum_running:
        app._enum_tick()
    s = app._enum.summary()
    check("enumeration found 70 complete", s["complete"] == 70, s)
    app.k_var.set(8)
    app.show_percentage()
    app.k_var.set(7)
    app.show_percentage()
    log = app.result_text.get("1.0", "end")
    check("K=8 shows 70/70 100%", "70 / 70" in log and "100.0000%" in log)
    check("K=7 shows N/A", "N/A" in log)

    # --- modal dialogs committed through the event loop ---
    fc = app.project.flowcharts[0]
    b = fc.new_block(M.ASSIGN, x=100, y=100)

    def close_block():
        for w in app.winfo_children():
            if isinstance(w, e.BlockDialog):
                w.v_target.set("x"); w.v_srckind.set(M.SRC_CONST)
                w.v_srcconst.set("42"); w._ok()
    app.after(40, close_block)
    dlg = e.BlockDialog(app, b)
    check("BlockDialog commits fields", dlg.result and b.label() == "x = 42", b.label())

    tc = T.TestCase(name="t")

    def close_test():
        for w in app.winfo_children():
            if isinstance(w, e.TestCaseDialog):
                w.v_name.set("demo")
                w.t_in.delete("1.0", "end"); w.t_in.insert("1.0", "3 4 5")
                w.t_out.delete("1.0", "end"); w.t_out.insert("1.0", "9")
                w._ok()
    app.after(40, close_test)
    e.TestCaseDialog(app, tc)
    check("TestCaseDialog parses ints", tc.input_tokens == [3, 4, 5] and tc.expected_output == [9])

    # --- regression: edge_src cleared when its block is deleted (no KeyError) ---
    fc2 = M.Flowchart(name="reg")
    a = fc2.new_block(M.START, x=100, y=100)
    b = fc2.new_block(M.END, x=100, y=200)
    app.project.flowcharts.append(fc2)
    app._refresh_threads()
    app._select_thread(len(app.project.flowcharts) - 1)
    app.view.edge_src = a.id
    app.view._del_block(a.id)
    check("edge_src cleared after deleting its block", app.view.edge_src is None)
    # completing an edge whose source is gone must not raise
    try:
        app.view._make_edge(a.id, b.id)
        no_crash = True
    except Exception:
        no_crash = False
    check("_make_edge with deleted source does not crash", no_crash)

    # --- regression: self-loop can be deleted via _delete_edge_near ---
    c = fc2.new_block(M.ASSIGN, x=300, y=300, target="x",
                      source_kind=M.SRC_CONST, source_const=0)
    fc2.add_edge(c.id, c.id)  # self-loop
    app.view.set_flowchart(fc2)
    pts = app.view._self_loop_points(c)
    px, py = pts[1]  # a point on the drawn loop
    had = any(ed.src == ed.dst for ed in fc2.edges)
    app.view._delete_edge_near(px, py)
    gone = not any(ed.src == ed.dst for ed in fc2.edges)
    check("self-loop deletable via Delete tool", had and gone)

    app.destroy()
    if _fail:
        print("FAILED:", ", ".join(_fail))
        return 1
    print("ALL GUI TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
