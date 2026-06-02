"""Data model for graph2Thread.

A *Project* contains 1..100 *Flowchart*s; each flowchart describes the
sequential algorithm of one thread.  A flowchart is a directed graph (which
may contain cycles) of *Block*s connected by *Edge*s.

Everything here is pure data + (de)serialization to JSON.  It has no GUI and
no execution logic, so it can be imported by the editor, the interpreter, the
translator and the tester alike.

Targets Python 3.8+.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

# --- limits from the assignment ---------------------------------------------
INT_MIN = 0
INT_MAX = 2 ** 31 - 1            # constants / INPUT live in 0 .. 2^31-1
MAX_THREADS = 100
MAX_BLOCKS = 100
MAX_VARS = 100

# --- block kinds ------------------------------------------------------------
START = "start"
END = "end"
ASSIGN = "assign"      # V1 = V2  (source_kind="var")  or  V = C (source_kind="const")
INPUT = "input"        # INPUT V
PRINT = "print"        # PRINT V
COND = "cond"          # branch:  V == C   or   V < C

# comparison operators for COND blocks
CMP_EQ = "eq"          # V == C
CMP_LT = "lt"          # V < C

# source kinds for ASSIGN blocks
SRC_VAR = "var"
SRC_CONST = "const"

VALID_KINDS = {START, END, ASSIGN, INPUT, PRINT, COND}


def is_valid_var_name(name: str) -> bool:
    """A shared-variable name: a non-empty identifier (letters/digits/_ not
    starting with a digit)."""
    if not name:
        return False
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in name)


def is_valid_const(value: int) -> bool:
    return isinstance(value, int) and INT_MIN <= value <= INT_MAX


@dataclass
class Block:
    """A single node of a flowchart.

    Only the fields relevant to ``kind`` are meaningful; the rest stay at their
    defaults.  ``x``/``y`` are canvas coordinates used purely by the editor.
    """
    id: int
    kind: str
    x: float = 0.0
    y: float = 0.0

    # ASSIGN
    target: str = ""               # V (destination variable)
    source_kind: str = SRC_CONST   # SRC_VAR | SRC_CONST
    source_var: str = ""           # used when source_kind == SRC_VAR
    source_const: int = 0          # used when source_kind == SRC_CONST

    # INPUT / PRINT
    var: str = ""

    # COND
    cmp: str = CMP_EQ              # CMP_EQ | CMP_LT
    const: int = 0                # the literal C in  V <cmp> C

    # ---- helpers ----------------------------------------------------------
    def label(self) -> str:
        """Human-readable one-line text shown in the editor / generated code."""
        if self.kind == START:
            return "START"
        if self.kind == END:
            return "END"
        if self.kind == ASSIGN:
            rhs = self.source_var if self.source_kind == SRC_VAR else str(self.source_const)
            return "{} = {}".format(self.target, rhs)
        if self.kind == INPUT:
            return "INPUT {}".format(self.var)
        if self.kind == PRINT:
            return "PRINT {}".format(self.var)
        if self.kind == COND:
            op = "==" if self.cmp == CMP_EQ else "<"
            return "{} {} {}".format(self.var, op, self.const)
        return "?"

    def variables(self) -> List[str]:
        """All shared-variable names referenced by this block."""
        out: List[str] = []
        if self.kind == ASSIGN:
            out.append(self.target)
            if self.source_kind == SRC_VAR:
                out.append(self.source_var)
        elif self.kind in (INPUT, PRINT):
            out.append(self.var)
        elif self.kind == COND:
            out.append(self.var)
        return [v for v in out if v]


@dataclass
class Edge:
    """Directed edge ``src -> dst``.

    ``branch`` is ``None`` for ordinary edges, and ``True``/``False`` for the
    two outgoing edges of a COND block (its true/false branches)."""
    src: int
    dst: int
    branch: Optional[bool] = None


@dataclass
class Flowchart:
    """One thread's algorithm: a directed graph of blocks."""
    name: str = "thread"
    blocks: Dict[int, Block] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    _next_id: int = 1

    # ---- block / edge management -----------------------------------------
    def new_block(self, kind: str, x: float = 0.0, y: float = 0.0, **kw) -> Block:
        bid = self._next_id
        self._next_id += 1
        b = Block(id=bid, kind=kind, x=x, y=y, **kw)
        self.blocks[bid] = b
        return b

    def remove_block(self, bid: int) -> None:
        self.blocks.pop(bid, None)
        self.edges = [e for e in self.edges if e.src != bid and e.dst != bid]

    def add_edge(self, src: int, dst: int, branch: Optional[bool] = None) -> Edge:
        # replace any existing edge with the same (src, branch) slot
        self.edges = [e for e in self.edges
                      if not (e.src == src and e.branch == branch)]
        e = Edge(src=src, dst=dst, branch=branch)
        self.edges.append(e)
        return e

    def remove_edge(self, src: int, dst: int, branch: Optional[bool] = None) -> None:
        self.edges = [e for e in self.edges
                      if not (e.src == src and e.dst == dst and e.branch == branch)]

    def start_block(self) -> Optional[Block]:
        for b in self.blocks.values():
            if b.kind == START:
                return b
        return None

    def successors(self, bid: int) -> Dict[Optional[bool], int]:
        """Map ``branch -> dst`` for the outgoing edges of ``bid``."""
        return {e.branch: e.dst for e in self.edges if e.src == bid}

    def variables(self) -> List[str]:
        names = []
        for b in self.blocks.values():
            for v in b.variables():
                if v not in names:
                    names.append(v)
        return names

    # ---- (de)serialization ------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "next_id": self._next_id,
            "blocks": [asdict(b) for b in self.blocks.values()],
            "edges": [asdict(e) for e in self.edges],
        }

    @staticmethod
    def from_dict(d: dict) -> "Flowchart":
        fc = Flowchart(name=d.get("name", "thread"))
        fc._next_id = d.get("next_id", 1)
        fc.blocks = {}
        for bd in d.get("blocks", []):
            b = Block(**bd)
            fc.blocks[b.id] = b
        fc.edges = [Edge(**ed) for ed in d.get("edges", [])]
        if fc._next_id <= max(fc.blocks.keys(), default=0):
            fc._next_id = max(fc.blocks.keys(), default=0) + 1
        return fc


