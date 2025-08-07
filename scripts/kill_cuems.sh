#!/bin/bash
# CUEMS Process Killer Script
# Kills all CUEMS-related processes using escalating force

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Process patterns to look for
PATTERNS=(
    "cuems"
    "pytest.*cuems"
    "python.*cuems"
    "audioplayer-cuems"
    "videoplayer-cuems"
    "dmxplayer-cuems"
    "ControllerEngine"
    "NodeEngine"
    "OssiaServer"
    "EditorWsServer"
)

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  -f, --force     Skip gentle termination, go straight to kill -9"
    echo "  -l, --list      List CUEMS processes and exit"
    echo "  -n, --dry-run   Show what would be killed without killing"
    echo "  -h, --help      Show this help"
}

list_cuems_processes() {
    echo -e "${YELLOW}Looking for CUEMS processes...${NC}"
    
    local found=0
    for pattern in "${PATTERNS[@]}"; do
        local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            echo -e "${GREEN}Pattern '$pattern':${NC}"
            for pid in $pids; do
                if ps -p $pid > /dev/null 2>&1; then
                    local info=$(ps -p $pid -o pid,ppid,pgid,stat,comm,args --no-headers)
                    echo "  PID $info"
                    found=1
                fi
            done
        fi
    done
    
    if [[ $found -eq 0 ]]; then
        echo -e "${GREEN}No CUEMS processes found${NC}"
    fi
    
    return $found
}

kill_process_gentle() {
    local pid=$1
    local name=$2
    
    echo -e "${YELLOW}Gently terminating PID $pid ($name)...${NC}"
    
    if kill -TERM "$pid" 2>/dev/null; then
        # Wait up to 5 seconds for process to die
        for i in {1..5}; do
            if ! ps -p "$pid" > /dev/null 2>&1; then
                echo -e "${GREEN}✓ Process $pid terminated gracefully${NC}"
                return 0
            fi
            sleep 1
        done
        echo -e "${YELLOW}⚠ Process $pid didn't terminate within 5s${NC}"
        return 1
    else
        echo -e "${RED}✗ Failed to send TERM signal to $pid${NC}"
        return 1
    fi
}

kill_process_force() {
    local pid=$1
    local name=$2
    
    echo -e "${RED}Force killing PID $pid ($name)...${NC}"
    
    # Try different kill signals
    local signals=("INT" "KILL")
    
    for sig in "${signals[@]}"; do
        if kill -$sig "$pid" 2>/dev/null; then
            sleep 1
            if ! ps -p "$pid" > /dev/null 2>&1; then
                echo -e "${GREEN}✓ Process $pid killed with SIG$sig${NC}"
                return 0
            fi
        fi
    done
    
    # Try killing process group
    echo -e "${YELLOW}Trying to kill process group...${NC}"
    local pgid=$(ps -p "$pid" -o pgid --no-headers 2>/dev/null | tr -d ' ')
    if [[ -n "$pgid" ]] && [[ "$pgid" != "1" ]]; then
        if kill -KILL -"$pgid" 2>/dev/null; then
            sleep 1
            if ! ps -p "$pid" > /dev/null 2>&1; then
                echo -e "${GREEN}✓ Process group killed${NC}"
                return 0
            fi
        fi
    fi
    
    echo -e "${RED}✗ Failed to kill process $pid${NC}"
    return 1
}

kill_cuems_processes() {
    local force_mode=$1
    local dry_run=$2
    
    echo -e "${YELLOW}=== CUEMS Process Killer ===${NC}"
    
    # Collect all PIDs
    local all_pids=()
    local pid_info=()
    
    for pattern in "${PATTERNS[@]}"; do
        local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        for pid in $pids; do
            if ps -p $pid > /dev/null 2>&1; then
                local comm=$(ps -p $pid -o comm --no-headers)
                all_pids+=($pid)
                pid_info[$pid]="$comm"
            fi
        done
    done
    
    # Remove duplicates
    local unique_pids=($(printf "%s\n" "${all_pids[@]}" | sort -u))
    
    if [[ ${#unique_pids[@]} -eq 0 ]]; then
        echo -e "${GREEN}No CUEMS processes found${NC}"
        return 0
    fi
    
    echo -e "${YELLOW}Found ${#unique_pids[@]} CUEMS processes:${NC}"
    for pid in "${unique_pids[@]}"; do
        local info=$(ps -p $pid -o pid,ppid,stat,comm,args --no-headers 2>/dev/null || echo "$pid ? ? ? ?")
        echo "  $info"
    done
    
    if [[ "$dry_run" == "true" ]]; then
        echo -e "${YELLOW}(Dry run - no processes killed)${NC}"
        return 0
    fi
    
    echo -e "${YELLOW}Killing processes...${NC}"
    
    local success_count=0
    local total_count=${#unique_pids[@]}
    
    # Sort PIDs by parent-child relationship (children first)
    # This is a simple approximation - just sort by PID descending
    local sorted_pids=($(printf "%s\n" "${unique_pids[@]}" | sort -nr))
    
    for pid in "${sorted_pids[@]}"; do
        if ! ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ Process $pid already gone${NC}"
            ((success_count++))
            continue
        fi
        
        local name="${pid_info[$pid]:-unknown}"
        local killed=false
        
        if [[ "$force_mode" != "true" ]]; then
            if kill_process_gentle "$pid" "$name"; then
                killed=true
            fi
        fi
        
        if [[ "$killed" != "true" ]]; then
            if kill_process_force "$pid" "$name"; then
                killed=true
            fi
        fi
        
        if [[ "$killed" == "true" ]]; then
            ((success_count++))
        fi
    done
    
    echo -e "${YELLOW}=== Summary ===${NC}"
    echo -e "${GREEN}Successfully killed: $success_count/$total_count processes${NC}"
    
    # Check for remaining processes
    local remaining=()
    for pattern in "${PATTERNS[@]}"; do
        local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        remaining+=($pids)
    done
    
    if [[ ${#remaining[@]} -gt 0 ]]; then
        echo -e "${RED}⚠ ${#remaining[@]} processes still running:${NC}"
        for pid in "${remaining[@]}"; do
            local info=$(ps -p $pid -o pid,comm --no-headers 2>/dev/null || echo "$pid ?")
            echo -e "${RED}  $info${NC}"
        done
        return 1
    else
        echo -e "${GREEN}✓ All CUEMS processes terminated${NC}"
        return 0
    fi
}

# Parse command line arguments
FORCE=false
LIST_ONLY=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--force)
            FORCE=true
            shift
            ;;
        -l|--list)
            LIST_ONLY=true
            shift
            ;;
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

# Main execution
if [[ "$LIST_ONLY" == "true" ]]; then
    list_cuems_processes
    exit $?
fi

kill_cuems_processes "$FORCE" "$DRY_RUN"
exit $? 
