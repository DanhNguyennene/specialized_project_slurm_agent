#!/bin/bash
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
