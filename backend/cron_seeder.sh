#!/usr/bin/env bash
# ==============================================================================
# pipeline/cron_seeder.sh
# AeroSync-India | Daily Flight Inventory Seeder — Cron Wrapper
# ==============================================================================
#
# PURPOSE
# ───────
# Wraps daily_seeder.py for cron execution. Handles:
#   - Python venv activation
#   - Environment variable injection (.env file)
#   - Log rotation (keeps last 30 log files)
#   - Lock file to prevent overlapping runs
#   - Exit code propagation for cron email alerts
#
# CRON INSTALLATION
# ─────────────────
# Run once to install:
#     chmod +x pipeline/cron_seeder.sh
#     crontab -e
#
# Add this line (runs at 02:00 IST = 20:30 UTC previous day):
#     30 20 * * * /path/to/aerosync/pipeline/cron_seeder.sh >> /var/log/aerosync/cron.log 2>&1
#
# MANUAL TEST RUN
# ───────────────
#     bash pipeline/cron_seeder.sh
#
# ENVIRONMENT VARIABLES (set in .env or exported before cron runs)
# ─────────────────────────────────────────────────────────────────
#     MONGO_URI       MongoDB connection string (default: mongodb://localhost:27017)
#     MONGO_DB_NAME   Database name            (default: aerosync_india)
#     MONGO_MAX_POOL  Max connection pool size (default: 20)
#     MONGO_TLS       Enable TLS               (default: false)
#     AEROSYNC_ROOT   Repo root directory      (default: script's parent dir)
#     VENV_PATH       Python venv path         (default: $AEROSYNC_ROOT/.venv)
#     LOG_DIR         Log output directory     (default: $AEROSYNC_ROOT/logs)
#     LOG_RETAIN_DAYS Number of log files kept (default: 30)
# ==============================================================================

set -euo pipefail   # Exit on error, undefined var, or pipe failure

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------

# Resolve repo root relative to this script's location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AEROSYNC_ROOT="${AEROSYNC_ROOT:-$(dirname "$SCRIPT_DIR")}"

# Python virtual environment
VENV_PATH="${VENV_PATH:-$AEROSYNC_ROOT/.venv}"
PYTHON_BIN="$VENV_PATH/bin/python"

# Log directory and retention
LOG_DIR="${LOG_DIR:-$AEROSYNC_ROOT/logs}"
LOG_RETAIN_DAYS="${LOG_RETAIN_DAYS:-30}"
TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/daily_seeder_${TIMESTAMP}.log"

# Lock file — prevents two cron instances running simultaneously
LOCK_FILE="/tmp/aerosync_daily_seeder.lock"

# Seeder module path
SEEDER_MODULE="pipeline.daily_seeder"

# .env file (optional — loaded if it exists)
ENV_FILE="$AEROSYNC_ROOT/.env"

# ------------------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------------------

log() {
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] ERROR: $*" | tee -a "$LOG_FILE" >&2
}

cleanup() {
    local exit_code=$?
    # Always release the lock file on exit
    if [[ -f "$LOCK_FILE" ]]; then
        rm -f "$LOCK_FILE"
        log "Lock file released."
    fi
    if [[ $exit_code -ne 0 ]]; then
        log_error "Seeder exited with code $exit_code."
    fi
    exit $exit_code
}

# Register cleanup on any exit (normal, error, signal)
trap cleanup EXIT

# ------------------------------------------------------------------------------
# LOCK FILE — prevent overlapping cron runs
# ------------------------------------------------------------------------------
if [[ -f "$LOCK_FILE" ]]; then
    LOCK_PID="$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")"
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        log_error "Another seeder instance is already running (PID $LOCK_PID). Exiting."
        exit 1
    else
        log "Stale lock file found (PID $LOCK_PID no longer running). Removing."
        rm -f "$LOCK_FILE"
    fi
fi

# Claim the lock
echo $$ > "$LOCK_FILE"

