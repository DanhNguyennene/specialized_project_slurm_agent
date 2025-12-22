#!/usr/bin/env python3
"""
MCP Server Direct Test Script

Tests MCP tools directly via HTTP POST to /message endpoint.
Does NOT require the agent to be running.

Usage:
  1. Start MCP server in mock mode: python mcp_server/slurm_mcp_sse.py --mock mixed
  2. Run this script: python tests/test_mcp_direct.py
"""

import asyncio
import json
import time
import os
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
import statistics

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import aiohttp
except ImportError:
    print("Installing aiohttp...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "-q"])
    import aiohttp

# Configuration
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


@dataclass
class TestResult:
    """Single test result"""
    test_id: str
    tool_name: str
    category: str
    description: str
    passed: bool
    latency_ms: float
    error: Optional[str] = None
    response_preview: Optional[str] = None


class TestSuite:
    """Collection of test results"""
    
    def __init__(self, name: str):
        self.name = name
        self.timestamp = datetime.now().isoformat()
        self.results: List[TestResult] = []
    
    def add(self, result: TestResult):
        self.results.append(result)
    
    def summary(self) -> Dict[str, Any]:
        if not self.results:
            return {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0}
        
        passed = sum(1 for r in self.results if r.passed)
        latencies = [r.latency_ms for r in self.results if r.passed]
        
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": len(self.results) - passed,
            "pass_rate": round(passed / len(self.results) * 100, 1),
            "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0,
            "min_latency_ms": round(min(latencies), 1) if latencies else 0,
            "max_latency_ms": round(max(latencies), 1) if latencies else 0,
        }
    
    def by_category(self) -> Dict[str, Dict]:
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = {"passed": 0, "failed": 0, "latencies": []}
            if r.passed:
                categories[r.category]["passed"] += 1
            else:
                categories[r.category]["failed"] += 1
            categories[r.category]["latencies"].append(r.latency_ms)
        
        for cat, data in categories.items():
            total = data["passed"] + data["failed"]
            data["total"] = total
            data["pass_rate"] = round(data["passed"] / total * 100, 1) if total else 0
            data["avg_latency_ms"] = round(statistics.mean(data["latencies"]), 1)
            del data["latencies"]
        
        return categories
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "summary": self.summary(),
            "by_category": self.by_category(),
            "results": [asdict(r) for r in self.results]
        }


async def call_mcp_tool(session: aiohttp.ClientSession, tool_name: str, 
                        params: Dict[str, Any]) -> Dict[str, Any]:
    """Call an MCP tool via POST /message"""
    start = time.perf_counter()
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params
        }
    }
    
    try:
        async with session.post(f"{MCP_SERVER_URL}/message", json=payload) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000
            
            if resp.status == 200:
                result = await resp.json()
                # Check for MCP error response
                if "error" in result:
                    return {
                        "success": False,
                        "error": result["error"].get("message", str(result["error"])),
                        "latency_ms": elapsed_ms
                    }
                return {
                    "success": True,
                    "result": result.get("result", result),
                    "latency_ms": elapsed_ms
                }
            else:
                text = await resp.text()
                return {
                    "success": False,
                    "error": f"HTTP {resp.status}: {text[:200]}",
                    "latency_ms": elapsed_ms
                }
    except aiohttp.ClientConnectorError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "success": False,
            "error": f"Connection failed: {e}. Is MCP server running?",
            "latency_ms": elapsed_ms
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "success": False,
            "error": str(e),
            "latency_ms": elapsed_ms
        }


# ============ Test Cases ============

