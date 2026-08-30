#!/usr/bin/env bash
#
# WARFRAME Wiki Module Sync Workflow
# Orchestrates request.py, convert_module.js, and attribution.py
#
# Usage:
#   bash workflow.sh
#   bash workflow.sh --dry-run
#

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Directories
DATA_DIR="data"
LOG_DIR="${DATA_DIR}/logs"
CONFIG_FILE="config.ini"
STALE_MODULES="stale_modules.json"
IGNORE_MODULES="ignore_modules.json"
CONSECUTIVE_ERRORS_FILE="${DATA_DIR}/.consecutive_errors"
DISABLE_FILE=".github/disable-action.md"

# Counters
REQUEST_START_TIME=0
REQUEST_END_TIME=0
CONVERT_START_TIME=0
CONVERT_END_TIME=0
WORKFLOW_START_TIME=0
WORKFLOW_END_TIME=0

# Functions
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message"
}

log_info() {
    log "INFO" "$@"
}

log_warn() {
    log "WARN" "$@"
}

log_error() {
    log "ERROR" "$@"
}

format_duration() {
    local seconds=$1
    local mins=$((seconds / 60))
    local secs=$((seconds % 60))
    if [ $mins -ge 1 ]; then
        echo "${mins}m ${secs}s"
    else
        echo "${secs}s"
    fi
}

cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Workflow failed with exit code $exit_code"
    fi
    exit $exit_code
}

trap cleanup EXIT

check_github_disable() {
    if [ -f "$DISABLE_FILE" ]; then
        log_error "GitHub Action is disabled. See $DISABLE_FILE"
        cat "$DISABLE_FILE"
        exit 4
    fi
}

init_directories() {
    mkdir -p "$LOG_DIR"
    mkdir -p "${DATA_DIR}/json"
    
    # Initialize consecutive errors counter if not exists
    if [ ! -f "$CONSECUTIVE_ERRORS_FILE" ]; then
        echo "0" > "$CONSECUTIVE_ERRORS_FILE"
    fi
}

generate_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        log_info "Generating default configuration file: $CONFIG_FILE"
        cat > "$CONFIG_FILE" << 'EOF'
# WARFRAME Wiki Module Mirror Configuration
# Generated on first run - customize as needed

[wiki]
# WARFRAME Wiki API settings
base_url = https://wiki.warframe.com
api_url = https://wiki.warframe.com/api.php
user_agent = WFModuleMirror/1.0 (your-contact@example.com)
rate_limit = 1.0  # seconds between API requests
staleness_hours = 24  # skip modules converted within this window

[conversion]
# Puppeteer conversion settings
timeout_ms = 60000  # per module conversion timeout
retry_delay_ms = 2000  # between retries
max_retries = 3
browser_timeout = 30000  # browser launch timeout

[paths]
# Directory paths
stale_modules = stale_modules.json
ignore_modules = ignore_modules.json
output_dir = data/json
metadata_dir = data/json
log_dir = data/logs

[github]
# GitHub Actions settings
max_consecutive_errors = 3  # disable action after this many crashes
notify_on_failure = true
EOF
        log_info "Configuration file created. Edit $CONFIG_FILE as needed."
    fi
}

run_request_py() {
    log_info "Starting request.py..."
    REQUEST_START_TIME=$(date +%s)
    
    # Run request.py and capture output (tee for live visibility)
    local output
    output=$(python3 request.py 2>&1 | tee /dev/tty) || {
        local exit_code=$?
        log_error "request.py failed with exit code $exit_code"
        log_error "Output:"
        echo "$output" | sed 's/^/  /'

        # Update consecutive errors
        local current_errors
        current_errors=$(cat "$CONSECUTIVE_ERRORS_FILE")
        current_errors=$((current_errors + 1))
        echo "$current_errors" > "$CONSECUTIVE_ERRORS_FILE"

        log_error "Consecutive errors: $current_errors"

        return $exit_code
    }

    REQUEST_END_TIME=$(date +%s)
    local request_duration=$((REQUEST_END_TIME - REQUEST_START_TIME))

    log_info "request.py completed successfully"
    log_info "Duration: ${request_duration}s"
    
    # Reset consecutive errors on success
    echo "0" > "$CONSECUTIVE_ERRORS_FILE"
    
    return 0
}