@dataclass
class Project:
    """The whole document: an ordered list of per-thread flowcharts."""
    flowcharts: List[Flowchart] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {"version": 1, "flowcharts": [fc.to_dict() for fc in self.flowcharts]},
            indent=2,
        )

    @staticmethod
    def from_json(text: str) -> "Project":
        d = json.loads(text)
        p = Project()
        p.flowcharts = [Flowchart.from_dict(fd) for fd in d.get("flowcharts", [])]
        return p

    def all_variables(self) -> List[str]:
        names: List[str] = []
        for fc in self.flowcharts:
            for v in fc.variables():
                if v not in names:
                    names.append(v)
        return names


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
def validate_flowchart(fc: Flowchart, idx: Optional[int] = None) -> List[str]:
    """Return blocking structural ERRORS (empty == translatable/executable).

    These are problems that make the flowchart's execution ill-defined: wrong
    out-degree, bad field values, missing/duplicate START, or exceeded limits.
    Soft issues that are still well-defined (no END, unreachable blocks) are
    reported by :func:`lint_flowchart` instead, since the spec permits graph
    cycles and therefore intentionally non-terminating threads.
    """
    where = "thread #{}".format(idx) if idx is not None else "flowchart"
    errs: List[str] = []

    if len(fc.blocks) > MAX_BLOCKS:
        errs.append("{}: has {} blocks (max {}).".format(where, len(fc.blocks), MAX_BLOCKS))

    starts = [b for b in fc.blocks.values() if b.kind == START]
    if len(starts) == 0:
        errs.append("{}: no START block.".format(where))
    elif len(starts) > 1:
        errs.append("{}: {} START blocks (need exactly 1).".format(where, len(starts)))

    for b in fc.blocks.values():
        succ = fc.successors(b.id)
        tag = "{} block #{} ({})".format(where, b.id, b.label())

        # out-degree rules
        if b.kind == END:
            if succ:
                errs.append("{}: END must have no outgoing edge.".format(tag))
        elif b.kind == COND:
            if set(succ.keys()) != {True, False}:
                errs.append("{}: condition needs exactly one TRUE and one FALSE edge.".format(tag))
        else:  # START, ASSIGN, INPUT, PRINT
            if list(succ.keys()) != [None]:
                errs.append("{}: must have exactly one outgoing edge.".format(tag))

        # field rules
        if b.kind == ASSIGN:
            if not is_valid_var_name(b.target):
                errs.append("{}: invalid destination variable.".format(tag))
            if b.source_kind == SRC_VAR:
                if not is_valid_var_name(b.source_var):
                    errs.append("{}: invalid source variable.".format(tag))
            elif b.source_kind == SRC_CONST:
                if not is_valid_const(b.source_const):
                    errs.append("{}: constant out of range 0..2^31-1.".format(tag))
            else:
                errs.append("{}: unknown source kind.".format(tag))
        elif b.kind in (INPUT, PRINT):
            if not is_valid_var_name(b.var):
                errs.append("{}: invalid variable.".format(tag))
        elif b.kind == COND:
            if not is_valid_var_name(b.var):
                errs.append("{}: invalid variable.".format(tag))
            if b.cmp not in (CMP_EQ, CMP_LT):
                errs.append("{}: unknown comparison.".format(tag))
            if not is_valid_const(b.const):
                errs.append("{}: constant out of range 0..2^31-1.".format(tag))

    nvars = len(fc.variables())
    if nvars > MAX_VARS:
        errs.append("{}: uses {} variables (max {}).".format(where, nvars, MAX_VARS))

    return errs


