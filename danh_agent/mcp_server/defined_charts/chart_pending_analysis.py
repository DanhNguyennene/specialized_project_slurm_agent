#!/usr/bin/env python3
"""
Pending Jobs Analysis Chart - Bar chart showing pending reasons

Shows: How many jobs are pending for each reason
Purpose: Diagnose queue bottlenecks, understand scheduling decisions
"""
import subprocess
import json
import sys
from datetime import datetime
from collections import defaultdict

MOCK_DATA = [
    {"id": "2001", "name": "gpu_train", "user": "alice", "reason": "Resources", "wait_time": "2:30:00", "cpus": 32, "gpus": 4},
    {"id": "2002", "name": "preprocess", "user": "bob", "reason": "Priority", "wait_time": "0:45:00", "cpus": 8, "gpus": 0},
    {"id": "2003", "name": "depends_job", "user": "charlie", "reason": "Dependency", "wait_time": "1:00:00", "cpus": 16, "gpus": 0},
    {"id": "2004", "name": "big_mem", "user": "alice", "reason": "Resources", "wait_time": "3:15:00", "cpus": 64, "gpus": 0},
    {"id": "2005", "name": "maint_wait", "user": "dave", "reason": "Resources", "wait_time": "0:30:00", "cpus": 4, "gpus": 0},
    {"id": "2006", "name": "fair_share", "user": "eve", "reason": "Priority", "wait_time": "0:15:00", "cpus": 16, "gpus": 2},
    {"id": "2007", "name": "job_wait", "user": "frank", "reason": "Dependency", "wait_time": "0:20:00", "cpus": 8, "gpus": 0},
    {"id": "2008", "name": "low_pri", "user": "grace", "reason": "Priority", "wait_time": "1:00:00", "cpus": 4, "gpus": 0},
]

def get_data(mock=False):
    """Get pending jobs with wait reasons."""
    if mock:
        return MOCK_DATA
    
    jobs = []
    try:
        # Get pending jobs with reason
        result = subprocess.run(
            ["squeue", "-h", "-t", "PENDING", "-o", "%i|%j|%u|%r|%M|%C|%b"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 6:
                        gpus = 0
                        if len(parts) > 6 and parts[6]:
                            gpu_str = parts[6]
                            if 'gpu:' in gpu_str.lower():
                                try:
                                    gpus = int(gpu_str.split(':')[-1])
                                except:
                                    pass
                        
                        jobs.append({
                            "id": parts[0],
                            "name": parts[1][:15],
                            "user": parts[2],
                            "reason": parts[3],
                            "wait_time": parts[4],
                            "cpus": int(parts[5]) if parts[5].isdigit() else 0,
                            "gpus": gpus
                        })
    except Exception as e:
        pass
    
    return jobs


def generate_chart(params):
    """Generate Mermaid bar chart showing pending job reasons."""
    data = get_data(params.get("mock", False))
    
    if not data:
        return "No pending jobs to analyze."
    
    # Group by reason
    by_reason = defaultdict(int)
    for job in data:
        reason = job.get("reason", "Unknown")
        # Normalize common reasons
        if "Resource" in reason:
            by_reason["Resources"] += 1
        elif "Priority" in reason or "Fair" in reason:
            by_reason["Priority"] += 1
        elif "Depend" in reason:
            by_reason["Dependency"] += 1
        elif "Node" in reason or "Down" in reason:
            by_reason["NodeIssue"] += 1
        elif "Reservation" in reason:
            by_reason["Reserved"] += 1
        else:
            by_reason["Other"] += 1
    
    # Sort by count
    sorted_reasons = sorted(by_reason.items(), key=lambda x: -x[1])
    
    # Build x-axis labels and bar values
    labels = [f'"{r}"' for r, _ in sorted_reasons]
    values = [str(c) for _, c in sorted_reasons]
    
    max_count = max(by_reason.values()) if by_reason else 10
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    mermaid = f'''---
config:
  theme: default
  themeVariables:
    background: "#ffffff"
  xyChart:
    width: 600
    height: 350
---
xychart-beta
    title "Pending Jobs by Reason @ {timestamp}"
    x-axis [{", ".join(labels)}]
    y-axis "Jobs" 0 --> {max_count + 2}
    bar [{", ".join(values)}]
'''
    
    return mermaid.strip()


if __name__ == "__main__":
    params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"mock": True}
    print(generate_chart(params))
