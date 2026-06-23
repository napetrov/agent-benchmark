#!/usr/bin/env bash
# Docker harness for terminal-bench-tasks/ — solve a task, then verify, emit reward.
#
# Two solver modes (no Harbor needed; the agent_benchmarks task runner just reads
# the reward file we drop in OUTPUT_DIR):
#   oracle  — apply the task's own solution/solve.sh (free, no LLM). Validates
#             that the task + Docker image + verifier work end to end.
#   claude  — run `claude -p` headless inside the built image to solve from the
#             instruction, then verify. This is the with/without-skill arm.
#
# Contract per task dir:
#   environment/Dockerfile  builds image with the SLOW baseline at /app
#   solution/solve.sh       oracle fix (writes optimized source + binary)
#   tests/{test.sh,*.py}    verifier; test.sh writes /logs/verifier/reward.txt (1/0)
#   instruction.md          the problem statement handed to an LLM solver
#
# Usage:
#   run_task.sh <mode:oracle|claude> <task_dir> <output_dir> [model] [extra_prompt_file]
#
# Reward: written to <output_dir>/reward.txt as "1" (pass) or "0" (fail), which
# the CommandHarness picks up via `command:` template.
set -uo pipefail

MODE="${1:?mode: oracle|claude}"
TASK_DIR="$(cd "${2:?task_dir}" && pwd)"
OUT_DIR="${3:?output_dir}"
MODEL="${4:-}"
EXTRA_PROMPT_FILE="${5:-}"        # optional: skill text prepended to the prompt (skill arm)

TASK_NAME="$(basename "$TASK_DIR")"
IMAGE="agent-bench/${TASK_NAME}:latest"
CONTAINER="abrun-${TASK_NAME}-$$"
mkdir -p "$OUT_DIR"
REWARD_FILE="$OUT_DIR/reward.txt"
LOG="$OUT_DIR/run.log"
echo "0" > "$REWARD_FILE"   # default fail; overwritten on pass

log() { echo "[$(basename "$0")] $*" | tee -a "$LOG" ; }

# ── 1. Build image (slow baseline lives at /app) ─────────────────────────────
# apt in the Dockerfile needs the corporate proxy; docker build does not inherit
# host proxy env, so pass it through + use host networking for the build only.
log "build $IMAGE"
BUILD_ARGS=(--network host)
for v in http_proxy https_proxy no_proxy HTTP_PROXY HTTPS_PROXY NO_PROXY; do
    [ -n "${!v:-}" ] && BUILD_ARGS+=(--build-arg "$v=${!v}")
done
if ! docker build -q "${BUILD_ARGS[@]}" -t "$IMAGE" \
        -f "$TASK_DIR/environment/Dockerfile" "$TASK_DIR/environment" >>"$LOG" 2>&1; then
    log "BUILD FAILED — see $LOG"; exit 1
fi

# ── 2. Start a long-lived container so solver + verifier share /app state ─────
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" --network none --cpus 4 --memory 2g \
    "$IMAGE" sleep 1200 >>"$LOG" 2>&1
trap 'docker rm -f "$CONTAINER" >/dev/null 2>&1 || true' EXIT

# ── 3. Solve ─────────────────────────────────────────────────────────────────
case "$MODE" in
  oracle)
    log "solve: oracle (solution/solve.sh)"
    # Run as root: some images set `USER bench` who can write /app but not / or
    # /logs. The verifier is user-agnostic, so root keeps solve + verify uniform.
    docker cp "$TASK_DIR/solution/solve.sh" "$CONTAINER:/solve.sh" >>"$LOG" 2>&1
    docker exec -u root "$CONTAINER" bash -lc "chmod +x /solve.sh && /solve.sh" >>"$LOG" 2>&1 \
        || { log "oracle solve.sh failed"; }
    ;;
  claude)
    log "solve: claude -p (model=${MODEL:-default})"
    # Snapshot /app to host, let claude edit it on the host (claude runs on host,
    # not in the container), copy back, then verify in-container.
    WORK="$OUT_DIR/work"; rm -rf "$WORK"; mkdir -p "$WORK"
    docker cp "$CONTAINER:/app/." "$WORK/" >>"$LOG" 2>&1
    # Skill arm: copy the whole skill directory next to the work tree so the
    # agent can Read the files SKILL.md references (triggers/, patterns/,
    # guidelines/) — prepending SKILL.md text alone would point it at files that
    # are not present, making the treatment incomplete.
    SKILL_NOTE=""
    if [ -n "$EXTRA_PROMPT_FILE" ] && [ -f "$EXTRA_PROMPT_FILE" ]; then
        SKILL_SRC_DIR="$(cd "$(dirname "$EXTRA_PROMPT_FILE")" && pwd)"
        cp -r "$SKILL_SRC_DIR" "$WORK/.skill" >>"$LOG" 2>&1
        SKILL_NOTE="A performance skill is available at ./.skill/ (start with ./.skill/$(basename "$EXTRA_PROMPT_FILE")). Read the files it references before fixing."
    fi
    PROMPT_FILE="$OUT_DIR/prompt.txt"
    {
      [ -n "$SKILL_NOTE" ] && echo "$SKILL_NOTE" && echo
      echo "Solve this coding task. Edit files in the current directory only."
      echo "When done, leave the optimized source and any required outputs in place."
      echo
      cat "$TASK_DIR/instruction.md"
    } > "$PROMPT_FILE"
    MODEL_ARG=(); [ -n "$MODEL" ] && MODEL_ARG=(--model "$MODEL")
    ( cd "$WORK" && timeout 600 claude -p "$(cat "$PROMPT_FILE")" \
        --dangerously-skip-permissions \
        --allowedTools "Read" "Edit" "Write" "Bash" \
        "${MODEL_ARG[@]}" ) >>"$LOG" 2>&1 || log "claude solver exited non-zero"
    rm -rf "$WORK/.skill"   # don't ship the skill files into /app for the verifier
    docker cp "$WORK/." "$CONTAINER:/app/" >>"$LOG" 2>&1
    # The agent runs on the HOST (newer glibc); a host-built binary fails to run
    # in the older task image. Re-compile inside the container using the exact
    # compile command(s) documented in instruction.md so the binary matches the
    # runtime. Match g++ and gcc (C tasks like missing-restrict use gcc).
    grep -oE '(g\+\+|gcc) [^`]*-o /app/[^ `]*' "$TASK_DIR/instruction.md" | while read -r cc; do
        log "recompile in-container: $cc"
        docker exec -u root "$CONTAINER" bash -lc "$cc" >>"$LOG" 2>&1 || log "recompile failed: $cc"
    done
    ;;
  *) log "unknown mode $MODE"; exit 2 ;;
esac

# ── 4. Verify (writes /logs/verifier/reward.txt inside container) ────────────
log "verify"
docker cp "$TASK_DIR/tests" "$CONTAINER:/tests" >>"$LOG" 2>&1
docker exec -u root "$CONTAINER" bash -lc "mkdir -p /logs/verifier && chmod +x /tests/test.sh && /tests/test.sh" >>"$LOG" 2>&1
VEXIT=$?

# ── 5. Pull reward ───────────────────────────────────────────────────────────
if docker cp "$CONTAINER:/logs/verifier/reward.txt" "$OUT_DIR/reward.txt" >>"$LOG" 2>&1; then
    log "reward=$(cat "$OUT_DIR/reward.txt")"
else
    log "no reward file; verifier exit=$VEXIT"
    [ "$VEXIT" -eq 0 ] && echo "1" > "$REWARD_FILE"
fi

cat "$OUT_DIR/reward.txt"