run_convert_module_js() {
    log_info "Starting convert_module.js..."
    CONVERT_START_TIME=$(date +%s)
    
    if [ ! -f "$STALE_MODULES" ]; then
        log_warn "No stale_modules.json found. Nothing to convert."
        CONVERT_END_TIME=$(date +%s)
        return 2
    fi
    
    # Check if stale_modules.json is empty
    local module_count
    module_count=$(python3 -c "import json; data=json.load(open('$STALE_MODULES')); print(len(data))" 2>/dev/null || echo "0")
    
    if [ "$module_count" -eq 0 ]; then
        log_info "No modules to convert (stale_modules.json is empty)"
        CONVERT_END_TIME=$(date +%s)
        return 2
    fi
    
    log_info "Converting $module_count modules..."
    
    # Run convert_module.js (tee for live visibility)
    local output
    output=$(node convert_module.js --batch --pages "$STALE_MODULES" 2>&1 | tee /dev/tty) || {
        local exit_code=$?
        log_error "convert_module.js failed with exit code $exit_code"
        log_error "Output:"
        echo "$output" | sed 's/^/  /'

        # Update consecutive errors
        local current_errors
        current_errors=$(cat "$CONSECUTIVE_ERRORS_FILE")
        current_errors=$((current_errors + 1))
        echo "$current_errors" > "$CONSECUTIVE_ERRORS_FILE"

        log_error "Consecutive errors: $current_errors"

        # Check if we should disable GitHub Action
        local max_errors
        max_errors=$(grep -A5 '\[github\]' "$CONFIG_FILE" | grep 'max_consecutive_errors' | cut -d'=' -f2 | tr -d ' ')
        if [ -n "$max_errors" ] && [ "$current_errors" -ge "$max_errors" ]; then
            log_error "Maximum consecutive errors reached ($current_errors >= $max_errors). Disabling GitHub Action."
            mkdir -p .github
            cat > "$DISABLE_FILE" << EOF
# Action Disabled
Disabled due to $current_errors consecutive errors.
Manual intervention required.
Disabled at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')
EOF
            return 4
        fi

        return $exit_code
    }

    CONVERT_END_TIME=$(date +%s)
    local convert_duration=$((CONVERT_END_TIME - CONVERT_START_TIME))

    log_info "convert_module.js completed successfully"
    log_info "Duration: ${convert_duration}s"
    
    # Reset consecutive errors on success
    echo "0" > "$CONSECUTIVE_ERRORS_FILE"
    
    return 0
}

generate_summary() {
    local request_duration=$1
    local convert_duration=$2
    local total_duration=$3
    
    log_info ""
    log_info "=================================="
    log_info "WORKFLOW SUMMARY"
    log_info "=================================="
    log_info "Request.py duration: $(format_duration $1)"
    log_info "Convert_module.js duration: $(format_duration $2)"
    log_info "Total workflow duration: $(format_duration $3)"
    log_info "=================================="
}

main() {
    local dry_run=false
    
    # Parse arguments
    for arg in "$@"; do
        case $arg in
            --dry-run)
                dry_run=true
                ;;
            *)
                log_warn "Unknown argument: $arg"
                ;;
        esac
    done
    
    WORKFLOW_START_TIME=$(date +%s)
    
    log_info "=================================="
    log_info "WARFRAME Wiki Module Sync Workflow"
    log_info "=================================="
    log_info "Start time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    log_info ""
    
    # Check if GitHub Action is disabled
    check_github_disable
    
    # Initialize
    init_directories
    generate_config
    
    if [ "$dry_run" = true ]; then
        log_info "DRY RUN MODE - No actual conversions will be performed"
        
        # Check if stale_modules.json exists
        if [ -f "$STALE_MODULES" ]; then
            local module_count
            module_count=$(python3 -c "import json; data=json.load(open('$STALE_MODULES')); print(len(data))" 2>/dev/null || echo "0")
            log_info "Would convert $module_count modules"
        else
            log_info "No stale_modules.json found"
        fi
        
        WORKFLOW_END_TIME=$(date +%s)
        local total_duration=$((WORKFLOW_END_TIME - WORKFLOW_START_TIME))
        generate_summary 0 0 $total_duration
        return 0
    fi
    
    # Run request.py
    local request_exit_code=0
    run_request_py || request_exit_code=$?
    
    if [ $request_exit_code -ne 0 ]; then
        log_error "Aborting workflow due to request.py failure"
        return $request_exit_code
    fi
    
    # Run convert_module.js
    local convert_exit_code=0
    run_convert_module_js || convert_exit_code=$?
    
    WORKFLOW_END_TIME=$(date +%s)
    local total_duration=$((WORKFLOW_END_TIME - WORKFLOW_START_TIME))
    
    # Generate summary
    local request_duration=$((REQUEST_END_TIME - REQUEST_START_TIME))
    local convert_duration=$((CONVERT_END_TIME - CONVERT_START_TIME))
    generate_summary $request_duration $convert_duration $total_duration
    
    # Return appropriate exit code
    if [ $convert_exit_code -eq 2 ]; then
        # No stale modules - not an error
        return 2
    elif [ $convert_exit_code -eq 4 ]; then
        # GitHub Action disabled
        return 4
    elif [ $convert_exit_code -ne 0 ]; then
        return $convert_exit_code
    fi
    
    return 0
}

# Run main function
main "$@"
