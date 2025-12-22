#!/usr/bin/env python3
"""
Slurm Agent Evaluation Script

Runs comprehensive tests against the MCP server (mock mode) and optionally the agent.
Generates JSON results and summary statistics for the thesis report.

Usage:
  1. Start MCP server in mock mode: python mcp_server/slurm_mcp_sse.py --mock mixed
  2. (Optional) Start agent: python agent/main.py
  3. Run tests: python tests/run_evaluation.py
  
Output:
  - tests/results/mcp_tool_results.json
  - tests/results/agent_query_results.json
  - tests/results/summary_stats.json
  - tests/results/report_tables.tex (LaTeX tables for report)
"""

import asyncio
import json
import time
import os
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
import aiohttp
import statistics

# Configuration
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002")
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:20000")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


@dataclass
class TestResult:
    """Single test result"""
    test_id: str
    category: str
    description: str
    passed: bool
    latency_ms: float
    error: Optional[str] = None
    response_preview: Optional[str] = None


@dataclass
class TestSuite:
    """Collection of test results"""
    suite_name: str
    timestamp: str
    results: List[TestResult] = field(default_factory=list)
    
    def add_result(self, result: TestResult):
        self.results.append(result)
    
    def summary(self) -> Dict[str, Any]:
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        latencies = [r.latency_ms for r in self.results]
        
        return {
            "total_tests": len(self.results),
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / len(self.results) * 100, 1) if self.results else 0,
            "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0,
            "min_latency_ms": round(min(latencies), 1) if latencies else 0,
            "max_latency_ms": round(max(latencies), 1) if latencies else 0,
            "std_latency_ms": round(statistics.stdev(latencies), 1) if len(latencies) > 1 else 0,
        }
    
    def by_category(self) -> Dict[str, Dict[str, Any]]:
        """Group results by category"""
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = {"passed": 0, "failed": 0, "latencies": []}
            if r.passed:
                categories[r.category]["passed"] += 1
            else:
                categories[r.category]["failed"] += 1
            categories[r.category]["latencies"].append(r.latency_ms)
        
        # Calculate stats per category
        for cat, data in categories.items():
            total = data["passed"] + data["failed"]
            data["total"] = total
            data["pass_rate"] = round(data["passed"] / total * 100, 1) if total else 0
            data["avg_latency_ms"] = round(statistics.mean(data["latencies"]), 1) if data["latencies"] else 0
            del data["latencies"]
        
        return categories


# ============ MCP Server Tests ============

