"""Headless command-line front-end.

Useful on machines without Tkinter and for scripting/testing.  Covers all
three points:

  translate   PROJECT [-o OUT.py]                 (Point 2)
  analyze     PROJECT [--bound B]                  (determinism, Point 3)
  test        PROJECT TESTSET [--mode once|all]    (Point 3)
  enumerate   PROJECT [--test TESTSET --index i]   (Point 3 interrupt + K)

``enumerate`` prints variants as it finds them; press Ctrl-C to interrupt,
then enter K (1..20) to see the percentage of <=K-operation complete variants
verified so far -- exactly the spec's interrupt flow.  For scripted runs use
--interrupt-after N --k K.
"""
from __future__ import annotations

import argparse
import sys

from . import model as M
from . import tester as T
from .interpreter import Engine
from .translator import translate


def _load_project(path: str) -> M.Project:
    with open(path, "r", encoding="utf-8") as f:
        return M.Project.from_json(f.read())


def _load_testset(path: str) -> T.TestSet:
    with open(path, "r", encoding="utf-8") as f:
        return T.TestSet.from_json(f.read())


def _check(p: M.Project) -> bool:
    """Print blocking errors / non-blocking warnings; return True if usable."""
    errs = M.validate_project(p)
    if errs:
        sys.stderr.write("Validation errors:\n  " + "\n  ".join(errs) + "\n")
        return False
    warns = M.lint_project(p)
    if warns:
        sys.stderr.write("Warnings:\n  " + "\n  ".join(warns) + "\n")
    return True


def cmd_translate(args) -> int:
    p = _load_project(args.project)
    if not _check(p):
        return 2
    src = translate(p)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(src)
        print("Wrote {} ({} threads).".format(args.output, len(p.flowcharts)))
    else:
        sys.stdout.write(src)
    return 0


def cmd_analyze(args) -> int:
    p = _load_project(args.project)
    if not _check(p):
        return 2
    eng = Engine(p, input_tokens=T.parse_int_tokens(args.input or ""))
    rep = T.analyze_determinism(eng, bound=args.bound)
    print("verdict           : {}".format(rep.verdict))
    print("distinct outputs  : {}".format(rep.distinct_output_count))
    for o in rep.distinct_outputs:
        print("    {}".format(list(o)))
    print("max branching     : {}".format(rep.max_branching))
    print("bound hit         : {}".format(rep.hit_bound))
    print("nodes explored    : {}{}".format(rep.nodes_explored,
                                            " (truncated!)" if rep.truncated else ""))
    return 0


def _print_summary(en: T.Enumerator) -> None:
    s = en.summary()
    print("  complete={complete}  passed={passed}  failed={failed}  "
          "deadlock={deadlock}  over_bound={over_bound}  "
          "distinct_outputs={n}  exhausted={exhausted}".format(
              n=len(s["distinct_outputs"]), **s))


def cmd_test(args) -> int:
    p = _load_project(args.project)
    if not _check(p):
        return 2
    ts = _load_testset(args.testset)
    failed_any = False
    for tc in ts.cases:
        eng = Engine(p, input_tokens=tc.input_tokens)
        print("\n# test '{}'  input={}  expected={}".format(
            tc.name, tc.input_tokens, tc.expected_output))
        if args.mode == "once":
            v = T.first_variant(eng, tc.expected_output, bound=args.bound)
            ok = (v.klass == T.COMPLETE and v.passed)
            failed_any = failed_any or not ok
            print("  one interleaving: {}  output={}  ({})".format(
                "PASS" if ok else "FAIL", list(v.output), v.klass))
        else:  # all interleavings
            en = T.Enumerator(eng, tc.expected_output, bound=args.bound)
            en.run_all(max_variants=args.max)
            _print_summary(en)
            if en.failed > 0:
                failed_any = True
            # report any output that did not match
            if en.failed:
                bad = [list(o) for o in en.distinct_outputs
                       if o != tuple(tc.expected_output)]
                print("  outputs != expected: {}".format(bad))
    return 1 if failed_any else 0