def lint_flowchart(fc: Flowchart, idx: Optional[int] = None) -> List[str]:
    """Return non-blocking WARNINGS: things that are legal but probably a
    mistake (a thread with no reachable END never terminates; unreachable
    blocks are dead code)."""
    where = "thread #{}".format(idx) if idx is not None else "flowchart"
    warns: List[str] = []

    # reachability from START
    start = fc.start_block()
    seen = set()
    if start is not None:
        stack = [start.id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for dst in fc.successors(cur).values():
                stack.append(dst)
        unreachable = [b.id for b in fc.blocks.values() if b.id not in seen]
        if unreachable:
            warns.append("{}: blocks unreachable from START: {} (dead code).".format(where, unreachable))

    reachable_end = any(fc.blocks.get(bid) and fc.blocks[bid].kind == END for bid in seen)
    if not reachable_end:
        warns.append("{}: no END reachable from START — this thread never "
                     "terminates (only valid if you intend an infinite loop).".format(where))
    return warns


def validate_project(p: Project) -> List[str]:
    """Blocking errors for the whole project (empty == ready to translate/test)."""
    errs: List[str] = []
    n = len(p.flowcharts)
    if n < 1:
        errs.append("Project has no threads (need 1..{}).".format(MAX_THREADS))
    if n > MAX_THREADS:
        errs.append("Project has {} threads (max {}).".format(n, MAX_THREADS))
    for i, fc in enumerate(p.flowcharts):
        errs.extend(validate_flowchart(fc, idx=i))
    return errs


def lint_project(p: Project) -> List[str]:
    """Non-blocking warnings for the whole project."""
    warns: List[str] = []
    for i, fc in enumerate(p.flowcharts):
        warns.extend(lint_flowchart(fc, idx=i))
    return warns
