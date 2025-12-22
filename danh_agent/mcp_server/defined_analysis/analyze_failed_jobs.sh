#!/bin/bash
# Failed Jobs Deep Analysis
# Identifies failure patterns and reasons

echo "=========================================="
echo "FAILED JOBS ANALYSIS FOR: $USER"
echo "Generated: $(date)"
echo "=========================================="

echo ""
echo "=== RECENT FAILED JOBS (LAST 14 DAYS) ==="
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s FAILED,TIMEOUT,OUT_OF_MEMORY,NODE_FAIL,CANCELLED \
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
sacct -u $USER -S $(date -d '14 days ago' +%Y-%m-%d) -s FAILED,TIMEOUT,OUT_OF_MEMORY -X \
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
