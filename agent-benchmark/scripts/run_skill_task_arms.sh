#!/usr/bin/env bash
# Executable-task treatment experiment: run every selected terminal-bench task
# through a coding agent twice — without-skill vs with-skill — and report the
# pass-rate delta. The verifier (deterministic pass/fail) is the metric; no LLM
# judge is involved for tasks.
#
# Solver: claude-code CLI (`claude -p`). Point it at any model via $SOLVER_MODEL
# (e.g. a Bedrock/Vertex Haiku inference-profile id). Skill arm prepends a
# SKILL.md to the task instruction.
#
# Usage:
#   SOLVER_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0 \
#   scripts/run_skill_task_arms.sh [out_dir] [skill_file] [task1 task2 ...]
#
# Defaults: out=results/skill-task-arms, skill=data/skills/intel-performance-patterns/SKILL.md,
# tasks = the 11 intel-perf-* tasks. N=1 run per cell; raise REPEATS for variance.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."

OUT="${1:-results/skill-task-arms}"
SKILL="${2:-data/skills/intel-performance-patterns/SKILL.md}"
# Drop the consumed positionals one at a time so calling with 0 or 1 arg does
# not leave them in $@ (a bare `shift 2` fails and mis-reads $1 as a task).
[ "$#" -ge 1 ] && shift
[ "$#" -ge 1 ] && shift
TASKS=("$@")
if [ "${#TASKS[@]}" -eq 0 ]; then
  TASKS=(serial-accumulator false-sharing shared-counter branch-mispredict
         missing-restrict ttas-spinlock cv-herd crc32c mutex-rwlock simd-sort
         hotspot-report)
fi
MODEL="${SOLVER_MODEL:-}"
REPEATS="${REPEATS:-1}"
RESULTS="$OUT/results.tsv"
mkdir -p "$OUT"; : > "$RESULTS"

for arm in noskill skill; do
  EXTRA=""; [ "$arm" = skill ] && EXTRA="$SKILL"
  for t in "${TASKS[@]}"; do
    for run in $(seq 1 "$REPEATS"); do
      d="$OUT/${arm}/${t}/run${run}"
      r=$(timeout 800 bash "$HERE/run_task.sh" claude \
            "terminal-bench-tasks/intel-perf-$t" "$d" "$MODEL" "$EXTRA" 2>/dev/null | tail -1)
      printf "%s\t%s\t%s\t%s\n" "$arm" "$t" "$run" "${r:-ERR}" | tee -a "$RESULTS"
    done
  done
done

echo "=== PASS-RATE BY ARM ==="
awk -F'\t' '{c[$1]++; if($4==1)p[$1]++} END{for(a in c)printf "%-8s %d/%d = %.0f%%\n",a,p[a]+0,c[a],100*p[a]/c[a]}' "$RESULTS"
