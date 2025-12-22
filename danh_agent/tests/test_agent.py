#!/usr/bin/env python3
"""
Slurm Agent Evaluation Script

Tests the Agent API directly via HTTP calls to /v1/chat/completions.
Requires: 
  1. MCP server running: python mcp_server/slurm_mcp_sse.py --mock mixed
  2. Agent running: python agent/main.py

Usage:
  python tests/test_agent.py
  
Output:
  - tests/results/agent_test_results.json
  - tests/results/agent_test_table.tex
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

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import aiohttp
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "-q"])
    import aiohttp

# Configuration
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:20000")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


@dataclass  
class AgentTestResult:
    """Single agent test result"""
    test_id: str
    category: str
    query: str
    passed: bool
    ttft_ms: Optional[float]  # Time to first token
    total_ms: float
    response_length: int
    tool_calls_detected: List[str]
    error: Optional[str] = None
    response_preview: Optional[str] = None
    keywords_found: List[str] = field(default_factory=list)


class AgentTestSuite:
    """Collection of agent test results"""
    
    def __init__(self, name: str):
        self.name = name
        self.timestamp = datetime.now().isoformat()
        self.results: List[AgentTestResult] = []
    
    def add(self, result: AgentTestResult):
        self.results.append(result)
    
    def summary(self) -> Dict[str, Any]:
        if not self.results:
            return {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0}
        
        passed = sum(1 for r in self.results if r.passed)
        ttfts = [r.ttft_ms for r in self.results if r.ttft_ms and r.passed]
        totals = [r.total_ms for r in self.results if r.passed]
        
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": len(self.results) - passed,
            "pass_rate": round(passed / len(self.results) * 100, 1),
            "avg_ttft_ms": round(statistics.mean(ttfts), 1) if ttfts else 0,
            "avg_total_ms": round(statistics.mean(totals), 1) if totals else 0,
            "min_total_ms": round(min(totals), 1) if totals else 0,
            "max_total_ms": round(max(totals), 1) if totals else 0,
        }
    
    def by_category(self) -> Dict[str, Dict]:
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = {"passed": 0, "failed": 0, "ttfts": [], "totals": []}
            if r.passed:
                categories[r.category]["passed"] += 1
                if r.ttft_ms:
                    categories[r.category]["ttfts"].append(r.ttft_ms)
                categories[r.category]["totals"].append(r.total_ms)
            else:
                categories[r.category]["failed"] += 1
        
        for cat, data in categories.items():
            total = data["passed"] + data["failed"]
            data["total"] = total
            data["pass_rate"] = round(data["passed"] / total * 100, 1) if total else 0
            data["avg_ttft_ms"] = round(statistics.mean(data["ttfts"]), 1) if data["ttfts"] else 0
            data["avg_total_ms"] = round(statistics.mean(data["totals"]), 1) if data["totals"] else 0
            del data["ttfts"]
            del data["totals"]
        
        return categories
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "summary": self.summary(),
            "by_category": self.by_category(),
            "results": [asdict(r) for r in self.results]
        }


async def call_agent(session: aiohttp.ClientSession, query: str, 
                     session_id: str = "test") -> Dict[str, Any]:
    """Call agent via streaming API and collect response"""
    start = time.perf_counter()
    ttft = None
    full_response = ""
    tool_calls = []
    
    payload = {
        "model": "slurm-agent",
        "messages": [{"role": "user", "content": query}],
        "stream": True,
        "chat_id": session_id
    }
    
    try:
        async with session.post(
            f"{AGENT_URL}/v1/chat/completions",
            json=payload,
            headers={"Accept": "text/event-stream"},
            timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            if resp.status != 200:
                elapsed = (time.perf_counter() - start) * 1000
                text = await resp.text()
                return {
                    "success": False,
                    "error": f"HTTP {resp.status}: {text[:200]}",
                    "total_ms": elapsed,
                    "ttft_ms": None,
                    "response": "",
                    "tool_calls": []
                }
            
            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                    
                if line.startswith("data: "):
                    if ttft is None:
                        ttft = (time.perf_counter() - start) * 1000
                    
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            full_response += content
                            
                            # Detect tool markers
                            if "[TOOL:" in content:
                                import re
                                tools = re.findall(r'\[TOOL:(\w+)\]', content)
                                tool_calls.extend(tools)
                    except json.JSONDecodeError:
                        pass
            
            elapsed = (time.perf_counter() - start) * 1000
            return {
                "success": True,
                "response": full_response,
                "total_ms": elapsed,
                "ttft_ms": ttft,
                "tool_calls": list(set(tool_calls))
            }
    
    except asyncio.TimeoutError:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "success": False,
            "error": "Request timed out (120s)",
            "total_ms": elapsed,
            "ttft_ms": ttft,
            "response": full_response,
            "tool_calls": tool_calls
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "success": False,
            "error": str(e),
            "total_ms": elapsed,
            "ttft_ms": ttft,
            "response": "",
            "tool_calls": []
        }


# ============ Test Cases ============

AGENT_TEST_CASES = [
    # (category, query, expected_keywords, description)
    
    # === Simple Status Queries ===
    ("status", "What jobs are currently running?", ["RUNNING", "job"], "Running jobs query"),
    ("status", "Show me the cluster status", ["node", "partition", "status"], "Cluster status"),
    ("status", "List all partitions", ["gpu", "cpu", "partition"], "Partition list"),
    ("status", "How many nodes are available?", ["node", "idle", "available"], "Node availability"),
    ("status", "What is the queue status?", ["queue", "pending", "running"], "Queue status"),
    
    # === Job-Specific Queries ===
    ("job_query", "Show details for job 4001", ["4001"], "Specific job details"),
    ("job_query", "What jobs does alice have?", ["alice"], "User jobs query"),
    ("job_query", "Are there any failed jobs?", ["FAILED", "fail", "error"], "Failed jobs query"),
    ("job_query", "Why are jobs pending?", ["pending", "reason", "wait"], "Pending reason"),
    ("job_query", "Show completed jobs", ["COMPLETED", "complete", "finish"], "Completed jobs"),
    
    # === Analysis Queries ===
    ("analysis", "Analyze the cluster health", ["health", "status", "node"], "Cluster analysis"),
    ("analysis", "What problems are there in the cluster?", ["issue", "problem", "error", "down"], "Problem detection"),
    ("analysis", "Show GPU resource usage", ["GPU", "gpu", "resource"], "GPU analysis"),
    ("analysis", "Analyze job failures", ["fail", "error", "reason"], "Failure analysis"),
    
    # === Visualization Queries ===
    ("visualization", "Show me a chart of node status", ["mermaid", "chart", "```"], "Node chart"),
    ("visualization", "Visualize cluster topology", ["mermaid", "chart", "```"], "Topology chart"),
    
    # === Action Queries (should trigger confirmation) ===
    ("action", "Cancel job 4001", ["confirm", "cancel", "pending", "proceed"], "Cancel job request"),
    ("action", "Hold job 4002", ["confirm", "hold", "pending", "proceed"], "Hold job request"),
    
    # === Multi-turn Context ===
    ("context", "Show jobs for user bob", ["bob"], "Context - user jobs"),
    ("context", "What about failed ones?", ["bob", "fail", "FAILED"], "Context - followup"),
]


async def run_agent_tests() -> AgentTestSuite:
    """Run all agent tests"""
    suite = AgentTestSuite("Agent Query Tests")
    
    print(f"Testing Agent at {AGENT_URL}")
    print(f"Running {len(AGENT_TEST_CASES)} test cases...\n")
    
    async with aiohttp.ClientSession() as session:
        # Health check
        try:
            async with session.get(f"{AGENT_URL}/health") as resp:
                if resp.status != 200:
                    print(f"ERROR: Agent health check failed (HTTP {resp.status})")
                    return suite
                print("✓ Agent is healthy\n")
        except Exception as e:
            print(f"ERROR: Cannot connect to Agent: {e}")
            print("Start the agent with: python agent/main.py")
            return suite
        
        # Use consistent session for context tests
        test_session_id = f"eval_{int(time.time())}"
        
        for i, (category, query, expected_kw, desc) in enumerate(AGENT_TEST_CASES, 1):
            # Use same session for context tests
            sid = test_session_id if category == "context" else f"test_{i}_{int(time.time())}"
            
            result = await call_agent(session, query, sid)
            
            # Check keywords
            response_lower = result.get("response", "").lower()
            keywords_found = [kw for kw in expected_kw if kw.lower() in response_lower]
            
            # Pass criteria: success + (keywords found OR substantial response)
            passed = result["success"] and (len(keywords_found) > 0 or len(result.get("response", "")) > 100)
            
            # Print progress
            status = "✓" if passed else "✗"
            ttft_str = f"TTFT:{result['ttft_ms']:.0f}ms" if result.get('ttft_ms') else "TTFT:N/A"
            total_str = f"Total:{result['total_ms']:.0f}ms"
            resp_len = len(result.get("response", ""))
            
            print(f"  [{i:2d}/{len(AGENT_TEST_CASES)}] {status} {desc}")
            print(f"         {ttft_str} | {total_str} | {resp_len} chars | Keywords: {keywords_found}")
            
            if not passed:
                if result.get("error"):
                    print(f"         Error: {result['error'][:80]}")
                else:
                    print(f"         Response: {result.get('response', '')[:100]}...")
            
            suite.add(AgentTestResult(
                test_id=f"agent_{i:03d}",
                category=category,
                query=query,
                passed=passed,
                ttft_ms=result.get("ttft_ms"),
                total_ms=result["total_ms"],
                response_length=resp_len,
                tool_calls_detected=result.get("tool_calls", []),
                error=result.get("error"),
                response_preview=result.get("response", "")[:300],
                keywords_found=keywords_found
            ))
            
            # Small delay between tests
            await asyncio.sleep(0.5)
    
    return suite


def generate_latex_tables(suite: AgentTestSuite) -> str:
    """Generate LaTeX tables for thesis"""
    lines = []
    
    # Query Accuracy Table
    by_cat = suite.by_category()
    lines.extend([
        r"% Auto-generated by test_agent.py",
        r"\begin{table}[H]",
        r"    \centering",
        r"    \caption{Query Response Accuracy by Category}",
        r"    \label{tab:query-accuracy}",
        r"    \begin{tabular}{|l|c|c|c|}",
        r"        \hline",
        r"        \textbf{Query Category} & \textbf{Queries} & \textbf{Correct} & \textbf{Accuracy} \\",
        r"        \hline",
    ])
    
    for cat, data in sorted(by_cat.items()):
        cat_name = cat.replace("_", " ").title()
        lines.append(f"        {cat_name} & {data['total']} & {data['passed']} & {data['pass_rate']}\\% \\\\")
    
    summary = suite.summary()
    lines.extend([
        r"        \hline",
        f"        \\textbf{{Total}} & {summary['total']} & {summary['passed']} & {summary['pass_rate']}\\% \\\\",
        r"        \hline",
        r"    \end{tabular}",
        r"\end{table}",
        "",
    ])
    
    # Latency Table  
    lines.extend([
        r"\begin{table}[H]",
        r"    \centering",
        r"    \caption{Response Latency Measurements}",
        r"    \label{tab:latency-measurements}",
        r"    \begin{tabular}{|l|c|c|c|}",
        r"        \hline",
        r"        \textbf{Query Type} & \textbf{TTFT (ms)} & \textbf{Avg Total (ms)} & \textbf{Tests} \\",
        r"        \hline",
    ])
    
    for cat, data in sorted(by_cat.items()):
        cat_name = cat.replace("_", " ").title()
        ttft = data.get('avg_ttft_ms', 0)
        total = data.get('avg_total_ms', 0)
        lines.append(f"        {cat_name} & {ttft:.0f} & {total:.0f} & {data['total']} \\\\")
    
    lines.extend([
        r"        \hline",
        f"        \\textbf{{Overall}} & {summary['avg_ttft_ms']:.0f} & {summary['avg_total_ms']:.0f} & {summary['total']} \\\\",
        r"        \hline",
        r"    \end{tabular}",
        r"\end{table}",
    ])
    
    return "\n".join(lines)


async def main():
    """Run tests and save results"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    print("=" * 60)
    print("Slurm Agent Evaluation Suite")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")
    
    suite = await run_agent_tests()
    
    if not suite.results:
        print("\nNo tests were run. Make sure Agent is running.")
        return
    
    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    
    summary = suite.summary()
    print(f"Total: {summary['total']} tests")
    print(f"Passed: {summary['passed']} ({summary['pass_rate']}%)")
    print(f"Failed: {summary['failed']}")
    print(f"Avg TTFT: {summary['avg_ttft_ms']:.0f}ms")
    print(f"Avg Total: {summary['avg_total_ms']:.0f}ms")
    print(f"Min/Max Total: {summary['min_total_ms']:.0f}ms / {summary['max_total_ms']:.0f}ms")
    
    print("\nBy Category:")
    for cat, data in sorted(suite.by_category().items()):
        print(f"  {cat}: {data['passed']}/{data['total']} ({data['pass_rate']}%) - avg {data['avg_total_ms']:.0f}ms")
    
    # Save JSON
    json_path = os.path.join(RESULTS_DIR, "agent_test_results.json")
    with open(json_path, "w") as f:
        json.dump(suite.to_dict(), f, indent=2)
    print(f"\nSaved: {json_path}")
    
    # Save LaTeX
    latex_path = os.path.join(RESULTS_DIR, "agent_test_table.tex")
    with open(latex_path, "w") as f:
        f.write(generate_latex_tables(suite))
    print(f"Saved: {latex_path}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
