"""
Mock Slurm Data for Testing

Contains realistic mock data for various test scenarios.
Load with: python slurm_mcp_sse.py --mock [scenario]

Scenarios:
- healthy: Normal cluster, all jobs running fine
- failed: Some failed jobs to investigate
- pending: Jobs stuck in queue
- mixed: Combination of issues
- debug_needed: Obscure errors requiring web search to diagnose
"""

from typing import Dict, Any
from datetime import datetime, timedelta
import random

# ============ Mock Job Data ============

MOCK_JOBS = {
    "healthy": [
        {"job_id": "1001", "name": "train_model_v1", "user": "alice", "state": "RUNNING", "time": "02:30:15", "nodes": 2, "cpus": 16, "mem": "32G", "partition": "gpu"},
        {"job_id": "1002", "name": "data_preprocess", "user": "bob", "state": "RUNNING", "time": "00:45:22", "nodes": 1, "cpus": 8, "mem": "16G", "partition": "cpu"},
        {"job_id": "1003", "name": "inference_batch", "user": "alice", "state": "RUNNING", "time": "01:12:08", "nodes": 1, "cpus": 4, "mem": "8G", "partition": "gpu"},
        {"job_id": "1004", "name": "analysis_job", "user": "charlie", "state": "PENDING", "time": "0:00", "nodes": 1, "cpus": 4, "mem": "4G", "partition": "cpu"},
    ],
    "failed": [
        {"job_id": "2001", "name": "train_large_model", "user": "alice", "state": "FAILED", "time": "00:05:32", "nodes": 4, "cpus": 32, "mem": "128G", "partition": "gpu", "exit_code": "1:0", "reason": "OOM killer"},
        {"job_id": "2002", "name": "data_pipeline", "user": "bob", "state": "FAILED", "time": "00:00:45", "nodes": 1, "cpus": 8, "mem": "16G", "partition": "cpu", "exit_code": "127:0", "reason": "Command not found"},
        {"job_id": "2003", "name": "backup_job", "user": "charlie", "state": "TIMEOUT", "time": "24:00:00", "nodes": 1, "cpus": 2, "mem": "4G", "partition": "cpu", "exit_code": "0:15", "reason": "Time limit reached"},
        {"job_id": "2004", "name": "gpu_test", "user": "alice", "state": "RUNNING", "time": "00:30:00", "nodes": 1, "cpus": 8, "mem": "16G", "partition": "gpu"},
        {"job_id": "2005", "name": "failed_again", "user": "bob", "state": "FAILED", "time": "00:02:15", "nodes": 1, "cpus": 4, "mem": "8G", "partition": "cpu", "exit_code": "1:0", "reason": "Segmentation fault"},
    ],
    "pending": [
        {"job_id": "3001", "name": "big_gpu_job", "user": "alice", "state": "PENDING", "time": "0:00", "nodes": 8, "cpus": 64, "mem": "256G", "partition": "gpu", "reason": "Resources"},
        {"job_id": "3002", "name": "waiting_job", "user": "bob", "state": "PENDING", "time": "0:00", "nodes": 2, "cpus": 16, "mem": "32G", "partition": "cpu", "reason": "Priority"},
        {"job_id": "3003", "name": "queue_test", "user": "charlie", "state": "PENDING", "time": "0:00", "nodes": 1, "cpus": 4, "mem": "8G", "partition": "gpu", "reason": "QOSMaxJobsPerUserLimit"},
        {"job_id": "3004", "name": "dependency_job", "user": "alice", "state": "PENDING", "time": "0:00", "nodes": 1, "cpus": 8, "mem": "16G", "partition": "cpu", "reason": "Dependency"},
        {"job_id": "3005", "name": "running_one", "user": "bob", "state": "RUNNING", "time": "01:00:00", "nodes": 1, "cpus": 4, "mem": "8G", "partition": "cpu"},
    ],
    "mixed": [
        {"job_id": "4001", "name": "ml_training", "user": "alice", "state": "RUNNING", "time": "05:30:00", "nodes": 2, "cpus": 16, "mem": "64G", "partition": "gpu"},
        {"job_id": "4002", "name": "etl_pipeline", "user": "bob", "state": "FAILED", "time": "00:10:00", "nodes": 1, "cpus": 8, "mem": "16G", "partition": "cpu", "exit_code": "1:0", "reason": "Script error"},
        {"job_id": "4003", "name": "batch_inference", "user": "charlie", "state": "PENDING", "time": "0:00", "nodes": 4, "cpus": 32, "mem": "128G", "partition": "gpu", "reason": "Resources"},
        {"job_id": "4004", "name": "data_export", "user": "alice", "state": "COMPLETED", "time": "00:45:00", "nodes": 1, "cpus": 4, "mem": "8G", "partition": "cpu"},
        {"job_id": "4005", "name": "model_eval", "user": "bob", "state": "RUNNING", "time": "02:15:00", "nodes": 1, "cpus": 8, "mem": "32G", "partition": "gpu"},
        {"job_id": "4006", "name": "stuck_job", "user": "charlie", "state": "PENDING", "time": "0:00", "nodes": 1, "cpus": 2, "mem": "4G", "partition": "cpu", "reason": "Priority"},
    ],
    # New scenario with obscure errors that require web search to debug
    "debug_needed": [
        {"job_id": "5001", "name": "cuda_training", "user": "alice", "state": "FAILED", "time": "00:02:15", "nodes": 2, "cpus": 16, "mem": "64G", "partition": "gpu", "exit_code": "134:0", "reason": "NonZeroExitCode", 
         "stderr": "CUDA error: an illegal memory access was encountered\nCUDA kernel errors might be asynchronously reported\nAborted (core dumped)"},
        {"job_id": "5002", "name": "mpi_distributed", "user": "bob", "state": "FAILED", "time": "00:00:32", "nodes": 4, "cpus": 32, "mem": "128G", "partition": "cpu", "exit_code": "139:0", "reason": "NonZeroExitCode",
         "stderr": "srun: error: node-03: task 12: Segmentation fault (core dumped)\nsrun: Terminating job step 5002.0\nPMIx: finalize"},
        {"job_id": "5003", "name": "pytorch_ddp", "user": "charlie", "state": "FAILED", "time": "00:05:45", "nodes": 2, "cpus": 16, "mem": "64G", "partition": "gpu", "exit_code": "1:0", "reason": "NonZeroExitCode",
         "stderr": "RuntimeError: NCCL error in: ../torch/lib/c10d/ProcessGroupNCCL.cpp:825\nncclSystemError: System call (e.g. socket, malloc) or external library call failed"},
        {"job_id": "5004", "name": "slurm_array", "user": "alice", "state": "PENDING", "time": "0:00", "nodes": 1, "cpus": 4, "mem": "8G", "partition": "cpu", "reason": "AssocGrpCPUMinutesLimit",
         "stderr": ""},
        {"job_id": "5005", "name": "tensorflow_job", "user": "bob", "state": "FAILED", "time": "00:01:05", "nodes": 1, "cpus": 8, "mem": "32G", "partition": "gpu", "exit_code": "137:0", "reason": "NonZeroExitCode",
         "stderr": "slurmstepd: error: Detected 1 oom-kill event(s) in StepId=5005.batch. Some of your processes may have been killed by the cgroup out-of-memory handler."},
        {"job_id": "5006", "name": "infiniband_test", "user": "charlie", "state": "FAILED", "time": "00:00:15", "nodes": 2, "cpus": 8, "mem": "16G", "partition": "cpu", "exit_code": "1:0", "reason": "NonZeroExitCode",
         "stderr": "libibverbs: Warning: couldn't open config directory '/etc/libibverbs.d'\n[node-02:12345] [[INVALID],INVALID] routed_radix_open - Failed to connect to rdmacm server on node-01"},
        {"job_id": "5007", "name": "lustre_io", "user": "alice", "state": "FAILED", "time": "00:10:22", "nodes": 1, "cpus": 4, "mem": "8G", "partition": "cpu", "exit_code": "5:0", "reason": "NonZeroExitCode",
         "stderr": "lfs: error: setstripe: unable to create /lustre/scratch/alice/output: Invalid argument\nError: Lustre striping failed"},
        {"job_id": "5008", "name": "healthy_job", "user": "bob", "state": "RUNNING", "time": "01:30:00", "nodes": 1, "cpus": 8, "mem": "16G", "partition": "cpu"},
    ],
}

