#!/usr/bin/env python3
"""
System Health Dashboard - Pie chart showing utilization breakdown

Shows: CPU/GPU/Memory utilization as used vs available
Purpose: Quick operational metrics visualization
"""
import subprocess
import json
import sys
from datetime import datetime

MOCK_DATA = {
    "scheduler": "healthy",
    "nodes": {"total": 50, "healthy": 46, "down": 2, "drain": 2},
    "jobs": {"running": 45, "pending": 23, "failed_24h": 3},
    "queue_wait": {"avg_minutes": 25, "max_minutes": 180},
    "utilization": {"cpu_pct": 72, "gpu_pct": 85, "mem_pct": 65},
    "alerts": [
        {"level": "warning", "msg": "Node gpu04 down for 2h"},
        {"level": "warning", "msg": "23 jobs pending > 1h"},
    ]
}

def get_data(mock=False):
    """Get system health metrics."""
    if mock:
        return MOCK_DATA
    
    data = {
        "scheduler": "unknown",
        "nodes": {"total": 0, "healthy": 0, "down": 0, "drain": 0},
        "jobs": {"running": 0, "pending": 0, "failed_24h": 0},
        "queue_wait": {"avg_minutes": 0, "max_minutes": 0},
        "utilization": {"cpu_pct": 0, "gpu_pct": 0, "mem_pct": 0},
        "alerts": []
    }
    
    try:
        # Check scheduler
        result = subprocess.run(["squeue", "-h", "-o", "%i"], capture_output=True, text=True, timeout=5)
        data["scheduler"] = "healthy" if result.returncode == 0 else "error"
        
        # Get node health
        result = subprocess.run(["sinfo", "-h", "-o", "%T"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                state = line.strip().lower().rstrip('*')
                data["nodes"]["total"] += 1
                if state in ["idle", "allocated", "mixed"]:
                    data["nodes"]["healthy"] += 1
                elif "down" in state:
                    data["nodes"]["down"] += 1
                elif "drain" in state:
                    data["nodes"]["drain"] += 1
        
        # Get job counts
        result = subprocess.run(["squeue", "-h", "-o", "%T"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                state = line.strip()
                if state == "RUNNING":
                    data["jobs"]["running"] += 1
                elif state == "PENDING":
                    data["jobs"]["pending"] += 1
        
        # Get failed jobs in last 24h
        result = subprocess.run(
            ["sacct", "-n", "-o", "State", "--state=FAILED", "--starttime=now-1day"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data["jobs"]["failed_24h"] = len([l for l in result.stdout.strip().split('\n') if l.strip()])
        
        # Get CPU utilization
        result = subprocess.run(["sinfo", "-h", "-o", "%C"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            parts = result.stdout.strip().split('/')
            if len(parts) >= 4:
                allocated = int(parts[0])
                total = int(parts[3])
                data["utilization"]["cpu_pct"] = int(allocated / total * 100) if total > 0 else 0
        
        # Build alerts
        if data["nodes"]["down"] > 0:
            data["alerts"].append({"level": "warning", "msg": f"{data['nodes']['down']} node(s) down"})
        if data["jobs"]["failed_24h"] > 5:
            data["alerts"].append({"level": "warning", "msg": f"{data['jobs']['failed_24h']} jobs failed (24h)"})
        if data["jobs"]["pending"] > 50:
            data["alerts"].append({"level": "info", "msg": f"High queue: {data['jobs']['pending']} pending"})
            
    except Exception as e:
        data["alerts"].append({"level": "error", "msg": str(e)})
    
    return data


def generate_chart(params):
    """Generate Mermaid flowchart dashboard showing system health metrics."""
    data = get_data(params.get("mock", False))
    
    util = data["utilization"]
    nodes = data["nodes"]
    jobs = data["jobs"]
    
    # Calculate node health
    node_health_pct = int(nodes["healthy"] / nodes["total"] * 100) if nodes["total"] > 0 else 0
    
    # Determine colors based on thresholds
    def get_color(value, good=70, warn=85):
        if value < good:
            return "#22c55e"  # green
        elif value < warn:
            return "#f59e0b"  # yellow
        else:
            return "#ef4444"  # red
    
    def get_node_color(pct):
        if pct >= 90:
            return "#22c55e"
        elif pct >= 75:
            return "#f59e0b"
        else:
            return "#ef4444"
    
    cpu_color = get_color(util["cpu_pct"])
    gpu_color = get_color(util["gpu_pct"])
    mem_color = get_color(util["mem_pct"])
    node_color = get_node_color(node_health_pct)
    
    # Overall status
    if node_health_pct >= 90 and util["cpu_pct"] < 90:
        status = "HEALTHY"
        status_color = "#22c55e"
    elif node_health_pct >= 75:
        status = "DEGRADED"
        status_color = "#f59e0b"
    else:
        status = "CRITICAL"
        status_color = "#ef4444"
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    mermaid = f'''%%{{init: {{"theme": "default", "themeVariables": {{"background": "#ffffff"}}}}}}%%
flowchart TB
    subgraph HEADER["Health Dashboard"]
        TIME["{timestamp}"]
        STATUS["{status}"]
    end
    
    subgraph RESOURCES[Resource Utilization]
        CPU["CPU: {util['cpu_pct']}%"]
        GPU["GPU: {util['gpu_pct']}%"]
        MEM["Memory: {util['mem_pct']}%"]
    end
    
    subgraph NODES[Node Status]
        HEALTHY["{nodes['healthy']}/{nodes['total']} Healthy"]
        DOWN["{nodes['down']} Down"]
        DRAIN["{nodes['drain']} Draining"]
    end
    
    subgraph JOBS[Job Queue]
        RUNNING["{jobs['running']} Running"]
        PENDING["{jobs['pending']} Pending"]
        FAILED["{jobs['failed_24h']} Failed 24h"]
    end
    
    HEADER --> RESOURCES
    HEADER --> NODES
    HEADER --> JOBS
    
    style STATUS fill:{status_color},color:#fff,stroke:none
    style CPU fill:{cpu_color},color:#fff,stroke:none
    style GPU fill:{gpu_color},color:#fff,stroke:none
    style MEM fill:{mem_color},color:#fff,stroke:none
    style HEALTHY fill:{node_color},color:#fff,stroke:none
    style DOWN fill:#ef4444,color:#fff,stroke:none
    style DRAIN fill:#f59e0b,color:#fff,stroke:none
    style RUNNING fill:#22c55e,color:#fff,stroke:none
    style PENDING fill:#3b82f6,color:#fff,stroke:none
    style FAILED fill:#ef4444,color:#fff,stroke:none
'''
    
    return mermaid.strip()


if __name__ == "__main__":
    params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"mock": True}
    print(generate_chart(params))
