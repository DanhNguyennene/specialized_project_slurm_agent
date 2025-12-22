#!/usr/bin/env python3
"""
Cluster Topology - Pie chart showing node states

Shows: Distribution of node states (idle, allocated, mixed, down, drain)
Purpose: Quick view of cluster node availability
"""
import subprocess
import json
import sys
from datetime import datetime
from collections import defaultdict

MOCK_DATA = {
    "partitions": {
        "gpu": {
            "nodes": {
                "gpu01": "allocated", "gpu02": "allocated", "gpu03": "mixed",
                "gpu04": "down", "gpu05": "idle"
            }
        },
        "compute": {
            "nodes": {
                "node01": "allocated", "node02": "allocated", "node03": "allocated",
                "node04": "mixed", "node05": "idle", "node06": "idle",
                "node07": "drain", "node08": "allocated"
            }
        },
        "debug": {
            "nodes": {
                "debug01": "idle", "debug02": "idle"
            }
        }
    }
}

def get_data(mock=False):
    """Get cluster topology: partitions and node states."""
    if mock:
        return MOCK_DATA
    
    data = {"partitions": defaultdict(lambda: {"nodes": {}})}
    
    try:
        # Get nodes with partition and state
        result = subprocess.run(
            ["sinfo", "-h", "-o", "%P|%n|%T"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 3:
                        partition = parts[0].rstrip('*')
                        node = parts[1]
                        state = parts[2].lower().rstrip('*')
                        
                        # Normalize state
                        if "down" in state:
                            state = "down"
                        elif "drain" in state:
                            state = "drain"
                        elif "alloc" in state:
                            state = "allocated"
                        elif "mix" in state:
                            state = "mixed"
                        else:
                            state = "idle"
                        
                        data["partitions"][partition]["nodes"][node] = state
    except Exception as e:
        pass
    
    return {"partitions": dict(data["partitions"])}


def generate_chart(params):
    """Generate Mermaid pie chart showing node state distribution."""
    data = get_data(params.get("mock", False))
    partitions = data.get("partitions", {})
    
    if not partitions:
        return "No cluster topology data available."
    
    # Count all node states
    state_counts = defaultdict(int)
    for partition in partitions.values():
        for node, state in partition.get("nodes", {}).items():
            state_counts[state] += 1
    
    if not state_counts:
        return "No node data available."
    
    # Build pie chart entries
    pie_entries = []
    state_labels = {
        "allocated": "Allocated",
        "mixed": "Mixed",
        "idle": "Idle",
        "down": "Down",
        "drain": "Draining"
    }
    
    for state, count in sorted(state_counts.items(), key=lambda x: -x[1]):
        label = state_labels.get(state, state.capitalize())
        pie_entries.append(f'    "{label}" : {count}')
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    mermaid = f'''%%{{init: {{"theme": "default", "themeVariables": {{"background": "#ffffff"}}}}}}%%
pie showData
    title Node States @ {timestamp}
{chr(10).join(pie_entries)}
'''
    
    return mermaid.strip()


if __name__ == "__main__":
    params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"mock": True}
    print(generate_chart(params))
