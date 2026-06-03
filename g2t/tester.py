"""Point 3 — testing by systematic enumeration of thread interleavings.

Implements the reconciled semantics:

* One *operation* = one block execution; a *variant* = one schedule (ordered
  sequence of thread choices), identified by that sequence.
* Enumeration is a stateful DFS over the schedule tree, expanding runnable
  threads in ascending id order, so every root-to-leaf path is produced
  exactly once -> *no repeats* are structural (no visited set needed).
* Leaves are classified COMPLETE (all threads finished), DEADLOCK (someone
  blocked forever, e.g. INPUT with no input), or OVER_BOUND (path hit the
  per-path operation cap ``bound`` -- this is how graph cycles / livelocks are
  kept finite).
* Output is compared as the exact ordered sequence of printed integers.
* The K-percentage on interrupt:
    Den(K) = number of COMPLETE variants whose op-count <= K
             (computed by an INDEPENDENT memoised bounded DFS),
    Num(K) = COMPLETE variants with op-count <= K enumerated & checked so far,
    percent = 100 * Num/Den   (N/A if Den == 0).
  Deadlocks and over-bound paths are excluded from both and reported apart.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import model as M
from .interpreter import Engine, State, RUNNING, DONE, DEADLOCK

# leaf classes
COMPLETE = "complete"
LEAF_DEADLOCK = "deadlock"
OVER_BOUND = "over_bound"

# determinism verdicts
DETERMINISTIC = "deterministic"
NONDETERMINISTIC = "nondeterministic"
NONDET_OR_NONTERM = "nondeterministic_or_nonterminating"  # bound hit while branching
UNKNOWN_TOO_LARGE = "unknown_too_large"

DEFAULT_BOUND = 1000


# ----------------------------------------------------------------------------
# I/O helpers
# ----------------------------------------------------------------------------
def parse_int_tokens(text: str) -> List[int]:
    """Parse whitespace-separated decimal integers from text."""
    text = (text or "").strip()
    if not text:
        return []
    return [int(tok) for tok in re.split(r"\s+", text)]


def validate_token_range(tokens: List[int], label: str = "value") -> None:
    """Raise ValueError if any token is outside the valid 0..2^31-1 range."""
    for t in tokens:
        if not (M.INT_MIN <= t <= M.INT_MAX):
            raise ValueError("{} {} is outside the allowed range 0..2³¹-1".format(label, t))


def format_output(tokens) -> str:
    """Canonical printed form: one integer per line (matches PRINT)."""
    return "\n".join(str(t) for t in tokens)


@dataclass
class TestCase:
    name: str
    input_tokens: List[int] = field(default_factory=list)
    expected_output: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name,
                "input": list(self.input_tokens),
                "expected": list(self.expected_output)}

    @staticmethod
    def from_dict(d: dict) -> "TestCase":
        return TestCase(name=d.get("name", "test"),
                        input_tokens=list(d.get("input", [])),
                        expected_output=list(d.get("expected", [])))


@dataclass
class Variant:
    """One enumerated execution (one root-to-leaf path)."""
    schedule: List[int]
    op_count: int
    klass: str
    output: Tuple[int, ...]
    passed: Optional[bool]      # None unless COMPLETE


# ----------------------------------------------------------------------------
# Enumerator
# ----------------------------------------------------------------------------
class Enumerator:
    """Lazily enumerates every execution variant (no repeats) for one test.

    Pull variants one at a time with :meth:`next` / iteration, or
    :meth:`next_complete` to skip to the next COMPLETE run.  Running statistics
    accumulate as variants are produced; :meth:`percentage_for_K` answers the
    interrupt question at any moment.
    """

    def __init__(self, engine: Engine, expected_output: List[int],
                 bound: int = DEFAULT_BOUND):
        self.engine = engine
        self.expected = list(expected_output)
        self.bound = bound

        # running statistics
        self.counts = {COMPLETE: 0, LEAF_DEADLOCK: 0, OVER_BOUND: 0}
        self.passed = 0
        self.failed = 0
        self.distinct_outputs = set()           # of COMPLETE variants
        self.complete_hist: Dict[int, int] = {}  # op_count -> #complete enumerated
        self.total_emitted = 0
        self.exhausted = False

        self._gen = self._leaves()

    # ---- the DFS generator ------------------------------------------------
    def _leaves(self):
        eng = self.engine
        s0 = eng.initial_state()
        if eng.status(s0) != RUNNING:
            yield self._make(s0, [])
            return
        # stack frames: (state, iterator over enabled thread ids, schedule)
        stack = [(s0, iter(eng.enabled(s0)), [])]
        while stack:
            state, it, sched = stack[-1]
            tid = next(it, None)
            if tid is None:
                stack.pop()
                continue
            ns = eng.step(state, tid)
            nsched = sched + [tid]
            st = eng.status(ns)
            if st == DONE:
                yield self._make(ns, nsched)
            elif st == DEADLOCK:
                yield self._make(ns, nsched)
            elif len(nsched) >= self.bound:
                yield self._make(ns, nsched, forced=OVER_BOUND)
            else:
                stack.append((ns, iter(eng.enabled(ns)), nsched))

    def _make(self, state: State, schedule: List[int], forced: Optional[str] = None) -> Variant:
        st = self.engine.status(state)
        if forced == OVER_BOUND:
            klass = OVER_BOUND
        elif st == DONE:
            klass = COMPLETE
        elif st == DEADLOCK:
            klass = LEAF_DEADLOCK
        else:
            klass = OVER_BOUND
        passed = None
        if klass == COMPLETE:
            passed = (list(state.output) == self.expected)
        return Variant(schedule=schedule, op_count=len(schedule),
                       klass=klass, output=state.output, passed=passed)

    # ---- pulling variants -------------------------------------------------
    def next(self) -> Optional[Variant]:
        """Return the next variant, or None when enumeration is exhausted."""
        try:
            v = next(self._gen)
        except StopIteration:
            self.exhausted = True
            return None
        self._record(v)
        return v

    def __iter__(self):
        return self

    def __next__(self) -> Variant:
        v = self.next()
        if v is None:
            raise StopIteration
        return v

    def next_complete(self) -> Optional[Variant]:
        """Advance until the next COMPLETE variant (recording everything in
        between), or None if none remain."""
        while True:
            v = self.next()
            if v is None:
                return None
            if v.klass == COMPLETE:
                return v

    def run_all(self, max_variants: Optional[int] = None) -> None:
        """Exhaust the enumeration (or stop after ``max_variants`` leaves)."""
        n = 0
        while True:
            v = self.next()
            if v is None:
                return
            n += 1
            if max_variants is not None and n >= max_variants:
                return

    def _record(self, v: Variant) -> None:
        self.total_emitted += 1
        self.counts[v.klass] = self.counts.get(v.klass, 0) + 1
        if v.klass == COMPLETE:
            self.distinct_outputs.add(v.output)
            self.complete_hist[v.op_count] = self.complete_hist.get(v.op_count, 0) + 1
            if v.passed:
                self.passed += 1
            else:
                self.failed += 1

    # ---- the interrupt question ------------------------------------------
    def count_den(self, K: int) -> int:
        """|Den(K)| = number of COMPLETE variants with op-count <= K.

        Independent memoised bounded DFS using the SAME step/enabled semantics
        as the live enumeration, so Num(K) is always a subset of Den(K).
        Always finite: depth <= K (<= 20), branching <= N.
        """
        eng = self.engine
        memo: Dict[tuple, int] = {}

        def rec(state: State, budget: int) -> int:
            if eng.status(state) == DONE:
                return 1
            if budget == 0:
                return 0
            # output is irrelevant to future completion counting -> omit it from
            # the key to maximise sharing.
            k = (tuple(sorted(state.mem.items())), state.pcs, state.input_pos, budget)
            cached = memo.get(k)
            if cached is not None:
                return cached
            total = 0
            for t in eng.enabled(state):
                total += rec(eng.step(state, t), budget - 1)
            memo[k] = total
            return total

        return rec(eng.initial_state(), K)

    def num_for_K(self, K: int) -> int:
        return sum(c for oc, c in self.complete_hist.items() if oc <= K)

    def percentage_for_K(self, K: int) -> dict:
        """Answer the interrupt question for a given K (1..20)."""
        den = self.count_den(K)
        num = self.num_for_K(K)
        percent = None if den == 0 else 100.0 * num / den
        return {
            "K": K,
            "denominator": den,
            "numerator": num,
            "percent": percent,                     # None == N/A (Den == 0)
            "deadlocks_seen": self.counts.get(LEAF_DEADLOCK, 0),
            "over_bound_seen": self.counts.get(OVER_BOUND, 0),
            "distinct_outputs": len(self.distinct_outputs),
            "passed": self.passed,
            "failed": self.failed,
            "exhausted": self.exhausted,
        }

    # ---- summary ----------------------------------------------------------
    def summary(self) -> dict:
        return {
            "complete": self.counts.get(COMPLETE, 0),
            "deadlock": self.counts.get(LEAF_DEADLOCK, 0),
            "over_bound": self.counts.get(OVER_BOUND, 0),
            "passed": self.passed,
            "failed": self.failed,
            "distinct_outputs": sorted(self.distinct_outputs),
            "exhausted": self.exhausted,
        }


# ----------------------------------------------------------------------------
# Determinism analysis
# ----------------------------------------------------------------------------
@dataclass
class DeterminismReport:
    verdict: str
    distinct_output_count: int
    distinct_outputs: List[Tuple[int, ...]]
    max_branching: int
    hit_bound: bool
    nodes_explored: int
    truncated: bool


def analyze_determinism(engine: Engine, bound: int = DEFAULT_BOUND,
                        node_cap: int = 200000) -> DeterminismReport:
    """Decide whether the program's output is uniquely determined by its input.

    Verdict is keyed on OUTPUT equality across all COMPLETE variants (per the
    spec's "two threads print 0 and 1" example), with structural and bound
    caveats surfaced via the flags.
    """
    s0 = engine.initial_state()
    outputs = set()
    max_branch = 0
    hit_bound = False
    nodes = 0
    truncated = False

    start_enabled = engine.enabled(s0)
    max_branch = max(max_branch, len(start_enabled))

    if engine.status(s0) != RUNNING:
        if engine.status(s0) == DONE:
            outputs.add(s0.output)
        return DeterminismReport(DETERMINISTIC, len(outputs), sorted(outputs),
                                 max_branch, False, 0, False)

    stack = [(s0, iter(start_enabled), 0)]
    while stack:
        nodes += 1
        if nodes > node_cap:
            truncated = True
            break
        state, it, depth = stack[-1]
        tid = next(it, None)
        if tid is None:
            stack.pop()
            continue
        ns = engine.step(state, tid)
        d = depth + 1
        st = engine.status(ns)
        if st == DONE:
            outputs.add(ns.output)
        elif st == DEADLOCK:
            pass
        elif d >= bound:
            hit_bound = True
        else:
            en = engine.enabled(ns)
            if len(en) > max_branch:
                max_branch = len(en)
            stack.append((ns, iter(en), d))

    if truncated:
        verdict = UNKNOWN_TOO_LARGE
    elif max_branch <= 1:
        verdict = DETERMINISTIC
    elif hit_bound:
        verdict = NONDET_OR_NONTERM
    elif len(outputs) <= 1:
        verdict = DETERMINISTIC
    else:
        verdict = NONDETERMINISTIC

    return DeterminismReport(verdict, len(outputs), sorted(outputs),
                             max_branch, hit_bound, nodes, truncated)


# ----------------------------------------------------------------------------
# Single-run helpers (quick deterministic check)
# ----------------------------------------------------------------------------
def first_variant(engine: Engine, expected_output: List[int],
                  bound: int = DEFAULT_BOUND) -> Variant:
    """Run one canonical interleaving (always pick the lowest-id runnable
    thread) to a terminal state.  This is the first variant the enumerator
    would yield; enough to check a deterministic program."""
    st = engine.initial_state()
    sched: List[int] = []
    while True:
        status = engine.status(st)
        if status != RUNNING:
            klass = COMPLETE if status == DONE else LEAF_DEADLOCK
            passed = (list(st.output) == list(expected_output)) if klass == COMPLETE else None
            return Variant(sched, len(sched), klass, st.output, passed)
        if len(sched) >= bound:
            return Variant(sched, len(sched), OVER_BOUND, st.output, None)
        tid = engine.enabled(st)[0]
        st = engine.step(st, tid)
        sched.append(tid)


@dataclass
class TestSet:
    """A user-defined set of test cases (Point 3)."""
    cases: List[TestCase] = field(default_factory=list)

    def to_json(self) -> str:
        import json
        return json.dumps({"version": 1, "tests": [c.to_dict() for c in self.cases]}, indent=2)

    @staticmethod
    def from_json(text: str) -> "TestSet":
        import json
        d = json.loads(text)
        return TestSet(cases=[TestCase.from_dict(c) for c in d.get("tests", [])])
