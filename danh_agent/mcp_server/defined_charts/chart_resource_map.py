#!/usr/bin/env python3
"""
Resource Allocation Map - Pie chart showing resource distribution by user

Shows: Who's using what percentage of cluster resources
Purpose: Understand resource distribution, identify heavy users
"""
import subprocess
import json
import sys
from datetime import datetime
from collections import defaultdict

MOCK_DATA = {
    "alice": {"jobs": 3, "cpus": 64, "mem_gb": 256, "gpus": 4},
    "bob": {"jobs": 5, "cpus": 40, "mem_gb": 160, "gpus": 0},
    "charlie": {"jobs": 2, "cpus": 128, "mem_gb": 512, "gpus": 8},
    "dave": {"jobs": 1, "cpus": 16, "mem_gb": 64, "gpus": 0},
    "system": {"jobs": 1, "cpus": 4, "mem_gb": 16, "gpus": 0},
}

MOCK_TOTALS = {"cpus": 500, "mem_gb": 2048, "gpus": 16}

def get_data(mock=False):
    """Get resource allocation by user."""
    if mock:
        return {"users": MOCK_DATA, "totals": MOCK_TOTALS}
    
    users = defaultdict(lambda: {"jobs": 0, "cpus": 0, "mem_gb": 0, "gpus": 0})
    totals = {"cpus": 0, "mem_gb": 0, "gpus": 0}
    
    try:
        # Get running jobs with resource info
        result = subprocess.run(
            ["squeue", "-h", "-t", "RUNNING", "-o", "%u|%C|%m|%b"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 3:
                        user = parts[0]
                        cpus = int(parts[1]) if parts[1].isdigit() else 0
                        
                        # Parse memory (format: 4G, 512M, etc.)
                        mem_str = parts[2]
                        mem_gb = 0
                        if 'G' in mem_str:
                            mem_gb = int(mem_str.replace('G', ''))
                        elif 'M' in mem_str:
                            mem_gb = int(mem_str.replace('M', '')) // 1024
                        
                        # Parse GPUs
                        gpus = 0
                        if len(parts) > 3 and parts[3]:
                            gpu_str = parts[3]
                            if 'gpu:' in gpu_str:
                                gpus = int(gpu_str.split(':')[-1])
                        
                        users[user]["jobs"] += 1
                        users[user]["cpus"] += cpus
                        users[user]["mem_gb"] += mem_gb
                        users[user]["gpus"] += gpus
        
        # Get cluster totals
        result = subprocess.run(
            ["sinfo", "-h", "-o", "%C"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            # Format: allocated/idle/other/total
            parts = result.stdout.strip().split('/')
            if len(parts) >= 4:
                totals["cpus"] = int(parts[3])
        
    except Exception as e:
        pass
    
    return {"users": dict(users), "totals": totals}


def generate_chart(params):
    """Generate Mermaid pie chart showing CPU allocation by user."""
    data = get_data(params.get("mock", False))
    users = data.get("users", {})
    totals = data.get("totals", {"cpus": 500, "mem_gb": 2048, "gpus": 16})
    
    if not users:
        return "No resource allocation data available."
    
    # Sort users by CPU usage
    sorted_users = sorted(users.items(), key=lambda x: -x[1]["cpus"])
    
    # Calculate totals in use
    total_cpus_used = sum(u["cpus"] for u in users.values())
    free_cpus = max(0, totals["cpus"] - total_cpus_used)
    
    # Build pie chart entries
    pie_entries = []
    for user, alloc in sorted_users[:5]:  # Top 5 users
        if alloc["cpus"] > 0:
            pie_entries.append(f'    "{user}" : {alloc["cpus"]}')
    
    if free_cpus > 0:
        pie_entries.append(f'    "Available" : {free_cpus}')
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    mermaid = f'''%%{{init: {{"theme": "default", "themeVariables": {{"background": "#ffffff"}}}}}}%%
pie showData
    title CPU by User @ {timestamp}
{chr(10).join(pie_entries)}
'''
    
    return mermaid.strip()


if __name__ == "__main__":
    params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"mock": True}
    print(generate_chart(params))
