"""
Mock MCP Server for local testing
Simulates Slurm responses without requiring actual Slurm cluster

Usage:
    python mock_mcp_server.py                    # Normal mode
    python mock_mcp_server.py --hard             # Hard test mode with complex data
    python mock_mcp_server.py --scenario empty   # Empty queue scenario
    python mock_mcp_server.py --scenario down    # All nodes down scenario
    python mock_mcp_server.py --scenario busy    # Cluster fully busy scenario

Scenarios for testing edge cases:
    - normal: Default test data
    - hard: Complex data with 50+ jobs
    - empty: Empty queue (no jobs)
    - down: All nodes down/drain
    - busy: Cluster fully allocated
    - failed: Many failed jobs in history

Loads config from .env:
    ENV_IP - Host to bind (default: localhost)
    ENV_PORT - Port to bind (default: 8765)
"""
import asyncio
import json
import logging
import os
import sys
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
import websockets
import argparse

# Load environment
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from .env
HOST = os.getenv("ENV_IP", "localhost")
PORT = int(os.getenv("ENV_PORT", "8765"))

# Parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Mock Slurm MCP Server")
    parser.add_argument("--hard", action="store_true", help="Enable hard mode with complex data")
    parser.add_argument("--scenario", type=str, default="normal",
                       choices=["normal", "hard", "empty", "down", "busy", "failed"],
                       help="Test scenario to use")
    return parser.parse_args()

ARGS = parse_args()
HARD_MODE = ARGS.hard or ARGS.scenario == "hard"
SCENARIO = ARGS.scenario


