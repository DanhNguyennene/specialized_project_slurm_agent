#!/bin/bash
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
