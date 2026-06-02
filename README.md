# graph2Thread

A tool that lets you **define the behaviour of a multithreaded console program
with a set of flowcharts** (one flowchart per thread), **translate** that set
into a runnable multithreaded program, and **test** it by systematically
enumerating thread interleavings.

This implements the lab assignment: Point 1 (graphical flowchart editor),
Point 2 (translation to source code), Point 3 (interleaving-aware testing with
the K-operations percentage).

---

## Requirements & running

Pure standard library — **no third-party packages**. You only need a Python
with **Tkinter** for the GUI (the engine/CLI need no GUI at all).

```bash
# GUI (the graphical editor):
python3 main.py

# Headless engine (no display needed):
python3 -m g2t.cli --help

# Self-tests for the engine:
python3 selftest.py

# (Re)generate the bundled examples:
python3 examples/make_examples.py
```

> **macOS note.** This machine's *system* `/usr/bin/python3` ships an ancient
> Tk 8.5 that refuses to start on macOS 26. The Homebrew interpreter was given
> a modern Tk with `brew install python-tk@3.14` (Tcl/Tk 9), so `python3
> main.py` works. If you ever see `No module named '_tkinter'`, install a
> Tk-enabled Python; the CLI still works without it.

---

## Point 1 — the flowchart editor (GUI)

* The left list holds **1..100 threads**; each is its own flowchart of **up to
  100 blocks**. Add/remove/rename threads.
* Toolbar tools place blocks on the canvas, connect them with **edges**
  (directed; **graph cycles are allowed**), move them, and delete them.
  Double-click (or right-click → Edit) to set a block's fields.
* Block kinds and the actions/conditions required by the spec:

  | Block    | Meaning                                             |
  |----------|-----------------------------------------------------|
  | START / END | thread entry / termination                       |
  | Assign   | `V1 = V2` (copy) **or** `V = C` (constant `0..2^31-1`) |
  | Input    | `INPUT V` — read an int from stdin into `V`         |
  | Print    | `PRINT V` — write `V` to stdout                     |
  | Branch   | condition `V == C` or `V < C` (TRUE / FALSE edges)  |

  All variables `V` are **shared 32-bit integers in shared memory**, visible to
  every thread, initialised to `0`. Up to 100 per flowchart.
* **Save/Open** projects as JSON (`File` menu). Format below.

Branch blocks need exactly one **TRUE** and one **FALSE** outgoing edge (when
connecting from a Branch block you are asked which one). Every other
non-terminal block needs exactly one outgoing edge.

---

## Point 2 — translation to source code

`Translate` tab → **Generate** (or `File → Export Python…`, or
`python3 -m g2t.cli translate project.json -o out.py`).

The target language is **Python 3** (`threading`). Design:

* Each flowchart becomes a thread function built as a **program-counter state
  machine** (`while pc is not None: dispatch on pc`), which represents an
  arbitrary directed graph — **including cycles** — directly.
* All shared variables live in one module-level dict `MEM`.
* **Block-level atomicity:** every block executes while holding one global
  `LOCK`, so threads interleave only *between* blocks. This makes the generated
  program a faithful realisation of the model the tester uses (see Point 3),
  exactly as the assignment requires.