def generate_hard_test_data():
    """Generate complex test data for hard test cases"""
    
    # Generate 50+ jobs with various states and issues
    jobs = {}
    users = ["alice", "bob", "charlie", "testuser", "admin", "researcher1", "mlops"]
    partitions = ["gpu", "cpu", "debug", "highmem", "preempt"]
    states = ["RUNNING", "PENDING", "PENDING", "PENDING", "COMPLETING", "FAILED", "TIMEOUT", "OUT_OF_MEMORY"]
    pending_reasons = [
        "Resources", "Priority", "QOSMaxJobsPerUserLimit", "ReqNodeNotAvail", 
        "Dependency", "AssocGrpCPUMinutesLimit", "AssocMaxJobsLimit"
    ]
    
    base_time = datetime.now()
    
    for i in range(55):
        job_id = str(10000 + i)
        user = random.choice(users)
        partition = random.choice(partitions)
        state = random.choice(states)
        
        # Calculate runtime or wait time
        if state == "RUNNING":
            start_delta = timedelta(hours=random.randint(0, 48))
            runtime = str(start_delta).split('.')[0]
            pending_reason = None
        elif state in ["PENDING"]:
            runtime = "0:00:00"
            pending_reason = random.choice(pending_reasons)
            start_delta = timedelta(hours=random.randint(0, 72))  # waiting time
        else:
            runtime = f"{random.randint(0, 24)}:{random.randint(0, 59)}:{random.randint(0, 59)}"
            pending_reason = None
        
        # Some jobs are array jobs
        is_array = random.random() < 0.2
        array_spec = f"{i}_{random.randint(0, 100)}" if is_array else None
        
        jobs[job_id] = {
            "job_id": job_id,
            "array_job_id": job_id.split("_")[0] if is_array else None,
            "array_task_id": array_spec,
            "name": random.choice([
                "training_run", "data_preprocessing", "inference_batch",
                "hyperparameter_sweep", "model_evaluation", "feature_extraction",
                "distributed_training", "checkpoint_eval", "dataset_gen"
            ]) + f"_{i}",
            "user": user,
            "state": state,
            "partition": partition,
            "nodes": random.randint(1, 8) if state == "RUNNING" else random.randint(1, 4),
            "cpus": random.choice([4, 8, 16, 32, 64]),
            "gpus": random.randint(0, 8) if partition == "gpu" else 0,
            "memory": f"{random.choice([8, 16, 32, 64, 128, 256])}G",
            "time_limit": random.choice(["1:00:00", "4:00:00", "12:00:00", "24:00:00", "72:00:00", "168:00:00"]),
            "runtime": runtime,
            "submit_time": (base_time - timedelta(hours=random.randint(1, 96))).isoformat(),
            "start_time": (base_time - start_delta).isoformat() if state == "RUNNING" else None,
            "priority": random.randint(1000, 50000),
            "pending_reason": pending_reason,
            "exit_code": "0:0" if state not in ["FAILED", "TIMEOUT", "OUT_OF_MEMORY"] else 
                        ("137:0" if state == "OUT_OF_MEMORY" else f"{random.randint(1, 255)}:0"),
            "dependency": f"afterok:{10000 + random.randint(0, i)}" if random.random() < 0.1 and i > 0 else None,
            "qos": random.choice(["normal", "high", "low", "interactive"]),
        }
    
    # Nodes with various states including problematic ones
    nodes = {
        # GPU nodes
        "gpu01": {"name": "gpu01", "state": "ALLOCATED", "cpus": 64, "alloc_cpus": 64, "memory": "512G", "alloc_mem": "480G", 
                  "gpus": 8, "alloc_gpus": 8, "gpu_type": "A100", "partition": "gpu", "features": "a100,nvlink"},
        "gpu02": {"name": "gpu02", "state": "ALLOCATED", "cpus": 64, "alloc_cpus": 48, "memory": "512G", "alloc_mem": "384G",
                  "gpus": 8, "alloc_gpus": 6, "gpu_type": "A100", "partition": "gpu", "features": "a100,nvlink"},
        "gpu03": {"name": "gpu03", "state": "MIXED", "cpus": 64, "alloc_cpus": 32, "memory": "512G", "alloc_mem": "256G",
                  "gpus": 8, "alloc_gpus": 4, "gpu_type": "A100", "partition": "gpu", "features": "a100,nvlink"},
        "gpu04": {"name": "gpu04", "state": "IDLE", "cpus": 64, "alloc_cpus": 0, "memory": "512G", "alloc_mem": "0",
                  "gpus": 8, "alloc_gpus": 0, "gpu_type": "A100", "partition": "gpu", "features": "a100,nvlink"},
        "gpu05": {"name": "gpu05", "state": "DOWN", "cpus": 64, "alloc_cpus": 0, "memory": "512G", "alloc_mem": "0",
                  "gpus": 8, "alloc_gpus": 0, "gpu_type": "A100", "partition": "gpu", "features": "a100,nvlink", 
                  "reason": "Hardware failure - GPU 3 ECC errors"},
        "gpu06": {"name": "gpu06", "state": "DRAIN", "cpus": 64, "alloc_cpus": 32, "memory": "512G", "alloc_mem": "256G",
                  "gpus": 8, "alloc_gpus": 4, "gpu_type": "A100", "partition": "gpu", "features": "a100,nvlink",
                  "reason": "Scheduled maintenance 2025-12-20"},
        
        # V100 nodes (older)
        "gpu-v01": {"name": "gpu-v01", "state": "ALLOCATED", "cpus": 32, "alloc_cpus": 32, "memory": "256G", "alloc_mem": "256G",
                    "gpus": 4, "alloc_gpus": 4, "gpu_type": "V100", "partition": "gpu", "features": "v100"},
        "gpu-v02": {"name": "gpu-v02", "state": "IDLE", "cpus": 32, "alloc_cpus": 0, "memory": "256G", "alloc_mem": "0",
                    "gpus": 4, "alloc_gpus": 0, "gpu_type": "V100", "partition": "gpu", "features": "v100"},
        
        # CPU nodes
        "cpu01": {"name": "cpu01", "state": "IDLE", "cpus": 128, "alloc_cpus": 0, "memory": "512G", "alloc_mem": "0",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu", "features": "avx512"},
        "cpu02": {"name": "cpu02", "state": "MIXED", "cpus": 128, "alloc_cpus": 64, "memory": "512G", "alloc_mem": "256G",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu", "features": "avx512"},
        "cpu03": {"name": "cpu03", "state": "ALLOCATED", "cpus": 128, "alloc_cpus": 128, "memory": "512G", "alloc_mem": "512G",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu", "features": "avx512"},
        "cpu04": {"name": "cpu04", "state": "DOWN", "cpus": 128, "alloc_cpus": 0, "memory": "512G", "alloc_mem": "0",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu", "features": "avx512",
                  "reason": "Network issues"},
        
        # High memory nodes
        "himem01": {"name": "himem01", "state": "ALLOCATED", "cpus": 64, "alloc_cpus": 32, "memory": "2T", "alloc_mem": "1.5T",
                    "gpus": 0, "alloc_gpus": 0, "partition": "highmem", "features": "highmem,avx512"},
        "himem02": {"name": "himem02", "state": "IDLE", "cpus": 64, "alloc_cpus": 0, "memory": "2T", "alloc_mem": "0",
                    "gpus": 0, "alloc_gpus": 0, "partition": "highmem", "features": "highmem,avx512"},
    }
    
    # Partitions with limits and issues
    partitions = {
        "gpu": {
            "name": "gpu", "state": "UP", "nodes": 8, "total_cpus": 448, "total_gpus": 52,
            "avail_cpus": 112, "avail_gpus": 10, "max_time": "7-00:00:00", "default": False,
            "max_nodes_per_job": 4, "max_cpus_per_user": 128, "priority_tier": 1,
            "qos": "normal,high", "allow_accounts": "all",
        },
        "cpu": {
            "name": "cpu", "state": "UP", "nodes": 4, "total_cpus": 512, "total_gpus": 0,
            "avail_cpus": 192, "avail_gpus": 0, "max_time": "14-00:00:00", "default": True,
            "max_nodes_per_job": 4, "priority_tier": 2,
            "qos": "normal,low", "allow_accounts": "all",
        },
        "highmem": {
            "name": "highmem", "state": "UP", "nodes": 2, "total_cpus": 128, "total_gpus": 0,
            "avail_cpus": 32, "avail_gpus": 0, "max_time": "3-00:00:00", "default": False,
            "max_nodes_per_job": 1, "priority_tier": 1,
            "qos": "normal", "allow_accounts": "research,genomics",
        },
        "debug": {
            "name": "debug", "state": "UP", "nodes": 1, "total_cpus": 8, "total_gpus": 1,
            "avail_cpus": 8, "avail_gpus": 1, "max_time": "01:00:00", "default": False,
            "max_nodes_per_job": 1, "priority_tier": 0,  # Highest priority
            "qos": "interactive", "allow_accounts": "all",
        },
        "preempt": {
            "name": "preempt", "state": "UP", "nodes": 8, "total_cpus": 448, "total_gpus": 52,
            "avail_cpus": 200, "avail_gpus": 20, "max_time": "4:00:00", "default": False,
            "max_nodes_per_job": 8, "priority_tier": 3,
            "qos": "preemptable", "allow_accounts": "all", "preempt_mode": "requeue",
        },
        "maintenance": {
            "name": "maintenance", "state": "DRAIN", "nodes": 2, "total_cpus": 128, "total_gpus": 16,
            "avail_cpus": 0, "avail_gpus": 0, "max_time": "0", "default": False,
            "reason": "Scheduled upgrade 2025-12-20 02:00 UTC",
        },
    }
    
    # Job history with failures
    job_history = []
    for i in range(30):
        end_time = base_time - timedelta(hours=random.randint(1, 168))
        start_time = end_time - timedelta(hours=random.randint(1, 24))
        
        state = random.choice(["COMPLETED", "COMPLETED", "COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_ME+", "CANCELLED"])
        
        if state == "COMPLETED":
            exit_code = "0:0"
        elif state == "OUT_OF_ME+":
            exit_code = "0:137"  # OOM kill
        elif state == "TIMEOUT":
            exit_code = "0:0"
        elif state == "CANCELLED":
            exit_code = "0:0"
        else:
            exit_code = f"0:{random.randint(1, 255)}"
        
        job_history.append({
            "job_id": str(9000 + i),
            "name": f"historical_job_{i}",
            "user": random.choice(users),
            "state": state,
            "partition": random.choice(list(partitions.keys())),
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "elapsed": str(end_time - start_time).split('.')[0],
            "exit_code": exit_code,
            "max_rss": f"{random.randint(1, 128)}G",
            "max_vmem": f"{random.randint(1, 256)}G",
            "cpu_time": f"{random.randint(1, 1000)}:{random.randint(0, 59)}:{random.randint(0, 59)}",
            "req_cpus": random.choice([4, 8, 16, 32]),
            "req_mem": f"{random.choice([8, 16, 32, 64, 128])}G",
            "req_gpus": random.randint(0, 4) if "gpu" in random.choice(list(partitions.keys())) else 0,
        })
    
    return jobs, nodes, partitions, job_history


def generate_empty_queue_data():
    """Scenario: Empty queue - no jobs running or pending"""
    jobs = {}  # No jobs at all
    
    nodes = {
        "gpu01": {"name": "gpu01", "state": "IDLE", "cpus": 64, "alloc_cpus": 0, "memory": "512G", "alloc_mem": "0",
                  "gpus": 8, "alloc_gpus": 0, "gpu_type": "A100", "partition": "gpu"},
        "gpu02": {"name": "gpu02", "state": "IDLE", "cpus": 64, "alloc_cpus": 0, "memory": "512G", "alloc_mem": "0",
                  "gpus": 8, "alloc_gpus": 0, "gpu_type": "A100", "partition": "gpu"},
        "cpu01": {"name": "cpu01", "state": "IDLE", "cpus": 128, "alloc_cpus": 0, "memory": "512G", "alloc_mem": "0",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu"},
    }
    
    partitions = {
        "gpu": {"name": "gpu", "state": "UP", "nodes": 2, "total_cpus": 128, "total_gpus": 16,
                "avail_cpus": 128, "avail_gpus": 16, "max_time": "7-00:00:00"},
        "cpu": {"name": "cpu", "state": "UP", "nodes": 1, "total_cpus": 128, "total_gpus": 0,
                "avail_cpus": 128, "avail_gpus": 0, "max_time": "14-00:00:00"},
    }
    
    job_history = [
        {"job_id": "9000", "name": "completed_job", "state": "COMPLETED", "user": "testuser",
         "elapsed": "01:30:00", "exit_code": "0:0", "partition": "gpu"},
    ]
    
    return jobs, nodes, partitions, job_history


def generate_all_nodes_down_data():
    """Scenario: All nodes down - cluster unavailable"""
    jobs = {
        "12345": {"job_id": "12345", "name": "stuck_job", "user": "testuser", "state": "PENDING",
                  "partition": "gpu", "nodes": 1, "cpus": 8, "gpus": 2, 
                  "pending_reason": "ReqNodeNotAvail,_Reserved_for_maintenance"},
    }
    
    nodes = {
        "gpu01": {"name": "gpu01", "state": "DOWN", "cpus": 64, "alloc_cpus": 0, "memory": "512G",
                  "gpus": 8, "alloc_gpus": 0, "partition": "gpu",
                  "reason": "Hardware failure - PSU replacement needed"},
        "gpu02": {"name": "gpu02", "state": "DRAIN", "cpus": 64, "alloc_cpus": 0, "memory": "512G",
                  "gpus": 8, "alloc_gpus": 0, "partition": "gpu",
                  "reason": "Scheduled maintenance - firmware upgrade"},
        "gpu03": {"name": "gpu03", "state": "DOWN", "cpus": 64, "alloc_cpus": 0, "memory": "512G",
                  "gpus": 8, "alloc_gpus": 0, "partition": "gpu",
                  "reason": "Network connectivity issues"},
        "cpu01": {"name": "cpu01", "state": "DOWN", "cpus": 128, "alloc_cpus": 0, "memory": "512G",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu",
                  "reason": "Memory errors detected - RMA in progress"},
        "cpu02": {"name": "cpu02", "state": "DRAIN", "cpus": 128, "alloc_cpus": 0, "memory": "512G",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu",
                  "reason": "OS upgrade scheduled"},
    }
    
    partitions = {
        "gpu": {"name": "gpu", "state": "DRAIN", "nodes": 3, "total_cpus": 192, "total_gpus": 24,
                "avail_cpus": 0, "avail_gpus": 0, "max_time": "7-00:00:00",
                "reason": "Cluster maintenance in progress - expected completion 2025-12-20 06:00 UTC"},
        "cpu": {"name": "cpu", "state": "DOWN", "nodes": 2, "total_cpus": 256, "total_gpus": 0,
                "avail_cpus": 0, "avail_gpus": 0, "max_time": "14-00:00:00",
                "reason": "All nodes unavailable - contact admin@hpc.example.com"},
    }
    
    job_history = []
    
    return jobs, nodes, partitions, job_history


def generate_fully_busy_data():
    """Scenario: Cluster fully allocated - no resources available"""
    base_time = datetime.now()
    
    # Many running jobs
    jobs = {}
    for i in range(20):
        jobs[str(12345 + i)] = {
            "job_id": str(12345 + i),
            "name": f"running_job_{i}",
            "user": random.choice(["alice", "bob", "charlie", "testuser"]),
            "state": "RUNNING",
            "partition": "gpu" if i < 12 else "cpu",
            "nodes": random.randint(1, 2),
            "cpus": random.choice([8, 16, 32]),
            "gpus": random.randint(1, 4) if i < 12 else 0,
            "runtime": f"{random.randint(0, 72)}:{random.randint(0, 59)}:00",
            "time_limit": "72:00:00",
        }
    
    # Many pending jobs
    for i in range(30):
        jobs[str(12400 + i)] = {
            "job_id": str(12400 + i),
            "name": f"waiting_job_{i}",
            "user": random.choice(["alice", "bob", "charlie", "testuser"]),
            "state": "PENDING",
            "partition": "gpu" if i % 2 == 0 else "cpu",
            "nodes": 1,
            "cpus": random.choice([4, 8, 16]),
            "gpus": random.randint(1, 2) if i % 2 == 0 else 0,
            "pending_reason": random.choice(["Resources", "Priority", "QOSMaxJobsPerUserLimit"]),
            "submit_time": (base_time - timedelta(hours=random.randint(1, 48))).isoformat(),
            "priority": random.randint(1000, 5000),
        }
    
    nodes = {
        "gpu01": {"name": "gpu01", "state": "ALLOCATED", "cpus": 64, "alloc_cpus": 64, "memory": "512G", "alloc_mem": "512G",
                  "gpus": 8, "alloc_gpus": 8, "gpu_type": "A100", "partition": "gpu"},
        "gpu02": {"name": "gpu02", "state": "ALLOCATED", "cpus": 64, "alloc_cpus": 64, "memory": "512G", "alloc_mem": "512G",
                  "gpus": 8, "alloc_gpus": 8, "gpu_type": "A100", "partition": "gpu"},
        "gpu03": {"name": "gpu03", "state": "ALLOCATED", "cpus": 64, "alloc_cpus": 64, "memory": "512G", "alloc_mem": "512G",
                  "gpus": 8, "alloc_gpus": 8, "gpu_type": "A100", "partition": "gpu"},
        "cpu01": {"name": "cpu01", "state": "ALLOCATED", "cpus": 128, "alloc_cpus": 128, "memory": "512G", "alloc_mem": "512G",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu"},
        "cpu02": {"name": "cpu02", "state": "ALLOCATED", "cpus": 128, "alloc_cpus": 128, "memory": "512G", "alloc_mem": "512G",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu"},
    }
    
    partitions = {
        "gpu": {"name": "gpu", "state": "UP", "nodes": 3, "total_cpus": 192, "total_gpus": 24,
                "avail_cpus": 0, "avail_gpus": 0, "max_time": "72:00:00",
                "note": "All GPU resources currently in use. Estimated wait time: 4-8 hours."},
        "cpu": {"name": "cpu", "state": "UP", "nodes": 2, "total_cpus": 256, "total_gpus": 0,
                "avail_cpus": 0, "avail_gpus": 0, "max_time": "168:00:00",
                "note": "High demand - consider using preempt partition for shorter jobs."},
        "preempt": {"name": "preempt", "state": "UP", "nodes": 3, "total_cpus": 192, "total_gpus": 24,
                    "avail_cpus": 48, "avail_gpus": 4, "max_time": "4:00:00",
                    "note": "Jobs may be preempted. Best for short, restartable tasks."},
    }
    
    job_history = []
    
    return jobs, nodes, partitions, job_history


def generate_failed_jobs_data():
    """Scenario: Many failed jobs in history - for debugging scenarios"""
    base_time = datetime.now()
    
    jobs = {
        "12345": {"job_id": "12345", "name": "current_job", "user": "testuser", "state": "RUNNING",
                  "partition": "gpu", "nodes": 1, "cpus": 8, "gpus": 2, "runtime": "0:15:00"},
    }
    
    nodes = {
        "gpu01": {"name": "gpu01", "state": "MIXED", "cpus": 64, "alloc_cpus": 8, "memory": "512G",
                  "gpus": 8, "alloc_gpus": 2, "gpu_type": "A100", "partition": "gpu"},
        "cpu01": {"name": "cpu01", "state": "IDLE", "cpus": 128, "alloc_cpus": 0, "memory": "512G",
                  "gpus": 0, "alloc_gpus": 0, "partition": "cpu"},
    }
    
    partitions = {
        "gpu": {"name": "gpu", "state": "UP", "nodes": 1, "total_cpus": 64, "total_gpus": 8,
                "avail_cpus": 56, "avail_gpus": 6, "max_time": "72:00:00"},
        "cpu": {"name": "cpu", "state": "UP", "nodes": 1, "total_cpus": 128, "total_gpus": 0,
                "avail_cpus": 128, "avail_gpus": 0, "max_time": "168:00:00"},
    }
    
    # Generate job history with many failures
    job_history = []
    failure_reasons = [
        ("OUT_OF_ME+", "0:137", "Job exceeded memory limit - requested 32GB but used 48GB"),
        ("TIMEOUT", "0:0", "Job exceeded time limit of 24:00:00"),
        ("FAILED", "0:1", "Exit code 1 - Check stderr for details"),
        ("FAILED", "0:2", "Exit code 2 - Command not found in script"),
        ("FAILED", "0:139", "Segmentation fault - SIGSEGV"),
        ("FAILED", "0:134", "SIGABRT - Aborted"),
        ("CANCELLED", "0:0", "Cancelled by user"),
        ("NODE_FAIL", "0:0", "Node failure during execution"),
    ]
    
    # Recent failed jobs (for "why did my job fail" test)
    for i in range(5):
        failure = failure_reasons[i % len(failure_reasons)]
        end_time = base_time - timedelta(hours=i + 1)
        start_time = end_time - timedelta(hours=random.randint(1, 4))
        
        job_history.append({
            "job_id": str(9100 + i),
            "name": f"failed_training_{i}",
            "user": "testuser",
            "state": failure[0],
            "exit_code": failure[1],
            "failure_reason": failure[2],
            "partition": "gpu",
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "elapsed": str(end_time - start_time).split('.')[0],
            "max_rss": f"{random.randint(16, 64)}G",
            "req_mem": "32G",
            "req_cpus": 8,
            "req_gpus": 2,
        })
    
    # Some completed jobs
    for i in range(10):
        end_time = base_time - timedelta(hours=random.randint(6, 72))
        start_time = end_time - timedelta(hours=random.randint(1, 24))
        
        job_history.append({
            "job_id": str(9000 + i),
            "name": f"completed_job_{i}",
            "user": "testuser",
            "state": "COMPLETED",
            "exit_code": "0:0",
            "partition": random.choice(["gpu", "cpu"]),
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "elapsed": str(end_time - start_time).split('.')[0],
            "max_rss": f"{random.randint(4, 32)}G",
            "req_mem": "32G",
            "req_cpus": random.choice([4, 8, 16]),
            "req_gpus": random.randint(0, 2),
        })
    
    return jobs, nodes, partitions, job_history


def generate_simple_test_data():
    """Generate simple test data for basic testing"""
    jobs = {
        "12345": {"job_id": "12345", "name": "training_job", "user": "testuser", "state": "RUNNING", 
                  "partition": "gpu", "nodes": 1, "cpus": 8, "gpus": 2, "runtime": "2:30:00"},
        "12344": {"job_id": "12344", "name": "data_prep", "user": "testuser", "state": "PENDING", 
                  "partition": "cpu", "nodes": 1, "cpus": 4, "gpus": 0, "pending_reason": "Resources"},
        "12343": {"job_id": "12343", "name": "inference", "user": "admin", "state": "RUNNING", 
                  "partition": "gpu", "nodes": 2, "cpus": 16, "gpus": 4, "runtime": "0:45:00"},
    }
    
    nodes = {
        "gpu01": {"name": "gpu01", "state": "IDLE", "cpus": 32, "memory": "128G", "gpus": 4, "partition": "gpu", 
                  "gpu_type": "A100", "alloc_cpus": 0, "alloc_gpus": 0},
        "gpu02": {"name": "gpu02", "state": "ALLOCATED", "cpus": 32, "memory": "128G", "gpus": 4, "partition": "gpu",
                  "gpu_type": "A100", "alloc_cpus": 32, "alloc_gpus": 4},
        "cpu01": {"name": "cpu01", "state": "IDLE", "cpus": 64, "memory": "256G", "gpus": 0, "partition": "cpu",
                  "alloc_cpus": 0, "alloc_gpus": 0},
        "cpu02": {"name": "cpu02", "state": "MIXED", "cpus": 64, "memory": "256G", "gpus": 0, "partition": "cpu",
                  "alloc_cpus": 32, "alloc_gpus": 0},
    }
    
    partitions = {
        "gpu": {"name": "gpu", "state": "UP", "nodes": 2, "total_cpus": 64, "total_gpus": 8,
                "avail_cpus": 32, "avail_gpus": 4, "max_time": "7-00:00:00"},
        "cpu": {"name": "cpu", "state": "UP", "nodes": 2, "total_cpus": 128, "total_gpus": 0,
                "avail_cpus": 96, "avail_gpus": 0, "max_time": "14-00:00:00"},
        "debug": {"name": "debug", "state": "UP", "nodes": 1, "total_cpus": 8, "total_gpus": 1,
                  "avail_cpus": 8, "avail_gpus": 1, "max_time": "01:00:00"},
    }
    
    job_history = [
        {"job_id": "12340", "name": "old_job", "state": "COMPLETED", "user": "testuser",
         "elapsed": "01:30:00", "exit_code": "0:0", "partition": "gpu"},
        {"job_id": "12341", "name": "failed_job", "state": "FAILED", "user": "testuser",
         "elapsed": "00:05:00", "exit_code": "1:0", "partition": "cpu", "failure_reason": "Script error"},
        {"job_id": "12342", "name": "timeout_job", "state": "TIMEOUT", "user": "testuser",
         "elapsed": "24:00:00", "exit_code": "0:0", "partition": "gpu"},
        {"job_id": "12339", "name": "oom_job", "state": "OUT_OF_ME+", "user": "testuser",
         "elapsed": "00:15:00", "exit_code": "0:137", "partition": "gpu", "failure_reason": "Out of memory"},
    ]
    
    return jobs, nodes, partitions, job_history


def get_scenario_data(scenario: str):
    """Get test data for a specific scenario"""
    scenarios = {
        "normal": generate_simple_test_data,
        "hard": generate_hard_test_data,
        "empty": generate_empty_queue_data,
        "down": generate_all_nodes_down_data,
        "busy": generate_fully_busy_data,
        "failed": generate_failed_jobs_data,
    }
    
    generator = scenarios.get(scenario, generate_simple_test_data)
    return generator()


class MockSlurmMCPServer:
    """Mock MCP Server that simulates Slurm responses"""
    
    def __init__(self, scenario: str = "normal", hard_mode: bool = False):
        self.scenario = scenario
        self.hard_mode = hard_mode or scenario == "hard"
        self.job_counter = 12500
        
        # Use scenario-based data loading
        if self.hard_mode:
            scenario = "hard"
        
        logger.info(f"📊 Loading scenario: {scenario}")
        self.jobs, self.nodes, self.partitions, self.job_history = get_scenario_data(scenario)
        
        logger.info(f"   Jobs: {len(self.jobs)}, Nodes: {len(self.nodes)}, History: {len(self.job_history)}")
    
    async def handle_tool(self, tool_name: str, args: dict) -> dict:
        """Route tool calls to handlers"""
        handlers = {
            "squeue": self.handle_squeue,
            "sinfo": self.handle_sinfo,
            "sbatch": self.handle_sbatch,
            "scancel": self.handle_scancel,
            "sacct": self.handle_sacct,
            "srun": self.handle_srun,
            "sprio": self.handle_sprio,
            "sshare": self.handle_sshare,
            "scontrol_show_job": self.handle_scontrol_show_job,
            "scontrol_show_node": self.handle_scontrol_show_node,
            "scontrol_show_partition": self.handle_scontrol_show_partition,
            "scontrol_show_config": self.handle_scontrol_show_config,
            "scontrol_hold": self.handle_scontrol_hold,
            "scontrol_release": self.handle_scontrol_release,
            "scontrol_requeue": self.handle_scontrol_requeue,
            "sstat": self.handle_sstat,
            "sdiag": self.handle_sdiag,
        }
        
        handler = handlers.get(tool_name)
        if handler:
            return await handler(args)
        else:
            return {"output": f"Mock response for {tool_name}", "args": args}
    
    async def handle_squeue(self, args: dict) -> dict:
        """Query job queue"""
        jobs = list(self.jobs.values())
        
        # Filter by user if specified
        user = args.get("user")
        if user and user != "$USER":
            jobs = [j for j in jobs if j["user"] == user]
        
        # Filter by partition
        partition = args.get("partition")
        if partition:
            jobs = [j for j in jobs if j["partition"] == partition]
        
        # Filter by job_id
        job_id = args.get("job_id")
        if job_id:
            jobs = [j for j in jobs if j["job_id"] == job_id]
        
        return {"jobs": jobs, "count": len(jobs)}
    
    async def handle_sinfo(self, args: dict) -> dict:
        """Cluster/partition info"""
        partitions = list(self.partitions.values())
        nodes = list(self.nodes.values())
        
        partition = args.get("partition")
        if partition:
            partitions = [p for p in partitions if p["name"] == partition]
            nodes = [n for n in nodes if n.get("partition") == partition]
        
        # Calculate detailed stats
        total_nodes = len(nodes)
        idle_nodes = len([n for n in nodes if n.get("state") == "IDLE"])
        allocated_nodes = len([n for n in nodes if n.get("state") == "ALLOCATED"])
        mixed_nodes = len([n for n in nodes if n.get("state") == "MIXED"])
        down_nodes = len([n for n in nodes if n.get("state") in ["DOWN", "DRAIN"]])
        
        total_cpus = sum(n.get("cpus", 0) for n in nodes)
        alloc_cpus = sum(n.get("alloc_cpus", 0) for n in nodes)
        
        total_gpus = sum(n.get("gpus", 0) for n in nodes)
        alloc_gpus = sum(n.get("alloc_gpus", 0) for n in nodes)
        
        return {
            "partitions": partitions,
            "nodes": nodes,
            "summary": {
                "total_nodes": total_nodes,
                "idle_nodes": idle_nodes,
                "allocated_nodes": allocated_nodes,
                "mixed_nodes": mixed_nodes,
                "down_nodes": down_nodes,
                "total_cpus": total_cpus,
                "avail_cpus": total_cpus - alloc_cpus,
                "total_gpus": total_gpus,
                "avail_gpus": total_gpus - alloc_gpus,
                "cluster_utilization": f"{(alloc_cpus/total_cpus*100):.1f}%" if total_cpus > 0 else "N/A",
                "gpu_utilization": f"{(alloc_gpus/total_gpus*100):.1f}%" if total_gpus > 0 else "N/A",
            }
        }
    
    async def handle_sbatch(self, args: dict) -> dict:
        """Submit batch job"""
        self.job_counter += 1
        job_id = str(self.job_counter)
        
        new_job = {
            "job_id": job_id,
            "name": args.get("job_name", "batch_job"),
            "user": "testuser",
            "state": "PENDING",
            "partition": args.get("partition", "cpu"),
            "nodes": args.get("nodes", 1),
            "cpus": args.get("cpus_per_task", 1) * args.get("ntasks", 1),
        }
        self.jobs[job_id] = new_job
        
        return {
            "job_id": job_id,
            "message": f"Submitted batch job {job_id}",
            "job": new_job
        }
    
    async def handle_scancel(self, args: dict) -> dict:
        """Cancel job"""
        job_id = args.get("job_id")
        if job_id and job_id in self.jobs:
            self.jobs[job_id]["state"] = "CANCELLED"
            return {"message": f"Job {job_id} cancelled successfully", "success": True}
        return {"message": f"Job {job_id} not found", "success": False}
    
    async def handle_sacct(self, args: dict) -> dict:
        """Job accounting/history"""
        # Use job_history if available (hard mode)
        if self.job_history:
            history = self.job_history.copy()
        else:
            history = [
                {"job_id": "12340", "name": "old_job", "state": "COMPLETED", "elapsed": "01:30:00", "exit_code": "0:0"},
                {"job_id": "12341", "name": "failed_job", "state": "FAILED", "elapsed": "00:05:00", "exit_code": "1:0"},
                {"job_id": "12342", "name": "timeout_job", "state": "TIMEOUT", "elapsed": "24:00:00", "exit_code": "0:1"},
                {"job_id": "12339", "name": "oom_job", "state": "OUT_OF_ME+", "elapsed": "00:15:00", "exit_code": "0:137"},
            ]
        
        user = args.get("user")
        if user and user != "$USER":
            history = [h for h in history if h.get("user") == user]
        
        job_id = args.get("job_id")
        if job_id:
            history = [h for h in history if h.get("job_id") == job_id]
        
        # Calculate summary stats
        total = len(history)
        completed = len([h for h in history if h.get("state") == "COMPLETED"])
        failed = len([h for h in history if h.get("state") in ["FAILED", "OUT_OF_ME+", "TIMEOUT"]])
        
        return {
            "jobs": history,
            "count": total,
            "summary": {
                "total": total,
                "completed": completed,
                "failed": failed,
                "success_rate": f"{(completed/total*100):.1f}%" if total > 0 else "N/A"
            }
        }
        
        return {"jobs": history, "count": len(history)}
    
    async def handle_srun(self, args: dict) -> dict:
        """Run interactive command"""
        command = args.get("command", "hostname")
        return {
            "output": f"[Mock] Running: {command}\ngpu01\n",
            "exit_code": 0,
            "success": True
        }
    
    async def handle_sprio(self, args: dict) -> dict:
        """Job priorities"""
        priorities = [
            {"job_id": "12345", "user": "testuser", "priority": 10000, "age": 500, "fairshare": 5000},
            {"job_id": "12344", "user": "testuser", "priority": 8000, "age": 200, "fairshare": 5000},
        ]
        return {"priorities": priorities}
    
    async def handle_sshare(self, args: dict) -> dict:
        """Fair share info"""
        shares = [
            {"account": "research", "user": "testuser", "raw_shares": 100, "fairshare": 0.5},
            {"account": "research", "user": "admin", "raw_shares": 100, "fairshare": 0.8},
        ]
        return {"shares": shares}
    
    async def handle_scontrol_show_job(self, args: dict) -> dict:
        """Show job details"""
        job_id = args.get("name") or args.get("job_id")
        if job_id and job_id in self.jobs:
            job = self.jobs[job_id]
            return {
                "JobId": job["job_id"],
                "JobName": job["name"],
                "UserId": job["user"],
                "JobState": job["state"],
                "Partition": job["partition"],
                "NumNodes": job["nodes"],
                "NumCPUs": job["cpus"],
                "SubmitTime": "2025-12-19T10:00:00",
                "StartTime": "2025-12-19T10:05:00" if job["state"] == "RUNNING" else "N/A",
            }
        return {"error": f"Job {job_id} not found"}
    
    async def handle_scontrol_show_node(self, args: dict) -> dict:
        """Show node details"""
        node_name = args.get("name") or args.get("entity_name")
        if node_name and node_name in self.nodes:
            node = self.nodes[node_name]
            return {
                "NodeName": node["name"],
                "State": node["state"],
                "CPUTot": node["cpus"],
                "RealMemory": node["memory"],
                "Gres": f"gpu:{node['gpus']}" if node["gpus"] else "",
                "Partitions": node["partition"],
            }
        return {"error": f"Node {node_name} not found"}
    
    async def handle_scontrol_show_partition(self, args: dict) -> dict:
        """Show partition details"""
        part_name = args.get("name") or args.get("entity_name")
        if part_name and part_name in self.partitions:
            part = self.partitions[part_name]
            return {
                "PartitionName": part["name"],
                "State": part["state"],
                "TotalNodes": part["nodes"],
                "TotalCPUs": part["cpus"],
                "MaxTime": part["max_time"],
            }
        # Return all partitions if no name specified
        return {"partitions": list(self.partitions.values())}
    
    async def handle_scontrol_show_config(self, args: dict) -> dict:
        """Show cluster config"""
        return {
            "ClusterName": "mock-cluster",
            "SlurmVersion": "23.02.0",
            "ControlMachine": "controller01",
            "MaxJobCount": 10000,
            "MaxArraySize": 1001,
        }
    
    async def handle_scontrol_hold(self, args: dict) -> dict:
        """Hold job"""
        job_id = args.get("job_id")
        if job_id and job_id in self.jobs:
            self.jobs[job_id]["state"] = "HELD"
            return {"message": f"Job {job_id} held", "success": True}
        return {"error": f"Job {job_id} not found"}
    
    async def handle_scontrol_release(self, args: dict) -> dict:
        """Release held job"""
        job_id = args.get("job_id")
        if job_id and job_id in self.jobs:
            self.jobs[job_id]["state"] = "PENDING"
            return {"message": f"Job {job_id} released", "success": True}
        return {"error": f"Job {job_id} not found"}
    
    async def handle_scontrol_requeue(self, args: dict) -> dict:
        """Requeue job"""
        job_id = args.get("job_id")
        if job_id and job_id in self.jobs:
            self.jobs[job_id]["state"] = "PENDING"
            return {"message": f"Job {job_id} requeued", "success": True}
        return {"error": f"Job {job_id} not found"}
    
    async def handle_sstat(self, args: dict) -> dict:
        """Running job statistics"""
        return {
            "job_id": args.get("job_id", "12345"),
            "cpu_time": "01:30:00",
            "max_rss": "4096M",
            "max_vmem": "8192M",
        }
    
    async def handle_sdiag(self, args: dict) -> dict:
        """Scheduler diagnostics"""
        return {
            "server_thread_count": 10,
            "jobs_submitted": 1000,
            "jobs_started": 950,
            "jobs_completed": 900,
            "jobs_canceled": 30,
            "jobs_failed": 20,
            "scheduler_cycle_last": "0.05s",
        }


async def handle_connection(websocket, server: MockSlurmMCPServer):
    """Handle WebSocket connection"""
    remote = websocket.remote_address
    logger.info(f"✅ Client connected: {remote}")
    
    try:
        async for message in websocket:
            try:
                request = json.loads(message)
                
                # MCP protocol
                method = request.get("method")
                params = request.get("params", {})
                request_id = request.get("id", 1)
                
                if method == "tools/call":
                    tool_name = params.get("name")
                    tool_args = params.get("arguments", {})
                    
                    logger.info(f"📥 {tool_name} <- {tool_args}")
                    
                    result = await server.handle_tool(tool_name, tool_args)
                    
                    logger.info(f"📤 {tool_name} -> OK")
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result
                    }
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"message": f"Method {method} not implemented"}
                    }
                
                await websocket.send(json.dumps(response))
                
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                await websocket.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"}
                }))
                
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"❌ Client disconnected: {remote}")


