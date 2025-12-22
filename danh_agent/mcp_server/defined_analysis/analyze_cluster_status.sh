#!/bin/bash
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