# ============ Mock Node Data ============

MOCK_NODES = {
    "healthy": [
        {"name": "gpu-node-01", "state": "idle", "cpus": "0/32", "mem": "0/128G", "partition": "gpu", "gres": "gpu:4"},
        {"name": "gpu-node-02", "state": "alloc", "cpus": "32/32", "mem": "120G/128G", "partition": "gpu", "gres": "gpu:4"},
        {"name": "cpu-node-01", "state": "mix", "cpus": "16/64", "mem": "32G/256G", "partition": "cpu", "gres": ""},
        {"name": "cpu-node-02", "state": "idle", "cpus": "0/64", "mem": "0/256G", "partition": "cpu", "gres": ""},
    ],
    "failed": [
        {"name": "gpu-node-01", "state": "down", "cpus": "0/32", "mem": "0/128G", "partition": "gpu", "gres": "gpu:4", "reason": "Hardware failure"},
        {"name": "gpu-node-02", "state": "alloc", "cpus": "32/32", "mem": "128G/128G", "partition": "gpu", "gres": "gpu:4"},
        {"name": "cpu-node-01", "state": "drain", "cpus": "0/64", "mem": "0/256G", "partition": "cpu", "gres": "", "reason": "Maintenance"},
        {"name": "cpu-node-02", "state": "mix", "cpus": "48/64", "mem": "200G/256G", "partition": "cpu", "gres": ""},
    ],
    "pending": [
        {"name": "gpu-node-01", "state": "alloc", "cpus": "32/32", "mem": "128G/128G", "partition": "gpu", "gres": "gpu:4"},
        {"name": "gpu-node-02", "state": "alloc", "cpus": "32/32", "mem": "128G/128G", "partition": "gpu", "gres": "gpu:4"},
        {"name": "cpu-node-01", "state": "alloc", "cpus": "64/64", "mem": "256G/256G", "partition": "cpu", "gres": ""},
        {"name": "cpu-node-02", "state": "alloc", "cpus": "64/64", "mem": "256G/256G", "partition": "cpu", "gres": ""},
    ],
    "mixed": [
        {"name": "gpu-node-01", "state": "mix", "cpus": "16/32", "mem": "64G/128G", "partition": "gpu", "gres": "gpu:4"},
        {"name": "gpu-node-02", "state": "down", "cpus": "0/32", "mem": "0/128G", "partition": "gpu", "gres": "gpu:4", "reason": "GPU error"},
        {"name": "cpu-node-01", "state": "alloc", "cpus": "64/64", "mem": "256G/256G", "partition": "cpu", "gres": ""},
        {"name": "cpu-node-02", "state": "idle", "cpus": "0/64", "mem": "0/256G", "partition": "cpu", "gres": ""},
    ],
    # Nodes with issues that require debugging
    "debug_needed": [
        {"name": "gpu-node-01", "state": "mix", "cpus": "24/32", "mem": "96G/128G", "partition": "gpu", "gres": "gpu:4"},
        {"name": "gpu-node-02", "state": "drain", "cpus": "0/32", "mem": "0/128G", "partition": "gpu", "gres": "gpu:4", "reason": "CUDA ECC error detected"},
        {"name": "gpu-node-03", "state": "down*", "cpus": "0/32", "mem": "0/128G", "partition": "gpu", "gres": "gpu:4", "reason": "Not responding - InfiniBand link down"},
        {"name": "cpu-node-01", "state": "alloc", "cpus": "64/64", "mem": "256G/256G", "partition": "cpu", "gres": ""},
        {"name": "cpu-node-02", "state": "drain", "cpus": "0/64", "mem": "0/256G", "partition": "cpu", "gres": "", "reason": "Lustre client hung"},
        {"name": "cpu-node-03", "state": "mix", "cpus": "32/64", "mem": "128G/256G", "partition": "cpu", "gres": ""},
    ],
}

