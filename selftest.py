#!/usr/bin/env python3
"""Headless correctness tests for the graph2Thread engine (no GUI needed).

Run:  python3 selftest.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from g2t import model as M
from g2t.interpreter import Engine, DONE, DEADLOCK, RUNNING
from g2t import tester as T
from g2t.translator import translate

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures = []


def check(name, cond, detail=""):
    print("  [{}] {}{}".format(PASS if cond else FAIL, name,
                               "" if cond else "  -- " + str(detail)))
    if not cond:
        _failures.append(name)


# --- flowchart builders ------------------------------------------------------
def chain(fc, blocks):
    """Connect a list of non-branching blocks in order (linear)."""
    for a, b in zip(blocks, blocks[1:]):
        fc.add_edge(a.id, b.id)


def print_const_thread(name, var, const):
    """START -> var=const -> PRINT var -> END."""
    fc = M.Flowchart(name=name)
    s = fc.new_block(M.START)
    a = fc.new_block(M.ASSIGN, target=var, source_kind=M.SRC_CONST, source_const=const)
    p = fc.new_block(M.PRINT, var=var)
    e = fc.new_block(M.END)
    chain(fc, [s, a, p, e])
    return fc


def echo_thread(name, var):
    """START -> INPUT var -> PRINT var -> END."""
    fc = M.Flowchart(name=name)
    s = fc.new_block(M.START)
    i = fc.new_block(M.INPUT, var=var)
    p = fc.new_block(M.PRINT, var=var)
    e = fc.new_block(M.END)
    chain(fc, [s, i, p, e])
    return fc


def infinite_loop_thread(name, var):
    """START -> var=0 -> [cond var<1]? true: var=0 (loop) ; false: END."""
    fc = M.Flowchart(name=name)
    s = fc.new_block(M.START)
    a = fc.new_block(M.ASSIGN, target=var, source_kind=M.SRC_CONST, source_const=0)
    c = fc.new_block(M.COND, var=var, cmp=M.CMP_LT, const=1)
    body = fc.new_block(M.ASSIGN, target=var, source_kind=M.SRC_CONST, source_const=0)
    e = fc.new_block(M.END)
    fc.add_edge(s.id, a.id)
    fc.add_edge(a.id, c.id)
    fc.add_edge(c.id, body.id, branch=True)
    fc.add_edge(body.id, c.id)               # cycle in the graph
    fc.add_edge(c.id, e.id, branch=False)
    return fc


# ============================================================================
print("\n== 1. validation ==")
p = M.Project(flowcharts=[echo_thread("t0", "x")])
check("valid echo project", M.validate_project(p) == [], M.validate_project(p))

bad = M.Project(flowcharts=[M.Flowchart(name="empty")])
check("empty flowchart flagged invalid", M.validate_project(bad) != [])


print("\n== 2. deterministic single thread (INPUT/PRINT) ==")
eng = Engine(p, input_tokens=[5])
v = T.first_variant(eng, expected_output=[5])
check("echo completes", v.klass == T.COMPLETE, v.klass)
check("echo output == [5]", v.output == (5,), v.output)
check("echo passes test", v.passed is True)
det = T.analyze_determinism(eng)
check("echo is deterministic", det.verdict == T.DETERMINISTIC, det.verdict)
check("echo single distinct output", det.distinct_output_count == 1)


print("\n== 3. classic nondeterministic (thread A prints 0, thread B prints 1) ==")
nd = M.Project(flowcharts=[print_const_thread("A", "a", 0),
                           print_const_thread("B", "b", 1)])
check("nd project valid", M.validate_project(nd) == [], M.validate_project(nd))
eng = Engine(nd, input_tokens=[])
det = T.analyze_determinism(eng)
check("nd is nondeterministic", det.verdict == T.NONDETERMINISTIC, det.verdict)
check("nd has 2 distinct outputs", det.distinct_output_count == 2, det.distinct_outputs)
check("nd outputs are (0,1) and (1,0)",
      set(det.distinct_outputs) == {(0, 1), (1, 0)}, det.distinct_outputs)

# enumerate everything, expecting output [0,1]
en = T.Enumerator(eng, expected_output=[0, 1])
en.run_all()
s = en.summary()
# both threads: 4 blocks each = 4 ops; complete run = 8 ops; #interleavings = C(8,4)=70
check("nd: 70 complete variants", s["complete"] == 70, s)
check("nd: enumeration exhausted", s["exhausted"] is True)
check("nd: no deadlocks/over-bound", s["deadlock"] == 0 and s["over_bound"] == 0, s)
# half print (0,1) first, half (1,0): symmetric -> 35/35
check("nd: 35 pass, 35 fail", en.passed == 35 and en.failed == 35, (en.passed, en.failed))

print("\n== 4. K-percentage math ==")
# every complete variant is exactly 8 ops
check("Den(8) == 70 (independent DFS)", en.count_den(8) == 70, en.count_den(8))
check("Den(7) == 0 (min ops to finish is 8)", en.count_den(7) == 0, en.count_den(7))
r8 = en.percentage_for_K(8)
check("K=8: numerator 70 (all enumerated & checked)", r8["numerator"] == 70, r8)
check("K=8: 100%", abs(r8["percent"] - 100.0) < 1e-9, r8)
r7 = en.percentage_for_K(7)
check("K=7: Den=0 -> percent is N/A (None)", r7["percent"] is None, r7)

# partial enumeration check: fresh enumerator, pull only 10 complete variants
en2 = T.Enumerator(Engine(nd, input_tokens=[]), expected_output=[0, 1])
got = 0
while got < 10:
    cv = en2.next_complete()
    if cv is None:
        break
    got += 1
p8 = en2.percentage_for_K(8)
check("partial: Den(8)=70 regardless of progress", p8["denominator"] == 70, p8)
check("partial: Num(8)=10 after 10 complete", p8["numerator"] == 10, p8)
check("partial: percent ~ 14.2857%", abs(p8["percent"] - (1000.0 / 70)) < 1e-6, p8)
check("partial: Num <= Den", p8["numerator"] <= p8["denominator"])


print("\n== 5. deadlock: INPUT with no input ==")
eng = Engine(M.Project(flowcharts=[echo_thread("t", "x")]), input_tokens=[])
en = T.Enumerator(eng, expected_output=[])
en.run_all()
s = en.summary()
check("deadlock detected", s["deadlock"] >= 1, s)
check("no complete variants", s["complete"] == 0, s)
check("Den(20)=0 for deadlock", en.count_den(20) == 0)


print("\n== 6. infinite loop (graph cycle) -> OVER_BOUND, stays finite ==")
eng = Engine(M.Project(flowcharts=[infinite_loop_thread("loop", "x")]), input_tokens=[])
en = T.Enumerator(eng, expected_output=[], bound=25)
en.run_all()
s = en.summary()
check("loop hits over-bound", s["over_bound"] >= 1, s)
check("loop has no complete variant", s["complete"] == 0, s)
det = T.analyze_determinism(eng, bound=25)
check("loop: single-thread deterministic, bound hit flagged",
      det.verdict == T.DETERMINISTIC and det.hit_bound, (det.verdict, det.hit_bound))


print("\n== 7. translator: generated Python runs & matches a valid interleaving ==")
src = translate(nd)
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write(src)
    path = f.name
try:
    out = subprocess.run([sys.executable, path], input="", capture_output=True,
                         text=True, timeout=15)
    toks = T.parse_int_tokens(out.stdout)
    check("generated program ran ok", out.returncode == 0, out.stderr)
    check("generated output is a valid interleaving",
          tuple(toks) in {(0, 1), (1, 0)}, toks)
finally:
    os.unlink(path)

# translator with INPUT
src2 = translate(M.Project(flowcharts=[echo_thread("t", "x")]))
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write(src2)
    path = f.name
try:
    out = subprocess.run([sys.executable, path], input="42\n", capture_output=True,
                         text=True, timeout=15)
    check("generated echo prints input", T.parse_int_tokens(out.stdout) == [42], out.stdout)
finally:
    os.unlink(path)


print("\n== 8. JSON round-trip ==")
js = nd.to_json()
nd2 = M.Project.from_json(js)
check("project round-trips", nd2.to_json() == js)
eng2 = Engine(nd2, input_tokens=[])
det2 = T.analyze_determinism(eng2)
check("round-tripped project still nondeterministic", det2.verdict == T.NONDETERMINISTIC)


print("\n== 9. translator: INPUT exhaustion -> deadlock report, non-zero exit ==")
src3 = translate(M.Project(flowcharts=[echo_thread("t", "x")]))
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write(src3)
    path = f.name
try:
    out = subprocess.run([sys.executable, path], input="", capture_output=True,
                         text=True, timeout=15)
    check("exits non-zero when input missing", out.returncode != 0, out.returncode)
    check("reports a deadlock (not a raw traceback)",
          "deadlock" in out.stderr.lower() and "Traceback" not in out.stderr, out.stderr)
finally:
    os.unlink(path)

raised = False
try:
    translate(M.Project(flowcharts=[]))
except ValueError:
    raised = True
check("empty project -> translate raises ValueError", raised)


print("\n== 10. GUI-free regression: edge_src clearing & self-loop delete (model) ==")
# self-loop create + remove via model API (the GUI's _delete_edge_near targets these)
loop = infinite_loop_thread("L", "x")
n_before = len(loop.edges)
# add an explicit self-loop edge and remove it
cond = next(b for b in loop.blocks.values() if b.kind == M.COND)
loop.add_edge(cond.id, cond.id, branch=False)  # self-loop replaces existing FALSE slot
check("self-loop edge stored", any(e.src == e.dst for e in loop.edges))
loop.edges = [e for e in loop.edges if not (e.src == e.dst)]
check("self-loop edge removable", not any(e.src == e.dst for e in loop.edges))


print("\n" + ("=" * 50))
if _failures:
    print("FAILED ({}): {}".format(len(_failures), ", ".join(_failures)))
    sys.exit(1)
print("ALL TESTS PASSED")
