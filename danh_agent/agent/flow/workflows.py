"""
Predefined Analysis Scripts for Slurm Agent

These are SAFE, READ-ONLY analysis scripts.
NO dangerous commands (no scancel, hold, suspend, etc.)

Agent picks the right script based on user query.
Script runs a comprehensive sequence of commands and returns combined output.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum


class AnalysisCategory(str, Enum):
    JOBS = "jobs"           # Job-related analysis
    CLUSTER = "cluster"     # Cluster/resource analysis
    USER = "user"           # User account/usage analysis
    DEBUG = "debug"         # Debugging/troubleshooting


@dataclass
class AnalysisScript:
    """Predefined analysis script"""
    id: str                     # Unique ID
    name: str                   # Display name
    description: str            # What it does (for agent to understand)
    category: AnalysisCategory  # Category
    script: str                 # The actual shell commands (multi-line)
    

# ============================================================
# JOB ANALYSIS SCRIPTS
# ============================================================

ANALYZE_MY_JOBS = AnalysisScript(
    id="analyze_my_jobs",
    name="Full Job Analysis",
    description="Comprehensive analysis of user's current and recent jobs - shows running, pending, completed, and failed jobs with details",
    category=AnalysisCategory.JOBS,
    script='''#!/bin/bash
# Full Job Analysis Script
# Shows comprehensive view of user's jobs

echo "=========================================="
echo "JOB ANALYSIS FOR USER: $USER"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== CURRENT JOBS IN QUEUE ==="
squeue -u $USER -o "%.10i %.20j %.10P %.8T %.12M %.12l %.6D %.4C %R" 2>/dev/null || echo "No jobs in queue"

echo ""
echo "=== RUNNING JOBS DETAILS ==="
squeue -u $USER -t RUNNING -o "%.10i %.20j %.10P %.10M %.10L %.6D %.20S %.20N" 2>/dev/null || echo "No running jobs"

echo ""
echo "=== PENDING JOBS WITH REASONS ==="
squeue -u $USER -t PENDING -o "%.10i %.20j %.10P %.8Q %.20r" 2>/dev/null || echo "No pending jobs"

echo ""
echo "=== JOB HISTORY (LAST 7 DAYS) ==="
sacct -u $USER -S $(date -d '7 days ago' +%Y-%m-%d) -o JobID,JobName%20,Partition,State,ExitCode,Elapsed,MaxRSS,MaxVMSize,AllocCPUS,AllocGRES -X 2>/dev/null || echo "No job history"

echo ""
echo "=== FAILED JOBS (LAST 7 DAYS) ==="
sacct -u $USER -S $(date -d '7 days ago' +%Y-%m-%d) -s FAILED,TIMEOUT,OUT_OF_MEMORY,CANCELLED -o JobID,JobName%20,State,ExitCode,Elapsed,MaxRSS -X 2>/dev/null || echo "No failed jobs"

echo ""
echo "=== JOB STATISTICS SUMMARY ==="
echo "Total jobs (7 days):"
sacct -u $USER -S $(date -d '7 days ago' +%Y-%m-%d) -X --noheader | wc -l
echo "Completed:"
sacct -u $USER -S $(date -d '7 days ago' +%Y-%m-%d) -s COMPLETED -X --noheader | wc -l
echo "Failed/Error:"
sacct -u $USER -S $(date -d '7 days ago' +%Y-%m-%d) -s FAILED,TIMEOUT,OUT_OF_MEMORY -X --noheader | wc -l
'''
)

ANALYZE_FAILED_JOBS = AnalysisScript(
    id="analyze_failed_jobs",
    name="Failed Jobs Deep Analysis",
    description="Deep analysis of failed, timed out, and OOM jobs - identifies patterns and common failure reasons",
    category=AnalysisCategory.DEBUG,
    script='''#!/bin/bash
# Failed Jobs Deep Analysis
# Identifies failure patterns and reasons

echo "=========================================="
echo "FAILED JOBS ANALYSIS FOR: $USER"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== RECENT FAILED JOBS (LAST 14 DAYS) ==="
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s FAILED,TIMEOUT,OUT_OF_MEMORY,NODE_FAIL,CANCELLED \\
    -o JobID,JobName%25,Partition,State,ExitCode,Elapsed,Start,End,MaxRSS,ReqMem,AllocCPUS,AllocGRES -X 2>/dev/null

echo ""
echo "=== FAILURE BREAKDOWN BY TYPE ==="
echo "FAILED (exit code != 0):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s FAILED -X --noheader 2>/dev/null | wc -l
echo "TIMEOUT (exceeded time limit):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s TIMEOUT -X --noheader 2>/dev/null | wc -l
echo "OUT_OF_MEMORY (OOM killed):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s OUT_OF_MEMORY -X --noheader 2>/dev/null | wc -l
echo "NODE_FAIL (node crashed):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s NODE_FAIL -X --noheader 2>/dev/null | wc -l
echo "CANCELLED:"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s CANCELLED -X --noheader 2>/dev/null | wc -l

echo ""
echo "=== FAILURE BY PARTITION ==="
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s FAILED,TIMEOUT,OUT_OF_MEMORY -X \\
    -o Partition --noheader 2>/dev/null | sort | uniq -c | sort -rn

echo ""
echo "=== MEMORY ANALYSIS (for OOM prevention) ==="
echo "Jobs where MaxRSS approached ReqMem (potential OOM risks):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -o JobID,JobName%20,State,ReqMem,MaxRSS,MaxVMSize -X 2>/dev/null | head -20

echo ""
echo "=== EXIT CODE ANALYSIS ==="
echo "Common exit codes:"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s FAILED -o ExitCode --noheader 2>/dev/null | sort | uniq -c | sort -rn | head -10
echo ""
echo "Exit code meanings:"
echo "  0:0   = Success"
echo "  1:0   = General error"
echo "  2:0   = Misuse of command"
echo "  137:0 = SIGKILL (often OOM)"
echo "  139:0 = SIGSEGV (segfault)"
echo "  143:0 = SIGTERM (terminated)"
'''
)

ANALYZE_PENDING_JOBS = AnalysisScript(
    id="analyze_pending_jobs",
    name="Pending Jobs Analysis",
    description="Analyzes why jobs are pending - checks resource availability, queue position, and gives wait time estimates",
    category=AnalysisCategory.DEBUG,
    script='''#!/bin/bash
# Pending Jobs Analysis
# Why are jobs waiting and how long?

echo "=========================================="
echo "PENDING JOBS ANALYSIS FOR: $USER"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== YOUR PENDING JOBS ==="
squeue -u $USER -t PENDING -o "%.10i %.25j %.10P %.8Q %.6D %.4C %.10m %.30r" 2>/dev/null || echo "No pending jobs"

echo ""
echo "=== PENDING REASON BREAKDOWN ==="
squeue -u $USER -t PENDING -o "%r" --noheader 2>/dev/null | sort | uniq -c | sort -rn

echo ""
echo "=== YOUR QUEUE PRIORITY ==="
sprio -u $USER 2>/dev/null || echo "No priority info"

echo ""
echo "=== RESOURCE AVAILABILITY CHECK ==="
echo "Partition status:"
sinfo -o "%.15P %.10a %.6D %.6t %.10C %.10m %.20G" 2>/dev/null

echo ""
echo "=== JOBS AHEAD OF YOU (by partition) ==="
for part in $(squeue -u $USER -t PENDING -o "%P" --noheader 2>/dev/null | sort -u); do
    echo "Partition: $part"
    squeue -p $part -t PENDING --noheader 2>/dev/null | wc -l
    echo "jobs pending"
done

echo ""
echo "=== ESTIMATED WAIT TIME FACTORS ==="
echo "Running jobs on your target partitions:"
squeue -u $USER -t PENDING -o "%P" --noheader 2>/dev/null | sort -u | while read part; do
    echo "=== $part ==="
    squeue -p $part -t RUNNING -o "%.10i %.20j %.10M %.10L" 2>/dev/null | head -5
done

echo ""
echo "=== YOUR FAIR SHARE STANDING ==="
sshare -u $USER 2>/dev/null || echo "Fair share info not available"
'''
)


# ============================================================
# CLUSTER ANALYSIS SCRIPTS
# ============================================================

ANALYZE_CLUSTER_STATUS = AnalysisScript(
    id="analyze_cluster_status",
    name="Full Cluster Status",
    description="Complete cluster status - all partitions, nodes, resource utilization, and availability",
    category=AnalysisCategory.CLUSTER,
    script='''#!/bin/bash
# Full Cluster Status Analysis
# Complete overview of cluster health and resources

echo "=========================================="
echo "CLUSTER STATUS REPORT"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== PARTITION OVERVIEW ==="
sinfo -o "%.15P %.10a %.6D %.6t %.10C %.12m %.25G %.15l" 2>/dev/null

echo ""
echo "=== NODE STATUS SUMMARY ==="
echo "By state:"
sinfo -o "%t" --noheader 2>/dev/null | sort | uniq -c | sort -rn

echo ""
echo "=== DETAILED NODE STATUS ==="
sinfo -N -o "%.12N %.10P %.6t %.10C %.10m %.30G %.20E" 2>/dev/null

echo ""
echo "=== PROBLEMATIC NODES (down/drain) ==="
sinfo -t DOWN,DRAIN,DRAINING -o "%.12N %.10P %.6t %.50E" 2>/dev/null || echo "No problematic nodes"

echo ""
echo "=== RESOURCE UTILIZATION ==="
echo "Total CPUs in cluster:"
sinfo -o "%C" --noheader 2>/dev/null | head -1
echo "(Format: Allocated/Idle/Other/Total)"

echo ""
echo "=== GPU RESOURCES ==="
sinfo -o "%.12N %.10P %.6t %.30G" 2>/dev/null | grep -i gpu || echo "No GPU info"

echo ""
echo "=== QUEUE OVERVIEW ==="
echo "Jobs by state:"
squeue -o "%T" --noheader 2>/dev/null | sort | uniq -c | sort -rn

echo ""
echo "=== JOBS BY PARTITION ==="
squeue -o "%P" --noheader 2>/dev/null | sort | uniq -c | sort -rn

echo ""
echo "=== TOP RESOURCE USERS ==="
squeue -o "%u" --noheader 2>/dev/null | sort | uniq -c | sort -rn | head -10

echo ""
echo "=== SCHEDULER HEALTH ==="
sdiag 2>/dev/null | head -30 || echo "Scheduler diagnostics not available"
'''
)

ANALYZE_GPU_RESOURCES = AnalysisScript(
    id="analyze_gpu_resources",
    name="GPU Resources Analysis",
    description="Detailed GPU availability and usage - shows which GPUs are free, allocated, and queue depth for GPU jobs",
    category=AnalysisCategory.CLUSTER,
    script='''#!/bin/bash
# GPU Resources Deep Analysis
# Everything about GPU availability

echo "=========================================="
echo "GPU RESOURCES ANALYSIS"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== GPU PARTITION STATUS ==="
sinfo -p gpu -o "%.12N %.10P %.6t %.10C %.10m %.40G" 2>/dev/null || sinfo -o "%.12N %.10P %.6t %.10C %.10m %.40G" 2>/dev/null | grep -i gpu

echo ""
echo "=== GPU NODES BREAKDOWN ==="
sinfo -N -o "%.12N %.6t %.40G %.12m %.10C" 2>/dev/null | grep -E "(GRES|gpu)" | head -30

echo ""
echo "=== CURRENTLY RUNNING GPU JOBS ==="
squeue -t RUNNING -o "%.10i %.20j %.10u %.10P %.6D %.4C %.20b %.12M" 2>/dev/null | grep -E "(GRES|gpu|JOBID)" | head -20

echo ""
echo "=== PENDING GPU JOBS ==="
squeue -t PENDING -o "%.10i %.20j %.10u %.10P %.6D %.4C %.20b %.20r" 2>/dev/null | grep -E "(gpu|JOBID)" | head -20

echo ""
echo "=== GPU QUEUE DEPTH ==="
echo "Running GPU jobs:"
squeue -t RUNNING 2>/dev/null | grep -i gpu | wc -l
echo "Pending GPU jobs:"
squeue -t PENDING 2>/dev/null | grep -i gpu | wc -l

echo ""
echo "=== GPU USAGE BY USER ==="
squeue -t RUNNING -o "%u %b" 2>/dev/null | grep gpu | awk '{print $1}' | sort | uniq -c | sort -rn | head -10

echo ""
echo "=== AVAILABLE GPU NODES ==="
sinfo -t IDLE,MIXED -o "%.12N %.6t %.40G %.10C" 2>/dev/null | grep -E "(gpu|GRES)"

echo ""
echo "=== RECOMMENDATIONS ==="
echo "Check which GPU types are available:"
sinfo -o "%G" --noheader 2>/dev/null | tr ',' '\\n' | grep gpu | sort | uniq -c
'''
)

ANALYZE_PARTITION_COMPARISON = AnalysisScript(
    id="analyze_partition_comparison",
    name="Partition Comparison",
    description="Compare all partitions - which has shortest queue, most resources, best for different job types",
    category=AnalysisCategory.CLUSTER,
    script='''#!/bin/bash
# Partition Comparison Analysis
# Helps choose the best partition for a job

echo "=========================================="
echo "PARTITION COMPARISON"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== ALL PARTITIONS OVERVIEW ==="
sinfo -o "%.18P %.10a %.6D %.6t %.10C %.10m %.20G %.12l %.8p" 2>/dev/null

echo ""
echo "=== PARTITION DETAILS ==="
for part in $(sinfo -o "%P" --noheader 2>/dev/null | tr -d '*' | sort -u); do
    echo ""
    echo "--- $part ---"
    echo "Nodes: $(sinfo -p $part -o "%D" --noheader 2>/dev/null | head -1)"
    echo "State: $(sinfo -p $part -o "%a" --noheader 2>/dev/null | head -1)"
    echo "CPUs (A/I/O/T): $(sinfo -p $part -o "%C" --noheader 2>/dev/null | head -1)"
    echo "Memory: $(sinfo -p $part -o "%m" --noheader 2>/dev/null | head -1) MB per node"
    echo "Time limit: $(sinfo -p $part -o "%l" --noheader 2>/dev/null | head -1)"
    echo "Running jobs: $(squeue -p $part -t RUNNING --noheader 2>/dev/null | wc -l)"
    echo "Pending jobs: $(squeue -p $part -t PENDING --noheader 2>/dev/null | wc -l)"
done

echo ""
echo "=== QUEUE DEPTH BY PARTITION ==="
squeue -o "%P %T" --noheader 2>/dev/null | sort | uniq -c | sort -k2

echo ""
echo "=== RECOMMENDED PARTITIONS ==="
echo "Shortest queue (pending jobs):"
for part in $(sinfo -o "%P" --noheader 2>/dev/null | tr -d '*' | sort -u); do
    pending=$(squeue -p $part -t PENDING --noheader 2>/dev/null | wc -l)
    echo "$pending $part"
done | sort -n | head -5

echo ""
echo "Most available CPUs:"
sinfo -o "%P %C" --noheader 2>/dev/null | sort -t'/' -k2 -rn | head -5
'''
)


# ============================================================
# USER ANALYSIS SCRIPTS
# ============================================================

ANALYZE_MY_USAGE = AnalysisScript(
    id="analyze_my_usage",
    name="My Usage Statistics",
    description="Complete usage statistics - job history, resource consumption, fair share standing, efficiency metrics",
    category=AnalysisCategory.USER,
    script='''#!/bin/bash
# User Usage Statistics
# Complete picture of user's cluster usage

echo "=========================================="
echo "USAGE STATISTICS FOR: $USER"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== FAIR SHARE STANDING ==="
sshare -u $USER -l 2>/dev/null || echo "Fair share not available"

echo ""
echo "=== JOB COUNTS (Last 30 days) ==="
echo "Total jobs submitted:"
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -X --noheader 2>/dev/null | wc -l
echo ""
echo "By state:"
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -o State -X --noheader 2>/dev/null | sort | uniq -c | sort -rn

echo ""
echo "=== RESOURCE USAGE (Last 30 days) ==="
echo "Total CPU time used:"
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -o CPUTimeRAW -X --noheader 2>/dev/null | awk '{sum+=$1} END {print sum/3600 " CPU-hours"}'

echo ""
echo "=== JOBS BY PARTITION ==="
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -o Partition -X --noheader 2>/dev/null | sort | uniq -c | sort -rn

echo ""
echo "=== EFFICIENCY ANALYSIS ==="
echo "Average job duration:"
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -o Elapsed -X --noheader 2>/dev/null | head -20

echo ""
echo "=== MEMORY USAGE PATTERNS ==="
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -o JobID,ReqMem,MaxRSS -X 2>/dev/null | head -20

echo ""
echo "=== CURRENT RUNNING JOBS ==="
squeue -u $USER -t RUNNING -o "%.10i %.20j %.10P %.10M %.10L %.4C %.10m" 2>/dev/null || echo "No running jobs"

echo ""
echo "=== ACCOUNT ASSOCIATIONS ==="
sacctmgr show user $USER withassoc 2>/dev/null || echo "Account info not available"
'''
)

ANALYZE_MY_EFFICIENCY = AnalysisScript(
    id="analyze_my_efficiency",
    name="Job Efficiency Analysis",
    description="Analyzes job efficiency - are you requesting too much memory, too much time, wasting resources?",
    category=AnalysisCategory.USER,
    script='''#!/bin/bash
# Job Efficiency Analysis
# Find resource waste and optimization opportunities

echo "=========================================="
echo "EFFICIENCY ANALYSIS FOR: $USER"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== MEMORY EFFICIENCY ==="
echo "Requested vs Used Memory (look for over-requesting):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s COMPLETED \\
    -o JobID,JobName%20,ReqMem,MaxRSS,State -X 2>/dev/null | head -25

echo ""
echo "=== TIME EFFICIENCY ==="
echo "Time Limit vs Actual Runtime (look for over-requesting):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s COMPLETED \\
    -o JobID,JobName%20,Timelimit,Elapsed,State -X 2>/dev/null | head -25

echo ""
echo "=== CPU EFFICIENCY ==="
echo "Requested CPUs vs CPU Efficiency:"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s COMPLETED \\
    -o JobID,JobName%20,AllocCPUS,CPUTime,TotalCPU -X 2>/dev/null | head -25

echo ""
echo "=== JOBS THAT TIMED OUT (under-requested time) ==="
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -s TIMEOUT \\
    -o JobID,JobName%20,Timelimit,Elapsed -X 2>/dev/null || echo "No timeouts"

echo ""
echo "=== JOBS THAT OOM'D (under-requested memory) ==="
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -s OUT_OF_MEMORY \\
    -o JobID,JobName%20,ReqMem,MaxRSS -X 2>/dev/null || echo "No OOM jobs"

echo ""
echo "=== RECOMMENDATIONS ==="
echo "1. If MaxRSS << ReqMem: Request less memory"
echo "2. If Elapsed << Timelimit: Request less time"
echo "3. If TotalCPU << CPUTime: You may not need all those CPUs"
echo "4. Timeouts: Increase --time or checkpoint your jobs"
echo "5. OOM: Increase --mem or optimize memory usage"
'''
)


# ============================================================
# REGISTRY
# ============================================================

ALL_ANALYSIS_SCRIPTS: Dict[str, AnalysisScript] = {
    # Jobs
    "analyze_my_jobs": ANALYZE_MY_JOBS,
    "analyze_failed_jobs": ANALYZE_FAILED_JOBS,
    "analyze_pending_jobs": ANALYZE_PENDING_JOBS,
    # Cluster
    "analyze_cluster_status": ANALYZE_CLUSTER_STATUS,
    "analyze_gpu_resources": ANALYZE_GPU_RESOURCES,
    "analyze_partition_comparison": ANALYZE_PARTITION_COMPARISON,
    # User
    "analyze_my_usage": ANALYZE_MY_USAGE,
    "analyze_my_efficiency": ANALYZE_MY_EFFICIENCY,
}

SCRIPTS_BY_CATEGORY: Dict[AnalysisCategory, List[AnalysisScript]] = {
    AnalysisCategory.JOBS: [ANALYZE_MY_JOBS],
    AnalysisCategory.DEBUG: [ANALYZE_FAILED_JOBS, ANALYZE_PENDING_JOBS],
    AnalysisCategory.CLUSTER: [ANALYZE_CLUSTER_STATUS, ANALYZE_GPU_RESOURCES, ANALYZE_PARTITION_COMPARISON],
    AnalysisCategory.USER: [ANALYZE_MY_USAGE, ANALYZE_MY_EFFICIENCY],
}


def get_script(script_id: str) -> Optional[AnalysisScript]:
    """Get script by ID"""
    return ALL_ANALYSIS_SCRIPTS.get(script_id)


def get_scripts_prompt() -> str:
    """Generate list for agent prompt"""
    lines = [
        "## ANALYSIS SCRIPTS (safe, read-only)",
        "Run these for comprehensive analysis. Set action='run_analysis', analysis_id='<id>'",
        ""
    ]
    
    for script in ALL_ANALYSIS_SCRIPTS.values():
        lines.append(f"- **{script.id}**: {script.description}")
    
    return "\n".join(lines)