# ============ Mock Job Details ============

def get_mock_job_details(job_id: str, scenario: str) -> Dict[str, Any]:
    """Get detailed scontrol show job output for a job."""
    jobs = MOCK_JOBS.get(scenario, MOCK_JOBS["healthy"])
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    
    if not job:
        return {"error": f"Job {job_id} not found"}
    
    now = datetime.now()
    submit_time = now - timedelta(hours=random.randint(1, 24))
    start_time = submit_time + timedelta(minutes=random.randint(1, 60)) if job["state"] != "PENDING" else "N/A"
    
    details = {
        "JobId": job["job_id"],
        "JobName": job["name"],
        "UserId": f"{job['user']}(1000)",
        "GroupId": f"{job['user']}(1000)",
        "Priority": random.randint(1000, 9999),
        "Account": job["user"],
        "QOS": "normal",
        "JobState": job["state"],
        "Reason": job.get("reason", "None"),
        "Partition": job["partition"],
        "NumNodes": job["nodes"],
        "NumCPUs": job["cpus"],
        "MinMemoryNode": job["mem"],
        "SubmitTime": submit_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "StartTime": start_time.strftime("%Y-%m-%dT%H:%M:%S") if isinstance(start_time, datetime) else start_time,
        "RunTime": job["time"],
        "TimeLimit": "24:00:00",
        "ExitCode": job.get("exit_code", "0:0"),
        "WorkDir": f"/home/{job['user']}/projects/{job['name']}",
        "StdOut": f"/home/{job['user']}/logs/{job['name']}_%j.out",
        "StdErr": f"/home/{job['user']}/logs/{job['name']}_%j.err",
        "Command": f"/home/{job['user']}/scripts/{job['name']}.sh",
    }
    
    if job["partition"] == "gpu":
        details["Gres"] = "gpu:2"
        details["TresPerNode"] = "gpu:2"
    
    # Include stderr content for debug_needed scenario
    if job.get("stderr"):
        details["StdErrContent"] = job["stderr"]
    
    return details


