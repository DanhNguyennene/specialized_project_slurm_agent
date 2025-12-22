#!/bin/bash
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
sinfo -o "%G" --noheader 2>/dev/null | tr ',' '\n' | grep gpu | sort | uniq -c