# ------------------------------------------------------------------------------
# SETUP
# ------------------------------------------------------------------------------

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

log "========================================================================"
log "AeroSync-India Daily Seeder — cron_seeder.sh"
log "Host     : $(hostname)"
log "User     : $(whoami)"
log "Repo root: $AEROSYNC_ROOT"
log "Log file : $LOG_FILE"
log "========================================================================"

# Load .env file if it exists (exports vars into this shell session)
if [[ -f "$ENV_FILE" ]]; then
    log "Loading environment from $ENV_FILE"
    # shellcheck disable=SC1090
    set -a
    source "$ENV_FILE"
    set +a
else
    log "No .env file found at $ENV_FILE — using exported environment variables."
fi

# Log active MongoDB config (mask password in URI)
MASKED_URI="${MONGO_URI:-mongodb://localhost:27017}"
MASKED_URI="$(echo "$MASKED_URI" | sed 's|://[^:]*:[^@]*@|://*****:*****@|g')"
log "MongoDB URI  : $MASKED_URI"
log "MongoDB DB   : ${MONGO_DB_NAME:-aerosync_india}"

# ------------------------------------------------------------------------------
# PYTHON ENVIRONMENT CHECK
# ------------------------------------------------------------------------------

if [[ ! -f "$PYTHON_BIN" ]]; then
    log_error "Python binary not found at $PYTHON_BIN"
    log_error "Create the venv first:  python3 -m venv $VENV_PATH && pip install -r requirements.txt"
    exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" --version 2>&1)"
log "Python: $PYTHON_VERSION ($PYTHON_BIN)"

# Verify required packages are importable
"$PYTHON_BIN" -c "import motor, pydantic, pymongo" 2>>"$LOG_FILE" || {
    log_error "Required packages (motor, pydantic, pymongo) not installed in venv."
    log_error "Run: $VENV_PATH/bin/pip install -r $AEROSYNC_ROOT/requirements.txt"
    exit 1
}

# ------------------------------------------------------------------------------
# RUN SEEDER
# ------------------------------------------------------------------------------

log "Starting seeder: python -m $SEEDER_MODULE"
log "------------------------------------------------------------------------"

START_TS="$(date +%s)"

# Run from repo root so relative imports and config paths resolve correctly
cd "$AEROSYNC_ROOT"

"$PYTHON_BIN" -m "$SEEDER_MODULE" 2>&1 | tee -a "$LOG_FILE"
SEEDER_EXIT="${PIPESTATUS[0]}"

END_TS="$(date +%s)"
ELAPSED=$(( END_TS - START_TS ))

log "------------------------------------------------------------------------"

if [[ "$SEEDER_EXIT" -eq 0 ]]; then
    log "Seeder completed successfully in ${ELAPSED}s."
else
    log_error "Seeder FAILED with exit code $SEEDER_EXIT after ${ELAPSED}s."
fi

# ------------------------------------------------------------------------------
# LOG ROTATION — keep last N daily log files
# ------------------------------------------------------------------------------

log "Running log rotation (retaining last $LOG_RETAIN_DAYS files)..."

# Find and delete log files older than the retention window
DELETED_COUNT=0
while IFS= read -r old_log; do
    rm -f "$old_log"
    DELETED_COUNT=$(( DELETED_COUNT + 1 ))
done < <(
    ls -t "$LOG_DIR"/daily_seeder_*.log 2>/dev/null \
    | tail -n +"$((LOG_RETAIN_DAYS + 1))"
)

if [[ "$DELETED_COUNT" -gt 0 ]]; then
    log "Log rotation: removed $DELETED_COUNT old log file(s)."
fi

# ------------------------------------------------------------------------------
# FINAL STATUS
# ------------------------------------------------------------------------------

log "========================================================================"
log "cron_seeder.sh finished | exit=$SEEDER_EXIT | elapsed=${ELAPSED}s"
log "========================================================================"

exit "$SEEDER_EXIT"