# ============ Output Formatters ============

def format_squeue_output(jobs: list, filters: Dict[str, str] = None) -> str:
    """Format jobs as squeue output."""
    filters = filters or {}
    
    # Apply filters
    filtered = jobs
    if filters.get("user"):
        filtered = [j for j in filtered if j["user"] == filters["user"]]
    if filters.get("state"):
        filtered = [j for j in filtered if j["state"] == filters["state"]]
    if filters.get("job_id"):
        filtered = [j for j in filtered if j["job_id"] == filters["job_id"]]
    if filters.get("partition"):
        filtered = [j for j in filtered if j["partition"] == filters["partition"]]
    
    if not filtered:
        return "JOBID|NAME|ST|TIME|NODES|CPUS|MIN_MEM|PARTITION|USER\n"
    
    lines = ["JOBID|NAME|ST|TIME|NODES|CPUS|MIN_MEM|PARTITION|USER"]
    for j in filtered:
        state_short = {"RUNNING": "R", "PENDING": "PD", "COMPLETED": "CD", "FAILED": "F", "TIMEOUT": "TO", "CANCELLED": "CA"}.get(j["state"], j["state"][:2])
        lines.append(f"{j['job_id']}|{j['name']}|{state_short}|{j['time']}|{j['nodes']}|{j['cpus']}|{j['mem']}|{j['partition']}|{j['user']}")
    
    return "\n".join(lines)