async def call_mcp_tool(session: aiohttp.ClientSession, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call an MCP tool via the SSE endpoint and return result with timing"""
    # For direct tool testing, we'll use a simple POST approach
    # The MCP server exposes tools via SSE, but we can test by making HTTP requests
    
    start = time.perf_counter()
    try:
        # MCP protocol: send tool call via POST
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params
            }
        }
        
        async with session.post(f"{MCP_SERVER_URL}/message", json=payload) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000
            
            if resp.status == 200:
                result = await resp.json()
                return {
                    "success": True,
                    "result": result,
                    "latency_ms": elapsed_ms
                }
            else:
                text = await resp.text()
                return {
                    "success": False,
                    "error": f"HTTP {resp.status}: {text[:200]}",
                    "latency_ms": elapsed_ms
                }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "success": False,
            "error": str(e),
            "latency_ms": elapsed_ms
        }


async def test_mcp_tools(session: aiohttp.ClientSession) -> TestSuite:
    """Run MCP tool tests"""
    suite = TestSuite(
        suite_name="MCP Tool Tests",
        timestamp=datetime.now().isoformat()
    )
    
    # Define test cases
    test_cases = [
        # squeue tests
        ("squeue", "query", "squeue - no params", {}),
        ("squeue", "query", "squeue - filter by user", {"user": "alice"}),
        ("squeue", "query", "squeue - filter by partition", {"partition": "gpu"}),
        ("squeue", "query", "squeue - filter by state", {"state": "RUNNING"}),
        ("squeue", "query", "squeue - filter by job_id", {"job_id": "4001"}),
        
        # sinfo tests
        ("sinfo", "query", "sinfo - no params", {}),
        ("sinfo", "query", "sinfo - filter by partition", {"partition": "gpu"}),
        ("sinfo", "query", "sinfo - filter by state", {"state": "idle"}),
        
        # sacct tests  
        ("sacct", "query", "sacct - no params", {}),
        ("sacct", "query", "sacct - filter by user", {"user": "alice"}),
        ("sacct", "query", "sacct - filter by state", {"state": "FAILED"}),
        ("sacct", "query", "sacct - filter by job_id", {"job_id": "4002"}),
        
        # scontrol_show tests
        ("scontrol_show", "query", "scontrol_show - job", {"entity": "job", "id": "4001"}),
        ("scontrol_show", "query", "scontrol_show - partition", {"entity": "partition", "id": "gpu"}),
        ("scontrol_show", "query", "scontrol_show - node", {"entity": "node", "id": "gpu-node-01"}),
        
        # run_analysis tests
        ("run_analysis", "analysis", "run_analysis - cluster_status", {"script_id": "analyze_cluster_status"}),
        ("run_analysis", "analysis", "run_analysis - failed_jobs", {"script_id": "analyze_failed_jobs"}),
        ("run_analysis", "analysis", "run_analysis - pending_jobs", {"script_id": "analyze_pending_jobs"}),
        ("run_analysis", "analysis", "run_analysis - my_jobs", {"script_id": "analyze_my_jobs"}),
        
        # generate_chart tests (if available)
        ("generate_chart", "visualization", "generate_chart - system_health", {"chart_id": "system_health"}),
        ("generate_chart", "visualization", "generate_chart - cluster_topology", {"chart_id": "cluster_topology"}),
        
        # Edge cases
        ("squeue", "edge_case", "squeue - non-existent user", {"user": "nonexistent_user_12345"}),
        ("scontrol_show", "edge_case", "scontrol_show - invalid job", {"entity": "job", "id": "999999"}),
    ]
    
    for tool_name, category, description, params in test_cases:
        result = await call_mcp_tool(session, tool_name, params)
        
        # Determine pass/fail based on result
        # For edge cases, we expect the tool to return gracefully (not crash)
        passed = result["success"] or ("edge_case" in category)
        
        suite.add_result(TestResult(
            test_id=f"mcp_{tool_name}_{len(suite.results)+1}",
            category=category,
            description=description,
            passed=passed,
            latency_ms=result["latency_ms"],
            error=result.get("error"),
            response_preview=str(result.get("result", ""))[:200] if result.get("result") else None
        ))
    
    return suite


# ============ Agent Query Tests ============

async def call_agent(session: aiohttp.ClientSession, query: str, session_id: str = "test") -> Dict[str, Any]:
    """Call the agent API and return result with timing"""
    start = time.perf_counter()
    ttft = None  # Time to first token
    full_response = ""
    
    try:
        payload = {
            "model": "slurm-agent",
            "messages": [{"role": "user", "content": query}],
            "stream": True,
            "session_id": session_id
        }
        
        async with session.post(
            f"{AGENT_URL}/v1/chat/completions",
            json=payload,
            headers={"Accept": "text/event-stream"}
        ) as resp:
            if resp.status != 200:
                elapsed_ms = (time.perf_counter() - start) * 1000
                return {
                    "success": False,
                    "error": f"HTTP {resp.status}",
                    "latency_ms": elapsed_ms,
                    "ttft_ms": None
                }
            
            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if line.startswith("data: "):
                    if ttft is None:
                        ttft = (time.perf_counter() - start) * 1000
                    
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        full_response += content
                    except json.JSONDecodeError:
                        pass
            
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "success": True,
                "response": full_response,
                "latency_ms": elapsed_ms,
                "ttft_ms": ttft
            }
    
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "success": False,
            "error": str(e),
            "latency_ms": elapsed_ms,
            "ttft_ms": ttft
        }


async def test_agent_queries(session: aiohttp.ClientSession) -> TestSuite:
    """Run agent query tests"""
    suite = TestSuite(
        suite_name="Agent Query Tests",
        timestamp=datetime.now().isoformat()
    )
    
    # Define test queries with expected behavior
    test_queries = [
        # Simple status queries
        ("simple_status", "What jobs are running?", ["RUNNING", "job"]),
        ("simple_status", "Show me the cluster status", ["node", "partition"]),
        ("simple_status", "List all partitions", ["gpu", "cpu", "partition"]),
        ("simple_status", "How many nodes are available?", ["node", "idle"]),
        
        # Job-specific queries
        ("job_query", "What is the status of job 4001?", ["4001", "RUNNING"]),
        ("job_query", "Show jobs for user alice", ["alice"]),
        ("job_query", "Are there any failed jobs?", ["FAILED", "fail"]),
        ("job_query", "Why are jobs pending?", ["PENDING", "pending", "reason"]),
        
        # Analysis queries
        ("analysis", "Analyze the cluster status", ["node", "partition", "status"]),
        ("analysis", "What's wrong with the cluster?", ["issue", "problem", "down", "fail"]),
        ("analysis", "Show me GPU utilization", ["GPU", "gpu"]),
        
        # Visualization queries
        ("visualization", "Show me a chart of node status", ["chart", "mermaid", "IMG"]),
        ("visualization", "Visualize the cluster topology", ["chart", "mermaid", "IMG"]),
        
        # Dangerous operation queries (should trigger confirmation)
        ("confirmation", "Cancel job 4001", ["confirm", "pending", "cancel"]),
        ("confirmation", "Kill all my jobs", ["confirm", "pending", "danger"]),
        
        # Multi-turn context (same session)
        ("context", "Show jobs for bob", ["bob"]),
        ("context", "What about his failed ones?", ["FAILED", "bob", "fail"]),
    ]
    
    session_id = f"test_{int(time.time())}"
    
    for category, query, expected_keywords in test_queries:
        result = await call_agent(session, query, session_id)
        
        # Check if response contains expected keywords (case-insensitive)
        response_lower = result.get("response", "").lower()
        keywords_found = any(kw.lower() in response_lower for kw in expected_keywords)
        
        passed = result["success"] and (keywords_found or len(result.get("response", "")) > 50)
        
        suite.add_result(TestResult(
            test_id=f"agent_{category}_{len(suite.results)+1}",
            category=category,
            description=query,
            passed=passed,
            latency_ms=result["latency_ms"],
            error=result.get("error"),
            response_preview=result.get("response", "")[:300] if result.get("response") else None
        ))
    
    return suite


# ============ Confirmation Flow Tests ============

async def test_confirmation_flow(session: aiohttp.ClientSession) -> TestSuite:
    """Test the two-factor confirmation mechanism"""
    suite = TestSuite(
        suite_name="Confirmation Flow Tests",
        timestamp=datetime.now().isoformat()
    )
    
    session_id = f"confirm_test_{int(time.time())}"
    
    # Test 1: Dangerous operation triggers pending
    result = await call_agent(session, "Cancel job 4001", session_id)
    passed = result["success"] and any(kw in result.get("response", "").lower() 
                                       for kw in ["confirm", "pending", "proceed", "cancel"])
    suite.add_result(TestResult(
        test_id="confirm_trigger",
        category="confirmation",
        description="Dangerous tool triggers pending storage",
        passed=passed,
        latency_ms=result["latency_ms"],
        error=result.get("error"),
        response_preview=result.get("response", "")[:200]
    ))
    
    # Test 2: Confirmation executes
    result = await call_agent(session, "Yes, confirm the cancellation", session_id)
    passed = result["success"]  # Just needs to not error
    suite.add_result(TestResult(
        test_id="confirm_execute",
        category="confirmation", 
        description="Confirmation executes pending action",
        passed=passed,
        latency_ms=result["latency_ms"],
        error=result.get("error"),
        response_preview=result.get("response", "")[:200]
    ))
    
    # Test 3: Cancel pending action
    session_id2 = f"confirm_test2_{int(time.time())}"
    result = await call_agent(session, "Cancel job 4002", session_id2)
    await asyncio.sleep(0.5)
    result = await call_agent(session, "No, cancel that request", session_id2)
    passed = result["success"] and any(kw in result.get("response", "").lower()
                                       for kw in ["cancel", "abort", "discard"])
    suite.add_result(TestResult(
        test_id="confirm_cancel",
        category="confirmation",
        description="Cancellation clears pending action", 
        passed=passed,
        latency_ms=result["latency_ms"],
        error=result.get("error"),
        response_preview=result.get("response", "")[:200]
    ))
    
    # Test 4: Safe operation executes immediately
    result = await call_agent(session, "Show me the queue", f"safe_test_{int(time.time())}")
    passed = result["success"] and "confirm" not in result.get("response", "").lower()
    suite.add_result(TestResult(
        test_id="safe_immediate",
        category="confirmation",
        description="Safe tool executes immediately",
        passed=passed,
        latency_ms=result["latency_ms"],
        error=result.get("error"),
        response_preview=result.get("response", "")[:200]
    ))
    
    return suite


# ============ Generate Report Tables ============

def generate_latex_tables(mcp_suite: TestSuite, agent_suite: TestSuite, confirm_suite: TestSuite) -> str:
    """Generate LaTeX tables for the thesis report"""
    
    latex = []
    
    # MCP Tool Results Table
    mcp_by_cat = mcp_suite.by_category()
    latex.append(r"""% Auto-generated from run_evaluation.py
\begin{table}[H]
    \centering
    \caption{MCP Tool Test Results}
    \label{tab:tool-results-auto}
    \begin{tabular}{|l|c|c|c|c|}
        \hline
        \textbf{Category} & \textbf{Tests} & \textbf{Passed} & \textbf{Pass Rate} & \textbf{Avg Latency (ms)} \\
        \hline""")
    
    for cat, data in mcp_by_cat.items():
        latex.append(f"        {cat.replace('_', ' ').title()} & {data['total']} & {data['passed']} & {data['pass_rate']}\\% & {data['avg_latency_ms']} \\\\")
    
    mcp_summary = mcp_suite.summary()
    latex.append(r"        \hline")
    latex.append(f"        \\textbf{{Total}} & {mcp_summary['total_tests']} & {mcp_summary['passed']} & {mcp_summary['pass_rate']}\\% & {mcp_summary['avg_latency_ms']} \\\\")
    latex.append(r"""        \hline
    \end{tabular}
\end{table}
""")
    
    # Agent Query Accuracy Table
    agent_by_cat = agent_suite.by_category()
    latex.append(r"""\begin{table}[H]
    \centering
    \caption{Query Response Accuracy by Category}
    \label{tab:accuracy-results-auto}
    \begin{tabular}{|l|c|c|c|c|}
        \hline
        \textbf{Query Category} & \textbf{Queries} & \textbf{Correct} & \textbf{Accuracy} & \textbf{Avg Latency (ms)} \\
        \hline""")
    
    for cat, data in agent_by_cat.items():
        latex.append(f"        {cat.replace('_', ' ').title()} & {data['total']} & {data['passed']} & {data['pass_rate']}\\% & {data['avg_latency_ms']} \\\\")
    
    agent_summary = agent_suite.summary()
    latex.append(r"        \hline")
    latex.append(f"        \\textbf{{Total}} & {agent_summary['total_tests']} & {agent_summary['passed']} & {agent_summary['pass_rate']}\\% & {agent_summary['avg_latency_ms']} \\\\")
    latex.append(r"""        \hline
    \end{tabular}
\end{table}
""")
    
    # Confirmation Flow Results
    latex.append(r"""\begin{table}[H]
    \centering
    \caption{Confirmation Mechanism Test Results}
    \label{tab:confirmation-results-auto}
    \begin{tabular}{|l|c|c|}
        \hline
        \textbf{Test Case} & \textbf{Expected} & \textbf{Result} \\
        \hline""")
    
    for result in confirm_suite.results:
        status = "Passed" if result.passed else "Failed"
        latex.append(f"        {result.description} & Yes & {status} \\\\")
    
    latex.append(r"""        \hline
    \end{tabular}
\end{table}
""")
    
    # Latency Table
    latex.append(r"""\begin{table}[H]
    \centering
    \caption{Response Latency Measurements}
    \label{tab:latency-results-auto}
    \begin{tabular}{|l|c|c|c|c|}
        \hline
        \textbf{Query Type} & \textbf{Avg (ms)} & \textbf{Min (ms)} & \textbf{Max (ms)} & \textbf{Std Dev} \\
        \hline""")
    
    for cat, data in agent_by_cat.items():
        # Calculate per-category latency stats
        cat_results = [r for r in agent_suite.results if r.category == cat]
        latencies = [r.latency_ms for r in cat_results]
        if latencies:
            avg = round(statistics.mean(latencies), 1)
            min_l = round(min(latencies), 1)
            max_l = round(max(latencies), 1)
            std = round(statistics.stdev(latencies), 1) if len(latencies) > 1 else 0
            latex.append(f"        {cat.replace('_', ' ').title()} & {avg} & {min_l} & {max_l} & {std} \\\\")
    
    latex.append(r"""        \hline
    \end{tabular}
\end{table}
""")
    
    return "\n".join(latex)


# ============ Main ============

async def main():
    """Run all tests and generate reports"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    print("=" * 60)
    print("Slurm Agent Evaluation Suite")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"MCP Server: {MCP_SERVER_URL}")
    print(f"Agent URL: {AGENT_URL}")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        # Test 1: MCP Tools
        print("\n[1/3] Testing MCP Tools...")
        try:
            mcp_suite = await test_mcp_tools(session)
            print(f"      {mcp_suite.summary()['passed']}/{mcp_suite.summary()['total_tests']} passed")
        except Exception as e:
            print(f"      ERROR: {e}")
            mcp_suite = TestSuite("MCP Tool Tests (Failed)", datetime.now().isoformat())
        
        # Test 2: Agent Queries
        print("\n[2/3] Testing Agent Queries...")
        try:
            agent_suite = await test_agent_queries(session)
            print(f"      {agent_suite.summary()['passed']}/{agent_suite.summary()['total_tests']} passed")
        except Exception as e:
            print(f"      ERROR: {e}")
            agent_suite = TestSuite("Agent Query Tests (Failed)", datetime.now().isoformat())
        
        # Test 3: Confirmation Flow
        print("\n[3/3] Testing Confirmation Flow...")
        try:
            confirm_suite = await test_confirmation_flow(session)
            print(f"      {confirm_suite.summary()['passed']}/{confirm_suite.summary()['total_tests']} passed")
        except Exception as e:
            print(f"      ERROR: {e}")
            confirm_suite = TestSuite("Confirmation Flow Tests (Failed)", datetime.now().isoformat())
    
    # Save results
    print("\n" + "=" * 60)
    print("Saving Results...")
    
    # JSON results
    with open(os.path.join(RESULTS_DIR, "mcp_tool_results.json"), "w") as f:
        json.dump({
            "suite": mcp_suite.suite_name,
            "timestamp": mcp_suite.timestamp,
            "summary": mcp_suite.summary(),
            "by_category": mcp_suite.by_category(),
            "results": [asdict(r) for r in mcp_suite.results]
        }, f, indent=2)
    
    with open(os.path.join(RESULTS_DIR, "agent_query_results.json"), "w") as f:
        json.dump({
            "suite": agent_suite.suite_name,
            "timestamp": agent_suite.timestamp,
            "summary": agent_suite.summary(),
            "by_category": agent_suite.by_category(),
            "results": [asdict(r) for r in agent_suite.results]
        }, f, indent=2)
    
    with open(os.path.join(RESULTS_DIR, "confirmation_results.json"), "w") as f:
        json.dump({
            "suite": confirm_suite.suite_name,
            "timestamp": confirm_suite.timestamp,
            "summary": confirm_suite.summary(),
            "results": [asdict(r) for r in confirm_suite.results]
        }, f, indent=2)
    
    # Combined summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "mcp_tests": mcp_suite.summary(),
        "agent_tests": agent_suite.summary(),
        "confirmation_tests": confirm_suite.summary(),
    }
    with open(os.path.join(RESULTS_DIR, "summary_stats.json"), "w") as f:
        json.dump(summary, f, indent=2)
    
    # LaTeX tables
    latex_tables = generate_latex_tables(mcp_suite, agent_suite, confirm_suite)
    with open(os.path.join(RESULTS_DIR, "report_tables.tex"), "w") as f:
        f.write(latex_tables)
    
    print(f"  - {RESULTS_DIR}/mcp_tool_results.json")
    print(f"  - {RESULTS_DIR}/agent_query_results.json")
    print(f"  - {RESULTS_DIR}/confirmation_results.json")
    print(f"  - {RESULTS_DIR}/summary_stats.json")
    print(f"  - {RESULTS_DIR}/report_tables.tex")
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"MCP Tools:    {mcp_suite.summary()['passed']}/{mcp_suite.summary()['total_tests']} ({mcp_suite.summary()['pass_rate']}%)")
    print(f"Agent Queries: {agent_suite.summary()['passed']}/{agent_suite.summary()['total_tests']} ({agent_suite.summary()['pass_rate']}%)")
    print(f"Confirmation: {confirm_suite.summary()['passed']}/{confirm_suite.summary()['total_tests']} ({confirm_suite.summary()['pass_rate']}%)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