* `INPUT` consumes the next whitespace-separated integer from stdin; `PRINT`
  writes one integer per line. If a thread reaches `INPUT` with no input left,
  the model treats it as a *blocked / deadlocked* execution (no "output after
  all threads finish"); the generated program mirrors this by reporting the
  deadlock on stderr and exiting non-zero rather than crashing or silently
  succeeding.

```bash
python3 -m g2t.cli translate examples/race_0_1.json -o race.py
python3 race.py        # prints "0 1" or "1 0" depending on the schedule
```

---

## Point 3 — testing by interleaving enumeration

A **test set** is a list of test cases; each case is `(input, expected
output)`. Manage it in the `Testing` tab or load/save JSON.

### Semantics (the precise model)

* **One operation = one block execution** (START/END included). Threads
  interleave only at block boundaries.
* An **execution variant** = one *schedule* (the ordered sequence of thread
  choices). Two variants are the same iff their schedules are identical — even
  if they print the same thing.
* `INPUT` reads from a single shared stdin stream; *which* thread reads *which*
  value is just a consequence of the schedule.
* Enumeration is a **DFS over the schedule tree** expanding runnable threads in
  ascending id order, so every variant is produced **exactly once → no
  repeats**, structurally (no visited set needed).
* A leaf is classified **COMPLETE** (all threads finished), **DEADLOCK**
  (someone blocked forever, e.g. `INPUT` with no input left), or **OVER_BOUND**
  (the path hit the per-path operation cap — this is how **graph cycles /
  non-termination are kept finite**).
* Output is compared as the **exact ordered sequence** of printed integers.

### Determinism

`Analyze determinism` reports whether the output is uniquely determined by the
input (verdict keyed on output equality across all complete variants, with
structural / bound caveats surfaced). Example: two threads that print 0 and 1
→ **nondeterministic**, two distinct outputs `[0,1]` and `[1,0]`.

### Enumeration + the K-percentage (the interrupt question)

For a nondeterministic program you can **enumerate different executions** of
the same test (`Start` / `Stop`), **without repeats**. At any moment press
`Stop`, choose **K (1..20)**, and `Show % verified` reports:

* **denominator** `Den(K)` = number of COMPLETE variants whose op-count ≤ K
  (computed by an independent, memoised bounded DFS using the *same*
  semantics), and
* **numerator** `Num(K)` = COMPLETE variants with op-count ≤ K **enumerated and
  output-checked so far**,
* **percentage** = `100·Num/Den`. If `Den == 0` it reports **N/A** ("no
  complete variants of ≤K operations") rather than a misleading 100%.

Deadlocked and over-bound executions have no "output after all threads finish",
so they are excluded from both counts and reported separately.

CLI equivalent (Ctrl-C to interrupt interactively, or scripted):

```bash
# enumerate variants for a test, auto-interrupt after 10, ask K=8
python3 -m g2t.cli enumerate examples/race_0_1.json \
        --test examples/race_0_1_tests.json --index 0 --interrupt-after 10 --k 8
#   -> verified 10 / 70 complete variants with <=K ops  ->  14.2857%

# run a whole test set, enumerating all interleavings
python3 -m g2t.cli test examples/branch_demo.json examples/branch_demo_tests.json
```

---

## File formats (JSON)

**Project** — `{"version":1,"flowcharts":[{ "name", "blocks":[...], "edges":[...] }]}`
where a block has `id,kind,x,y` plus kind-specific fields
(`target/source_kind/source_var/source_const`, `var`, `cmp/const`), and an edge
is `{src,dst,branch}` (`branch` is `null`, or `true`/`false` for a Branch
block's two edges).

**Test set** — `{"version":1,"tests":[{"name","input":[...],"expected":[...]}]}`.

---

## Examples (in `examples/`)

| file | what it shows |
|------|---------------|
| `echo.json` | one thread: `INPUT x; PRINT x` (deterministic) |
| `race_0_1.json` | the spec's example: two threads print 0 and 1 (nondeterministic) |
| `shared_race.json` | write-write race on a shared variable → 4 distinct outputs |
| `branch_demo.json` | `INPUT x; if x<10 print 0 else print 1` (branching) |
| `*_tests.json` | matching test sets |

---

## Project layout

```
main.py              GUI launcher
selftest.py          headless correctness tests for the engine
g2t/
  model.py           blocks / edges / flowchart / project + JSON + validation
  interpreter.py     stepping engine (operational semantics, one block = one op)
  tester.py          interleaving enumeration, K-percentage, determinism (Point 3)
  translator.py      flowcharts -> multithreaded Python (Point 2)
  editor.py          Tkinter editor + Translate/Testing panels (Point 1)
  cli.py             headless command-line front-end
examples/            sample projects + test sets (+ generator)
```