MCP_TEST_CASES = [
    # === Query Tools ===
    # squeue
    ("squeue", "query", "squeue - no params", {}),
    ("squeue", "query", "squeue - filter by user", {"user": "alice"}),
    ("squeue", "query", "squeue - filter by partition", {"partition": "gpu"}),
    ("squeue", "query", "squeue - filter by state RUNNING", {"state": "RUNNING"}),
    ("squeue", "query", "squeue - filter by state PENDING", {"state": "PENDING"}),
    ("squeue", "query", "squeue - filter by job_id", {"job_id": "4001"}),
    ("squeue", "query", "squeue - multiple filters", {"user": "alice", "partition": "gpu"}),
    
    # sinfo
    ("sinfo", "query", "sinfo - no params", {}),
    ("sinfo", "query", "sinfo - filter by partition", {"partition": "gpu"}),
    ("sinfo", "query", "sinfo - filter by state idle", {"state": "idle"}),
    ("sinfo", "query", "sinfo - filter by state alloc", {"state": "alloc"}),
    
    # sacct
    ("sacct", "query", "sacct - no params", {}),
    ("sacct", "query", "sacct - filter by user", {"user": "alice"}),
    ("sacct", "query", "sacct - filter by state FAILED", {"state": "FAILED"}),
    ("sacct", "query", "sacct - filter by state COMPLETED", {"state": "COMPLETED"}),
    
    # scontrol_show
    ("scontrol_show", "query", "scontrol_show job", {"entity": "job", "id": "4001"}),
    ("scontrol_show", "query", "scontrol_show partition", {"entity": "partition", "id": "gpu"}),
    ("scontrol_show", "query", "scontrol_show node", {"entity": "node", "id": "gpu-node-01"}),
    
    # === Analysis Tools ===
    ("run_analysis", "analysis", "analyze_cluster_status", {"script_id": "analyze_cluster_status"}),
    ("run_analysis", "analysis", "analyze_failed_jobs", {"script_id": "analyze_failed_jobs"}),
    ("run_analysis", "analysis", "analyze_pending_jobs", {"script_id": "analyze_pending_jobs"}),
    ("run_analysis", "analysis", "analyze_my_jobs", {"script_id": "analyze_my_jobs"}),
    ("run_analysis", "analysis", "analyze_gpu_resources", {"script_id": "analyze_gpu_resources"}),
    
    # === Accounting Tools ===
    ("sacctmgr_show", "accounting", "sacctmgr_show account", {"entity": "account"}),
    ("sacctmgr_show", "accounting", "sacctmgr_show user", {"entity": "user"}),
    ("sacctmgr_show", "accounting", "sacctmgr_show qos", {"entity": "qos"}),
    ("sreport", "accounting", "sreport cluster utilization", {"report_type": "cluster", "report_name": "Utilization"}),
    ("sreport", "accounting", "sreport user top usage", {"report_type": "user", "report_name": "TopUsage"}),
    
    # === Action Tools (Mock - should succeed in mock mode) ===
    ("sbatch", "action", "sbatch submit job", {"script": "#!/bin/bash\necho hello"}),
    ("scancel", "action", "scancel job", {"job_id": "9999"}),
    ("scontrol_hold", "action", "scontrol_hold job", {"job_id": "9999"}),
    ("scontrol_release", "action", "scontrol_release job", {"job_id": "9999"}),
    ("scontrol_update", "action", "scontrol_update job", {"job_id": "9999", "TimeLimit": "2:00:00"}),
    ("scontrol_requeue", "action", "scontrol_requeue job", {"job_id": "9999"}),
    
    # === Interactive Tools ===
    ("srun", "interactive", "srun command", {"command": "hostname", "nodes": 1}),
    ("salloc", "interactive", "salloc allocation", {"nodes": 2, "partition": "gpu"}),
    
    # === Admin Tools (Mock) ===
    ("scontrol_create", "admin", "scontrol_create reservation", {"entity": "reservation", "name": "test_res"}),
    ("scontrol_delete", "admin", "scontrol_delete reservation", {"entity": "reservation", "name": "test_res"}),
    ("sacctmgr_add", "admin", "sacctmgr_add account", {"entity": "account", "name": "test_account"}),
    ("sacctmgr_modify", "admin", "sacctmgr_modify account", {"entity": "account", "name": "test_account"}),
    ("sacctmgr_delete", "admin", "sacctmgr_delete account", {"entity": "account", "name": "test_account"}),
    
    # === Edge Cases ===
    ("squeue", "edge_case", "squeue - nonexistent user", {"user": "nonexistent_user_xyz"}),
    ("scontrol_show", "edge_case", "scontrol_show - invalid job", {"entity": "job", "id": "999999999"}),
    ("run_analysis", "edge_case", "run_analysis - invalid script", {"script_id": "invalid_script_xyz"}),
]


