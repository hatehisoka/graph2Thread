#!/usr/bin/env python3
"""Generate example projects/test sets so the editor and CLI have something to
open.  Run:  python3 examples/make_examples.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from g2t import model as M
from g2t import tester as T


def chain(fc, blocks):
    for a, b in zip(blocks, blocks[1:]):
        fc.add_edge(a.id, b.id)


def laid_out(fc, xs=160):
    """Spread blocks vertically so they don't overlap in the editor."""
    for i, b in enumerate(sorted(fc.blocks.values(), key=lambda x: x.id)):
        b.x = xs
        b.y = 60 + i * 90
    return fc


def echo():
    fc = M.Flowchart(name="echo")
    s = fc.new_block(M.START)
    i = fc.new_block(M.INPUT, var="x")
    p = fc.new_block(M.PRINT, var="x")
    e = fc.new_block(M.END)
    chain(fc, [s, i, p, e])
    return M.Project(flowcharts=[laid_out(fc)])


def race_0_1():
    """Spec's canonical example: two threads independently print 0 and 1."""
    def t(name, var, const):
        fc = M.Flowchart(name=name)
        s = fc.new_block(M.START)
        a = fc.new_block(M.ASSIGN, target=var, source_kind=M.SRC_CONST, source_const=const)
        p = fc.new_block(M.PRINT, var=var)
        e = fc.new_block(M.END)
        chain(fc, [s, a, p, e])
        return laid_out(fc)
    return M.Project(flowcharts=[t("prints_0", "a", 0), t("prints_1", "b", 1)])


def shared_race():
    """Write-write race on a shared variable x, then each thread prints x."""
    def t(name, const):
        fc = M.Flowchart(name=name)
        s = fc.new_block(M.START)
        a = fc.new_block(M.ASSIGN, target="x", source_kind=M.SRC_CONST, source_const=const)
        p = fc.new_block(M.PRINT, var="x")
        e = fc.new_block(M.END)
        chain(fc, [s, a, p, e])
        return laid_out(fc)
    return M.Project(flowcharts=[t("writer_1", 1), t("writer_2", 2)])


def branch_demo():
    """Single thread: read x; if x<10 print 0 else print 1 (deterministic)."""
    fc = M.Flowchart(name="classify")
    s = fc.new_block(M.START)
    i = fc.new_block(M.INPUT, var="x")
    c = fc.new_block(M.COND, var="x", cmp=M.CMP_LT, const=10)
    lo = fc.new_block(M.ASSIGN, target="r", source_kind=M.SRC_CONST, source_const=0)
    hi = fc.new_block(M.ASSIGN, target="r", source_kind=M.SRC_CONST, source_const=1)
    p = fc.new_block(M.PRINT, var="r")
    e = fc.new_block(M.END)
    fc.add_edge(s.id, i.id)
    fc.add_edge(i.id, c.id)
    fc.add_edge(c.id, lo.id, branch=True)
    fc.add_edge(c.id, hi.id, branch=False)
    fc.add_edge(lo.id, p.id)
    fc.add_edge(hi.id, p.id)
    fc.add_edge(p.id, e.id)
    # manual layout (branch)
    s.x, s.y = 220, 50
    i.x, i.y = 220, 130
    c.x, c.y = 220, 220
    lo.x, lo.y = 110, 320
    hi.x, hi.y = 340, 320
    p.x, p.y = 220, 420
    e.x, e.y = 220, 500
    return M.Project(flowcharts=[fc])


def save(proj, name):
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(proj.to_json())
    print("wrote", path)


def save_ts(ts, name):
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ts.to_json())
    print("wrote", path)


if __name__ == "__main__":
    save(echo(), "echo.json")
    save(race_0_1(), "race_0_1.json")
    save(shared_race(), "shared_race.json")
    save(branch_demo(), "branch_demo.json")

    save_ts(T.TestSet(cases=[
        T.TestCase("five", [5], [5]),
        T.TestCase("zero", [0], [0]),
    ]), "echo_tests.json")

    save_ts(T.TestSet(cases=[
        T.TestCase("expects 0 then 1", [], [0, 1]),
    ]), "race_0_1_tests.json")

    save_ts(T.TestSet(cases=[
        T.TestCase("small -> 0", [3], [0]),
        T.TestCase("big -> 1", [42], [1]),
        T.TestCase("boundary 10 -> 1", [10], [1]),
    ]), "branch_demo_tests.json")
    print("done")
