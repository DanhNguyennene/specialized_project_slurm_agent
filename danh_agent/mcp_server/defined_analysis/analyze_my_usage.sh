#!/bin/bash
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
