"""The stepping engine.

This is the operational semantics shared by the tester and (conceptually) by
the translated program:

* The whole multithreaded program has one global *state*: shared memory, one
  program counter per thread, a position in the shared input stream, and the
  sequence of values printed so far.
* **One operation = execution of one flowchart block** (START and END
  included).  Threads interleave only at block boundaries, i.e. each block is
  atomic.  This is exactly what the generated program enforces with its global
  lock, so model and code agree.
* ``step(state, tid)`` returns a *new* state (states are never mutated in
  place), which keeps the DFS in the tester simple and bug-free.

The engine never decides scheduling; it only reports which threads are
*enabled* and executes the one the caller picks.  All nondeterminism therefore
lives in the caller's choice of ``tid``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import model as M

# terminal status of a whole-program state
RUNNING = "running"
DONE = "done"          # every thread reached END
DEADLOCK = "deadlock"  # some thread unfinished but nobody can move
                       # (e.g. INPUT with no input left)


@dataclass
class State:
    """Immutable-by-convention snapshot of the whole program."""
    mem: Dict[str, int]
    pcs: Tuple[Optional[int], ...]   # current block id per thread (None = finished)
    input_pos: int
    output: Tuple[int, ...]

    def clone_mem(self) -> Dict[str, int]:
        return dict(self.mem)

    def key(self) -> tuple:
        """Hashable identity of this state (for optional stateful dedup)."""
        return (tuple(sorted(self.mem.items())), self.pcs, self.input_pos, self.output)


class Engine:
    """Operational semantics over a fixed project + fixed input."""

    def __init__(self, project: M.Project, input_tokens: Optional[List[int]] = None):
        self.project = project
        self.flowcharts = project.flowcharts
        self.input_tokens: List[int] = list(input_tokens or [])
        self.variables = project.all_variables()

    # ---- construction -----------------------------------------------------
    def initial_state(self) -> State:
        mem = {v: 0 for v in self.variables}
        pcs = []
        for fc in self.flowcharts:
            start = fc.start_block()
            pcs.append(start.id if start is not None else None)
        return State(mem=mem, pcs=tuple(pcs), input_pos=0, output=tuple())

    # ---- queries ----------------------------------------------------------
    def _block(self, tid: int, bid: int) -> M.Block:
        return self.flowcharts[tid].blocks[bid]

    def thread_enabled(self, state: State, tid: int) -> bool:
        """Can thread ``tid`` take a step from ``state``?"""
        pc = state.pcs[tid]
        if pc is None:
            return False
        b = self._block(tid, pc)
        if b.kind == M.INPUT:
            # blocked when the shared input stream is exhausted
            return state.input_pos < len(self.input_tokens)
        return True

    def enabled(self, state: State) -> List[int]:
        """Thread indices that can move, in deterministic (ascending) order."""
        return [t for t in range(len(state.pcs))
                if self.thread_enabled(state, t)]

    def status(self, state: State) -> str:
        if all(pc is None for pc in state.pcs):
            return DONE
        if not self.enabled(state):
            return DEADLOCK
        return RUNNING

    def is_terminal(self, state: State) -> bool:
        return self.status(state) != RUNNING

    # ---- transition -------------------------------------------------------
    def step(self, state: State, tid: int) -> State:
        """Execute one block of thread ``tid``; return the resulting new state.

        Caller must ensure ``thread_enabled(state, tid)`` is true.
        """
        pc = state.pcs[tid]
        b = self._block(tid, pc)
        fc = self.flowcharts[tid]
        succ = fc.successors(b.id)

        mem = state.mem
        input_pos = state.input_pos
        output = state.output
        next_pc: Optional[int]

        if b.kind == M.START:
            next_pc = succ.get(None)
        elif b.kind == M.END:
            next_pc = None
        elif b.kind == M.ASSIGN:
            mem = state.clone_mem()
            if b.source_kind == M.SRC_VAR:
                mem[b.target] = mem.get(b.source_var, 0)
            else:
                mem[b.target] = b.source_const
            next_pc = succ.get(None)
        elif b.kind == M.INPUT:
            mem = state.clone_mem()
            mem[b.var] = int(self.input_tokens[input_pos])
            input_pos = input_pos + 1
            next_pc = succ.get(None)
        elif b.kind == M.PRINT:
            output = output + (mem.get(b.var, 0),)
            next_pc = succ.get(None)
        elif b.kind == M.COND:
            val = mem.get(b.var, 0)
            if b.cmp == M.CMP_EQ:
                taken = (val == b.const)
            else:  # CMP_LT
                taken = (val < b.const)
            next_pc = succ.get(taken)
        else:
            next_pc = None

        new_pcs = list(state.pcs)
        new_pcs[tid] = next_pc
        return State(mem=mem, pcs=tuple(new_pcs), input_pos=input_pos, output=output)

    # ---- convenience ------------------------------------------------------
    def run_schedule(self, schedule: List[int]) -> Tuple[State, bool]:
        """Replay an explicit schedule (list of thread ids).  Returns the final
        state and whether the schedule was fully applied (every chosen thread
        was actually enabled when its turn came)."""
        st = self.initial_state()
        for tid in schedule:
            if not self.thread_enabled(st, tid):
                return st, False
            st = self.step(st, tid)
        return st, True