def format_sacct_output(jobs: list, filters: Dict[str, str] = None) -> str:
    """Format jobs as sacct output."""
    filters = filters or {}
    
    filtered = jobs
    if filters.get("user"):
        filtered = [j for j in filtered if j["user"] == filters["user"]]
    if filters.get("state"):
        filtered = [j for j in filtered if j["state"] == filters["state"]]
    if filters.get("job_id"):
        filtered = [j for j in filtered if j["job_id"] == filters["job_id"]]
    
    lines = ["JobID           JobName         State      Elapsed   AllocCPUS     MaxRSS   ExitCode"]
    lines.append("--------------- --------------- ---------- ---------- ---------- ---------- --------")
    
    for j in filtered:
        exit_code = j.get("exit_code", "0:0")
        max_rss = f"{random.randint(1, 32)}G" if j["state"] in ["COMPLETED", "FAILED", "TIMEOUT", "RUNNING"] else ""
        lines.append(f"{j['job_id']:15} {j['name'][:15]:15} {j['state']:10} {j['time']:>10} {j['cpus']:>10} {max_rss:>10} {exit_code:>8}")
        # Add batch step for completed/failed jobs
        if j["state"] in ["COMPLETED", "FAILED", "TIMEOUT"]:
            lines.append(f"{j['job_id']}.batch {'batch':15} {j['state']:10} {j['time']:>10} {j['cpus']:>10} {max_rss:>10} {exit_code:>8}")
    
    return "\n".join(lines)


def format_sinfo_output(nodes: list, filters: Dict[str, str] = None) -> str:
    """Format nodes as sinfo output."""
    filters = filters or {}
    
    filtered = nodes
    if filters.get("partition"):
        filtered = [n for n in filtered if n["partition"] == filters["partition"]]
    if filters.get("state"):
        filtered = [n for n in filtered if n["state"] == filters["state"]]
    
    lines = ["PARTITION   AVAIL  TIMELIMIT  NODES  STATE  NODELIST"]
    
    # Group by partition
    partitions = {}
    for n in filtered:
        p = n["partition"]
        if p not in partitions:
            partitions[p] = []
        partitions[p].append(n)
    
    for part, part_nodes in partitions.items():
        for n in part_nodes:
            avail = "up" if n["state"] not in ["down", "drain"] else "down"
            lines.append(f"{part:11} {avail:6} infinite   {1:5}  {n['state']:5}  {n['name']}")
    
    return "\n".join(lines)


def format_scontrol_output(details: Dict[str, Any]) -> str:
    """Format job details as scontrol show job output."""
    if "error" in details:
        return details["error"]
    
    lines = []
    for key, value in details.items():
        lines.append(f"   {key}={value}")
    
    return "\n".join(lines)


# ============ Analysis Script Outputs ============