async def main():
    """Start the mock MCP server"""
    server = MockSlurmMCPServer(scenario=SCENARIO, hard_mode=HARD_MODE)
    
    scenario_icons = {
        "normal": "📋 Normal",
        "hard": "🔥 Hard Mode",
        "empty": "📭 Empty Queue",
        "down": "🔴 All Nodes Down",
        "busy": "🔥 Fully Busy",
        "failed": "❌ Failed Jobs",
    }
    mode_str = scenario_icons.get(SCENARIO, f"📋 {SCENARIO}")
    jobs_count = len(server.jobs)
    nodes_count = len(server.nodes)
    history_count = len(server.job_history)
    
    print(f"""
╔════════════════════════════════════════════════════════════╗
║            Mock Slurm MCP Server                          ║
╠════════════════════════════════════════════════════════════╣
║  Host:     {HOST:<20}                            ║
║  Port:     {PORT:<20}                            ║
║  URL:      ws://{HOST}:{PORT:<15}                       ║
║  Scenario: {mode_str:<20}                            ║
╠════════════════════════════════════════════════════════════╣
║  Test Data:                                               ║
║  • Jobs:       {jobs_count:<10}                                    ║
║  • Nodes:      {nodes_count:<10}                                    ║
║  • Partitions: {len(server.partitions):<10}                                    ║
║  • History:    {history_count:<10}                                    ║
╠════════════════════════════════════════════════════════════╣
║  Available Scenarios:                                     ║
║  • --scenario normal  : Default test data                 ║
║  • --scenario hard    : 50+ jobs, complex partitions      ║
║  • --scenario empty   : Empty queue (no jobs)             ║
║  • --scenario down    : All nodes down/drain              ║
║  • --scenario busy    : Cluster fully allocated           ║
║  • --scenario failed  : Many failed jobs in history       ║
╠════════════════════════════════════════════════════════════╣
║  Supported commands:                                      ║
║  • squeue, sinfo, sbatch, scancel                        ║
║  • sacct, srun, sprio, sshare                            ║
║  • scontrol_show_job/node/partition/config               ║
║  • scontrol_hold/release/requeue                         ║
║  • sstat, sdiag                                          ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    async with websockets.serve(
        lambda ws: handle_connection(ws, server),
        HOST,
        PORT
    ):
        logger.info(f"🚀 Server running on ws://{HOST}:{PORT}")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