async def run_mcp_tests() -> TestSuite:
    """Run all MCP tool tests"""
    suite = TestSuite("MCP Tool Tests")
    
    print(f"Testing MCP Server at {MCP_SERVER_URL}")
    print(f"Running {len(MCP_TEST_CASES)} test cases...\n")
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        # First check if server is running
        try:
            async with session.get(f"{MCP_SERVER_URL}/health") as resp:
                if resp.status != 200:
                    print(f"ERROR: MCP server health check failed (HTTP {resp.status})")
                    return suite
                print("✓ MCP server is healthy\n")
        except Exception as e:
            print(f"ERROR: Cannot connect to MCP server: {e}")
            print("Start the server with: python mcp_server/slurm_mcp_sse.py --mock mixed")
            return suite
        
        # Run tests
        for i, (tool, category, desc, params) in enumerate(MCP_TEST_CASES, 1):
            result = await call_mcp_tool(session, tool, params)
            
            # Determine pass/fail
            # Edge cases should return gracefully (not crash)
            passed = result["success"]
            if category == "edge_case" and not result["success"]:
                # Edge case failures with proper error messages are still passes
                if result.get("error") and "not found" in result["error"].lower():
                    passed = True
            
            # Print progress
            status = "✓" if passed else "✗"
            latency = f"{result['latency_ms']:.0f}ms"
            print(f"  [{i:2d}/{len(MCP_TEST_CASES)}] {status} {desc} ({latency})")
            
            if not passed and result.get("error"):
                print(f"         Error: {result['error'][:80]}")
            
            suite.add(TestResult(
                test_id=f"mcp_{i:03d}",
                tool_name=tool,
                category=category,
                description=desc,
                passed=passed,
                latency_ms=result["latency_ms"],
                error=result.get("error"),
                response_preview=str(result.get("result", ""))[:200]
            ))
    
    return suite


def generate_latex_table(suite: TestSuite) -> str:
    """Generate LaTeX table for the thesis report"""
    by_cat = suite.by_category()
    
    lines = [
        r"% Auto-generated by test_mcp_direct.py",
        r"\begin{table}[H]",
        r"    \centering",
        r"    \caption{MCP Tool Test Results}",
        r"    \label{tab:mcp-test-results}",
        r"    \begin{tabular}{|l|c|c|c|c|}",
        r"        \hline",
        r"        \textbf{Category} & \textbf{Tests} & \textbf{Passed} & \textbf{Pass Rate} & \textbf{Avg Latency} \\",
        r"        \hline",
    ]
    
    for cat, data in sorted(by_cat.items()):
        cat_name = cat.replace("_", " ").title()
        lines.append(f"        {cat_name} & {data['total']} & {data['passed']} & {data['pass_rate']}\\% & {data['avg_latency_ms']}ms \\\\")
    
    summary = suite.summary()
    lines.extend([
        r"        \hline",
        f"        \\textbf{{Total}} & {summary['total']} & {summary['passed']} & {summary['pass_rate']}\\% & {summary['avg_latency_ms']}ms \\\\",
        r"        \hline",
        r"    \end{tabular}",
        r"\end{table}",
    ])
    
    return "\n".join(lines)


async def main():
    """Run tests and save results"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    print("=" * 60)
    print("MCP Server Direct Test Suite")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")
    
    suite = await run_mcp_tests()
    
    if not suite.results:
        print("\nNo tests were run. Make sure MCP server is running.")
        return
    
    # Save results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    summary = suite.summary()
    print(f"Total: {summary['total']} tests")
    print(f"Passed: {summary['passed']} ({summary['pass_rate']}%)")
    print(f"Failed: {summary['failed']}")
    print(f"Avg Latency: {summary['avg_latency_ms']}ms")
    print(f"Min/Max Latency: {summary['min_latency_ms']}ms / {summary['max_latency_ms']}ms")
    
    # By category
    print("\nBy Category:")
    for cat, data in sorted(suite.by_category().items()):
        print(f"  {cat}: {data['passed']}/{data['total']} ({data['pass_rate']}%)")
    
    # Save JSON
    json_path = os.path.join(RESULTS_DIR, "mcp_test_results.json")
    with open(json_path, "w") as f:
        json.dump(suite.to_dict(), f, indent=2)
    print(f"\nSaved: {json_path}")
    
    # Save LaTeX
    latex_path = os.path.join(RESULTS_DIR, "mcp_test_table.tex")
    with open(latex_path, "w") as f:
        f.write(generate_latex_table(suite))
    print(f"Saved: {latex_path}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