MOCK_ANALYSIS_OUTPUTS = {
    "healthy": """
=== Cluster Status Analysis ===
Date: {date}

SUMMARY:
- Total Jobs: 4
- Running: 3
- Pending: 1
- Failed: 0

RUNNING JOBS:
  Job 1001 (train_model_v1) - alice - 02:30:15 elapsed - GPU partition
  Job 1002 (data_preprocess) - bob - 00:45:22 elapsed - CPU partition
  Job 1003 (inference_batch) - alice - 01:12:08 elapsed - GPU partition

PENDING JOBS:
  Job 1004 (analysis_job) - charlie - Waiting for resources

CLUSTER UTILIZATION:
  GPU nodes: 50% utilized (1/2 nodes busy)
  CPU nodes: 25% utilized (1/4 nodes busy)
  
No issues detected. Cluster is healthy.
""",
    "failed": """
=== Cluster Status Analysis ===
Date: {date}

⚠️  ALERT: Multiple job failures detected!

SUMMARY:
- Total Jobs: 5
- Running: 1
- Failed: 3
- Timeout: 1

FAILED JOBS (Requires Attention):
  Job 2001 (train_large_model) - alice
    Exit Code: 1:0
    Reason: OOM killer - Job exceeded memory limit
    Recommendation: Increase memory allocation or reduce batch size
    
  Job 2002 (data_pipeline) - bob
    Exit Code: 127:0
    Reason: Command not found
    Recommendation: Check script path and dependencies
    
  Job 2005 (failed_again) - bob
    Exit Code: 1:0
    Reason: Segmentation fault
    Recommendation: Debug application code

TIMEOUT JOBS:
  Job 2003 (backup_job) - charlie
    Ran for: 24:00:00 (hit time limit)
    Recommendation: Increase time limit or optimize job

NODE STATUS:
  ❌ gpu-node-01: DOWN - Hardware failure
  ⚠️  cpu-node-01: DRAIN - Maintenance scheduled
""",
    "pending": """
=== Cluster Status Analysis ===
Date: {date}

⚠️  ALERT: High queue backlog detected!

SUMMARY:
- Total Jobs: 5
- Running: 1
- Pending: 4

PENDING JOBS:
  Job 3001 (big_gpu_job) - alice
    Nodes: 8, GPUs: 32
    Reason: Insufficient resources
    Wait time: ~2-4 hours estimated
    
  Job 3002 (waiting_job) - bob
    Reason: Lower priority
    
  Job 3003 (queue_test) - charlie
    Reason: QOS limit - Max jobs per user reached
    
  Job 3004 (dependency_job) - alice
    Reason: Waiting for dependent job

CLUSTER CAPACITY:
  All GPU nodes: FULLY ALLOCATED
  All CPU nodes: FULLY ALLOCATED
  
Recommendation: Consider off-peak submission or smaller job sizes.
""",
    "mixed": """
=== Cluster Status Analysis ===
Date: {date}

SUMMARY:
- Total Jobs: 6
- Running: 2
- Pending: 2
- Completed: 1
- Failed: 1

ISSUES FOUND:

1. FAILED JOB:
   Job 4002 (etl_pipeline) - bob
   Exit Code: 1:0
   Reason: Script error
   
2. NODE DOWN:
   gpu-node-02 is DOWN due to GPU error
   Impact: Reduced GPU capacity

3. PENDING QUEUE:
   Job 4003 waiting for GPU resources
   Job 4006 lower priority

RUNNING JOBS (OK):
  Job 4001 (ml_training) - 05:30:00 elapsed
  Job 4005 (model_eval) - 02:15:00 elapsed

RECOMMENDATIONS:
- Investigate job 4002 failure
- Contact admin about gpu-node-02
- Consider resubmitting job 4003 with fewer GPUs
""",
    "debug_needed": """
=== CRITICAL: Multiple Failures Detected ===
Date: {date}

⚠️  ATTENTION: MULTIPLE OBSCURE ERRORS REQUIRE INVESTIGATION

SUMMARY:
- Total Jobs: 8
- Running: 1
- Pending: 1  
- Failed: 6 (CRITICAL!)

============================================
FAILED JOBS WITH UNUSUAL EXIT CODES:
============================================

1. Job 5001 (cuda_training) - alice
   Exit Code: 134:0 (SIGABRT - Aborted)
   Partition: gpu, Nodes: 2
   ERROR OUTPUT:
   -------
   CUDA error: an illegal memory access was encountered
   CUDA kernel errors might be asynchronously reported
   Aborted (core dumped)
   -------
   ⚠️  This is a CUDA memory error - possibly caused by:
      - Out-of-bounds array access in kernel
      - Race condition in GPU memory
      - Driver/CUDA version mismatch
   💡 RECOMMEND: Search web for "CUDA illegal memory access" solutions

2. Job 5002 (mpi_distributed) - bob
   Exit Code: 139:0 (SIGSEGV - Segmentation Fault)
   Partition: cpu, Nodes: 4
   ERROR OUTPUT:
   -------
   srun: error: node-03: task 12: Segmentation fault (core dumped)
   srun: Terminating job step 5002.0
   PMIx: finalize
   -------
   ⚠️  MPI job crashed with segfault - possibly:
      - Memory corruption in MPI ranks
      - Incompatible MPI library versions
      - Stack overflow in parallel code
   💡 RECOMMEND: Search for "MPI segmentation fault distributed job"

3. Job 5003 (pytorch_ddp) - charlie
   Exit Code: 1:0
   Partition: gpu, Nodes: 2
   ERROR OUTPUT:
   -------
   RuntimeError: NCCL error in: ../torch/lib/c10d/ProcessGroupNCCL.cpp:825
   ncclSystemError: System call (e.g. socket, malloc) or external library call failed
   -------
   ⚠️  PyTorch Distributed Data Parallel NCCL failure:
      - Network communication issue between GPU nodes
      - Possible InfiniBand/network misconfiguration
   💡 RECOMMEND: Search for "NCCL ncclSystemError PyTorch DDP"

4. Job 5005 (tensorflow_job) - bob
   Exit Code: 137:0 (SIGKILL - Killed by OOM)
   Partition: gpu, Nodes: 1
   ERROR OUTPUT:
   -------
   slurmstepd: error: Detected 1 oom-kill event(s) in StepId=5005.batch
   Some of your processes may have been killed by the cgroup out-of-memory handler
   -------
   ⚠️  Job killed by Slurm cgroup OOM handler
      - Requested 32G but exceeded memory limit
   💡 RECOMMEND: Request more memory or reduce batch size

5. Job 5006 (infiniband_test) - charlie
   Exit Code: 1:0
   Partition: cpu, Nodes: 2
   ERROR OUTPUT:
   -------
   libibverbs: Warning: couldn't open config directory '/etc/libibverbs.d'
   [node-02:12345] [[INVALID],INVALID] routed_radix_open - Failed to connect to rdmacm server
   -------
   ⚠️  InfiniBand/RDMA connection failure:
      - IB fabric issue between nodes
      - Missing OFED drivers or config
   💡 RECOMMEND: Search for "libibverbs rdmacm connection failed HPC"

6. Job 5007 (lustre_io) - alice  
   Exit Code: 5:0 (I/O Error)
   Partition: cpu, Nodes: 1
   ERROR OUTPUT:
   -------
   lfs: error: setstripe: unable to create /lustre/scratch/alice/output: Invalid argument
   Error: Lustre striping failed
   -------
   ⚠️  Lustre parallel filesystem error:
      - Invalid stripe parameters
      - Filesystem quota/permission issue
   💡 RECOMMEND: Search for "Lustre lfs setstripe invalid argument"

============================================
PENDING JOBS WITH UNUSUAL REASONS:
============================================

Job 5004 (slurm_array) - alice
   Reason: AssocGrpCPUMinutesLimit
   ⚠️  User has exceeded their CPU-minutes allocation
   💡 RECOMMEND: Search for "Slurm AssocGrpCPUMinutesLimit" to understand limits

============================================
NODE ISSUES:
============================================

- gpu-node-02: DRAIN - "CUDA ECC error detected"
  ⚠️  GPU memory error - node needs maintenance
  
- gpu-node-03: DOWN* - "Not responding - InfiniBand link down"  
  ⚠️  Network fabric issue - IB cable or switch problem

- cpu-node-02: DRAIN - "Lustre client hung"
  ⚠️  Filesystem client unresponsive

============================================
RECOMMENDED ACTIONS:
============================================

1. Use web_search tool to find solutions for these specific errors
2. For CUDA errors: search "CUDA error illegal memory access solution"
3. For NCCL errors: search "PyTorch NCCL ncclSystemError fix"  
4. For IB issues: search "InfiniBand rdmacm connection troubleshooting"
5. Contact HPC admins about drained/down nodes

Some of these errors are complex and may require web search for proper diagnosis!
"""
}


def get_analysis_output(scenario: str) -> str:
    """Get mock analysis output for scenario."""
    output = MOCK_ANALYSIS_OUTPUTS.get(scenario, MOCK_ANALYSIS_OUTPUTS["healthy"])
    return output.format(date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
