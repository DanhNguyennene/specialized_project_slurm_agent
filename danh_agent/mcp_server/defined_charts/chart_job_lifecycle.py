#!/usr/bin/env python3
"""
Job Lifecycle Chart - Gantt timeline of recent jobs

Shows: Job progression from PENDING → RUNNING → COMPLETED/FAILED
Purpose: Visualize job wait times, runtime, and identify bottlenecks
"""
import subprocess
import json
import sys
from datetime import datetime, timedelta

MOCK_DATA = [
    {"id": "1001", "name": "train_large", "state": "RUNNING", "submit": "10:00", "start": "10:15", "user": "alice"},
    {"id": "1002", "name": "preprocess", "state": "PENDING", "submit": "10:30", "start": None, "user": "bob"},
    {"id": "1003", "name": "inference", "state": "RUNNING", "submit": "09:45", "start": "09:50", "user": "alice"},
    {"id": "1004", "name": "eval_model", "state": "COMPLETED", "submit": "08:00", "start": "08:10", "end": "09:30", "user": "charlie"},
    {"id": "1005", "name": "data_clean", "state": "FAILED", "submit": "09:00", "start": "09:05", "end": "09:20", "user": "dave"},
]

def get_data(mock=False, limit=8):
    """Get recent jobs with timing info."""
    if mock:
        return MOCK_DATA
    
    jobs = []
    try:
        # Get job info with times
        result = subprocess.run(
            ["squeue", "-h", "-o", "%i|%j|%T|%V|%S|%u", "--sort=-V"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n')[:limit]:
                if line and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 6:
                        jobs.append({
                            "id": parts[0],
                            "name": parts[1][:15],
                            "state": parts[2],
                            "submit": parts[3],
                            "start": parts[4] if parts[4] != "N/A" else None,
                            "user": parts[5]
                        })
        
        # Also get recent completed jobs from sacct
        result = subprocess.run(
            ["sacct", "-n", "-o", "JobID,JobName%15,State,Submit,Start,End,User", 
             "--starttime=now-2hours", "--noheader"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n')[:limit]:
                if line and not line.strip().startswith(("batch", "extern")):
                    parts = line.split()
                    if len(parts) >= 6 and "." not in parts[0]:
                        state = parts[2]
                        if state in ["COMPLETED", "FAILED", "CANCELLED"]:
                            jobs.append({
                                "id": parts[0],
                                "name": parts[1][:15],
                                "state": state,
                                "submit": parts[3],
                                "start": parts[4],
                                "end": parts[5],
                                "user": parts[6] if len(parts) > 6 else "unknown"
                            })
    except Exception as e:
        pass
    
    return jobs[:limit]


def generate_chart(params):
    """Generate Mermaid Gantt chart showing job lifecycle."""
    data = get_data(params.get("mock", False), params.get("limit", 8))
    
    if not data:
        return "No job timeline data available."
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Use Gantt chart for timeline visualization
    mermaid = f'''%%{{init: {{'theme': 'default', 'themeVariables': {{'background': '#ffffff'}}, 'gantt': {{'barHeight': 30, 'fontSize': 12, 'sectionFontSize': 14, 'leftPadding': 120}}}}}}%%
gantt
    title Jobs @ {timestamp}
    dateFormat HH:mm
    axisFormat %H:%M
    
'''
    
    # Group by state for sections
    sections = {
        "RUNNING": [],
        "PENDING": [],
        "COMPLETED": [],
        "FAILED": [],
        "CANCELLED": []
    }
    
    for job in data:
        state = job.get("state", "UNKNOWN")
        if state in sections:
            sections[state].append(job)
    
    # Add sections
    for state, jobs in sections.items():
        if not jobs:
            continue
        
        # State styling
        if state == "RUNNING":
            mermaid += '    section Running\n'
        elif state == "PENDING":
            mermaid += '    section Pending\n'
        elif state == "COMPLETED":
            mermaid += '    section Completed\n'
        elif state == "FAILED":
            mermaid += '    section Failed\n'
        elif state == "CANCELLED":
            mermaid += '    section Cancelled\n'
        
        for job in jobs:
            job_id = job["id"]
            job_name = job["name"]
            
            # Parse times (simplified for display)
            submit = job.get("submit", "00:00")
            start = job.get("start")
            
            # Extract just HH:MM
            if submit and len(submit) > 5:
                submit = submit[-5:] if ":" in submit[-5:] else "00:00"
            if start and len(start) > 5:
                start = start[-5:] if ":" in start[-5:] else None
            
            # Label without colon (colon conflicts with Mermaid syntax)
            label = f"{job_name} [{job_id}]"
            
            if state == "PENDING":
                mermaid += f'    {label} : {submit}, 30m\n'
            elif state == "RUNNING" and start:
                mermaid += f'    {label} : active, {start}, 60m\n'
            elif state in ["COMPLETED", "FAILED", "CANCELLED"] and start:
                status = "done" if state == "COMPLETED" else "crit"
                mermaid += f'    {label} : {status}, {start}, 30m\n'
    
    return mermaid.strip()


if __name__ == "__main__":
    params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"mock": True}
    print(generate_chart(params))