def cmd_enumerate(args) -> int:
    p = _load_project(args.project)
    if not _check(p):
        return 2
    expected = []
    inp = T.parse_int_tokens(args.input or "")
    if args.test:
        ts = _load_testset(args.test)
        if not ts.cases:
            sys.stderr.write("Test set '{}' is empty.\n".format(args.test))
            return 2
        if not (0 <= args.index < len(ts.cases)):
            sys.stderr.write("--index {} out of range (0..{}).\n".format(
                args.index, len(ts.cases) - 1))
            return 2
        tc = ts.cases[args.index]
        inp = tc.input_tokens
        expected = tc.expected_output
        print("Using test '{}' input={} expected={}".format(tc.name, inp, expected))
    eng = Engine(p, input_tokens=inp)
    en = T.Enumerator(eng, expected, bound=args.bound)

    def report_k(k: int) -> None:
        r = en.percentage_for_K(k)
        if r["percent"] is None:
            pct = "N/A (no complete variants of <= {} operations)".format(k)
        else:
            pct = "{:.4f}%".format(r["percent"])
        print("\n--- K = {} ---".format(k))
        print("  complete variants with <=K ops verified so far: {} / {}  ->  {}".format(
            r["numerator"], r["denominator"], pct))
        print("  (deadlocks seen={}, over-bound seen={}, passed={}, failed={})".format(
            r["deadlocks_seen"], r["over_bound_seen"], r["passed"], r["failed"]))

    count = 0
    try:
        while True:
            v = en.next()
            if v is None:
                print("\n[enumeration exhausted]")
                _print_summary(en)
                break
            count += 1
            if args.verbose:
                tag = v.klass.upper()
                extra = " output={} {}".format(list(v.output),
                                               "PASS" if v.passed else "FAIL") \
                    if v.klass == T.COMPLETE else ""
                print("  #{:<6} ops={:<3} {}{}  schedule={}".format(
                    count, v.op_count, tag, extra, v.schedule))
            if args.interrupt_after and count >= args.interrupt_after:
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        if args.k:
            report_k(args.k)
        else:
            try:
                k = int(input("\nInterrupted. Enter K (1..20): ").strip())
                report_k(k)
            except (ValueError, EOFError):
                print("no K entered.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="graph2thread",
                                 description="Flowchart-driven multithreaded program tool.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("translate", help="translate flowcharts to Python (Point 2)")
    t.add_argument("project")
    t.add_argument("-o", "--output")
    t.set_defaults(func=cmd_translate)

    a = sub.add_parser("analyze", help="determinism analysis (Point 3)")
    a.add_argument("project")
    a.add_argument("--input", help="stdin tokens, e.g. '3 4'")
    a.add_argument("--bound", type=int, default=T.DEFAULT_BOUND)
    a.set_defaults(func=cmd_analyze)

    te = sub.add_parser("test", help="run a test set (Point 3)")
    te.add_argument("project")
    te.add_argument("testset")
    te.add_argument("--mode", choices=["once", "all"], default="all",
                    help="'once': one interleaving; 'all': enumerate interleavings")
    te.add_argument("--bound", type=int, default=T.DEFAULT_BOUND)
    te.add_argument("--max", type=int, default=None, help="cap on variants in 'all' mode")
    te.set_defaults(func=cmd_test)

    e = sub.add_parser("enumerate", help="enumerate interleavings, Ctrl-C + K (Point 3)")
    e.add_argument("project")
    e.add_argument("--input", help="stdin tokens")
    e.add_argument("--test", help="testset json to take input/expected from")
    e.add_argument("--index", type=int, default=0, help="test case index")
    e.add_argument("--bound", type=int, default=T.DEFAULT_BOUND)
    e.add_argument("--verbose", action="store_true")
    e.add_argument("--interrupt-after", type=int, default=None,
                   help="auto-interrupt after N variants (scripted)")
    e.add_argument("--k", type=int, default=None, help="K to report on interrupt (scripted)")
    e.set_defaults(func=cmd_enumerate)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        sys.stderr.write("File not found: {}\n".format(e.filename or e))
        return 2
    except ValueError as e:           # incl. json.JSONDecodeError (malformed file)
        sys.stderr.write("Could not parse input (malformed JSON or value?): {}\n".format(e))
        return 2
    except OSError as e:
        sys.stderr.write("I/O error: {}\n".format(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
