---
name: fastcontext
description: Locate the right files and line ranges before answering, editing, reviewing, or debugging unfamiliar code — explore first, then act on a compact set of citations instead of repeating broad searches.
---
# FastContext: explore before you act

Use this skill whenever a task touches code or docs you have not already read in
this session and the answer depends on **more than one file** or on
**cross-module logic**. Find the relevant locations *first*, commit to them as a
compact list of citations, then read narrow windows around those citations
instead of scanning the whole repository.

This skill is about *context acquisition*, not about the fix itself. Doing it
well makes the rest of the task cheaper and more accurate: fewer wasted reads,
tighter edits, less frontier-model token spend.

## When to use it

- Before answering a "where / how is X implemented?" question.
- Before editing, refactoring, or debugging code you have not localized yet.
- Before reviewing a change whose blast radius you have not mapped.

## When to skip it

- You already have the file and line range in hand.
- The task is a single, known file you have just read.
- A one-shot lookup you can answer without cross-referencing.

## How to explore

1. Search by **intent**, not by dumping files: grep for the symbol, the error
   string, the config key, or the API name — scoped to a directory when you can.
2. Run independent searches in parallel rather than one-at-a-time.
3. Read only the **narrow window** each hit points at, not the whole file.
4. Stop when you can name the locations that matter. Do not keep searching to
   feel thorough — converge.

## Commit to a citation block

When you have located the evidence, write it as a compact, machine-readable
block of `path:start-end` citations (one per line):

```text
<final_answer>
src/pkg/module.py:42-58
tests/test_module.py:101-119
docs/guide.md:120-180
</final_answer>
```

Rules for good citations:

- Cite the **tightest range** that contains the relevant logic — a function or a
  few lines, not a whole file. Whole-file citations are not localization.
- Include the supporting evidence the task needs: the implementation **and** its
  test or caller, the doc **and** the example.
- Do not pad the list. Extra, loosely-related files lower precision and make the
  next reader distrust the set.

## After exploring

- Read the narrow windows your citations point at; do **not** re-run the broad
  search you already did.
- Trust the located set. Re-doing exploration from scratch wastes tokens and is
  the dominant failure mode this skill exists to prevent.
