#!/bin/bash
# Job Efficiency Analysis
# Find resource waste and optimization opportunities

echo "=========================================="
echo "EFFICIENCY ANALYSIS FOR: $USER"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== MEMORY EFFICIENCY ==="
echo "Requested vs Used Memory (look for over-requesting):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s COMPLETED \
    -o JobID,JobName%20,ReqMem,MaxRSS,State -X 2>/dev/null | head -25

echo ""
echo "=== TIME EFFICIENCY ==="
echo "Time Limit vs Actual Runtime (look for over-requesting):"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s COMPLETED \
    -o JobID,JobName%20,Timelimit,Elapsed,State -X 2>/dev/null | head -25

echo ""
echo "=== CPU EFFICIENCY ==="
echo "Requested CPUs vs CPU Efficiency:"
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s COMPLETED \
    -o JobID,JobName%20,AllocCPUS,CPUTime,TotalCPU -X 2>/dev/null | head -25

echo ""
echo "=== JOBS THAT TIMED OUT (under-requested time) ==="
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -s TIMEOUT \
    -o JobID,JobName%20,Timelimit,Elapsed -X 2>/dev/null || echo "No timeouts"

echo ""
echo "=== JOBS THAT OOM'D (under-requested memory) ==="
sacct -u $USER -S $(date -d '30 days ago' +%Y-%m-%d) -s OUT_OF_MEMORY \
    -o JobID,JobName%20,ReqMem,MaxRSS -X 2>/dev/null || echo "No OOM jobs"

echo ""
echo "=== RECOMMENDATIONS ==="
echo "1. If MaxRSS << ReqMem: Request less memory"
echo "2. If Elapsed << Timelimit: Request less time"
echo "3. If TotalCPU << CPUTime: You may not need all those CPUs"
echo "4. Timeouts: Increase --time or checkpoint your jobs"
echo "5. OOM: Increase --mem or optimize memory usage"
