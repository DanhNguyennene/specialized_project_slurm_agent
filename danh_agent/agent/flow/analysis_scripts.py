"""
Predefined Analysis Scripts for Slurm Agent

These are READ-ONLY analysis scripts. No dangerous actions.
Agent picks the right script, system runs it A-Z.

Each script is a fixed sequence of Slurm commands for common analysis tasks.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum


class AnalysisCategory(str, Enum):
    """Categories of analysis"""
    JOBS = "jobs"           # Job-related queries
    CLUSTER = "cluster"     # Cluster/node status
    ACCOUNT = "account"     # User/account info
    DEBUG = "debug"         # Troubleshooting


@dataclass
class AnalysisScript:
    """A predefined analysis script"""
    id: str                      # Unique ID
    name: str                    # Human name
    description: str             # What it does (for agent to understand)
    category: AnalysisCategory   # Category
    commands: List[str]          # Slurm commands to run in sequence
    

# ============ JOB ANALYSIS ============

LIST_MY_JOBS = AnalysisScript(
    id="list_my_jobs",
    name="List My Jobs",
    description="Show all my current jobs (running and pending)",
    category=AnalysisCategory.JOBS,
    commands=[
        "squeue --me --format='%.18i %.9P %.30j %.8u %.8T %.10M %.9l %.6D %R'",
    ]
)

LIST_ALL_JOBS = AnalysisScript(
    id="list_all_jobs",
    name="List All Queue Jobs",
    description="Show all jobs in the queue from all users",
    category=AnalysisCategory.JOBS,
    commands=[
        "squeue --format='%.18i %.9P %.30j %.8u %.8T %.10M %.9l %.6D %R'",
    ]
)

MY_JOB_HISTORY = AnalysisScript(
    id="my_job_history",
    name="My Job History",
    description="Show my recent job history with exit codes and runtime",
    category=AnalysisCategory.JOBS,
    commands=[
        "sacct --me --format=JobID,JobName%30,Partition,State,ExitCode,Elapsed,MaxRSS,MaxVMSize,Start,End -S $(date -d '7 days ago' +%Y-%m-%d)",
    ]
)

MY_FAILED_JOBS = AnalysisScript(
    id="my_failed_jobs",
    name="My Failed Jobs",
    description="Show my recently failed jobs with failure reasons",
    category=AnalysisCategory.JOBS,
    commands=[
        "sacct --me --state=FAILED,TIMEOUT,OUT_OF_MEMORY,CANCELLED,NODE_FAIL --format=JobID,JobName%30,State,ExitCode,Elapsed,MaxRSS,Start,End -S $(date -d '7 days ago' +%Y-%m-%d)",
    ]
)

MY_PENDING_JOBS = AnalysisScript(
    id="my_pending_jobs",
    name="My Pending Jobs",
    description="Show my pending jobs with reasons why they are waiting",
    category=AnalysisCategory.JOBS,
    commands=[
        "squeue --me --state=PENDING --format='%.18i %.9P %.30j %.8u %.8T %.10M %.9l %.6D %R'",
    ]
)

JOB_PRIORITIES = AnalysisScript(
    id="job_priorities",
    name="Job Priorities",
    description="Show job priority breakdown (age, fairshare, etc)",
    category=AnalysisCategory.JOBS,
    commands=[
        "sprio --me --format='%.15i %.10Y %.10A %.10F %.10J %.10P %.10Q'",
    ]
)


# ============ CLUSTER ANALYSIS ============

CLUSTER_STATUS = AnalysisScript(
    id="cluster_status",
    name="Cluster Status",
    description="Show all partitions and node availability",
    category=AnalysisCategory.CLUSTER,
    commands=[
        "sinfo --format='%20P %5a %.10l %16F %10z %10m %10G'",
    ]
)

CLUSTER_LOAD = AnalysisScript(
    id="cluster_load",
    name="Cluster Load",
    description="Show cluster utilization and load",
    category=AnalysisCategory.CLUSTER,
    commands=[
        "sinfo --format='%20P %5a %10A %10c %10m' --noheader | awk '{print $0}'",
        "squeue --noheader | wc -l",
    ]
)

NODE_STATUS = AnalysisScript(
    id="node_status",
    name="Node Status",
    description="Show detailed status of all nodes",
    category=AnalysisCategory.CLUSTER,
    commands=[
        "sinfo -N --format='%20N %10P %10T %10c %10m %20f %30E'",
    ]
)

GPU_STATUS = AnalysisScript(
    id="gpu_status",
    name="GPU Status",
    description="Show GPU availability across the cluster",
    category=AnalysisCategory.CLUSTER,
    commands=[
        "sinfo -p gpu --format='%20N %10P %10T %10c %10m %25G %20f' 2>/dev/null || sinfo --format='%20N %10P %10T %10c %10m %25G'",
    ]
)

DOWN_NODES = AnalysisScript(
    id="down_nodes",
    name="Down Nodes",
    description="Show nodes that are down or draining with reasons",
    category=AnalysisCategory.CLUSTER,
    commands=[
        "sinfo -R --format='%20N %10T %50E'",
    ]
)

PARTITION_LIMITS = AnalysisScript(
    id="partition_limits",
    name="Partition Limits",
    description="Show time limits and resource limits per partition",
    category=AnalysisCategory.CLUSTER,
    commands=[
        "sinfo --format='%20P %10l %10L %10s %10c %10m %10G'",
    ]
)


# ============ ACCOUNT ANALYSIS ============

MY_FAIRSHARE = AnalysisScript(
    id="my_fairshare",
    name="My Fairshare",
    description="Show my fairshare and usage compared to others",
    category=AnalysisCategory.ACCOUNT,
    commands=[
        "sshare --me --format=Account,User,RawShares,NormShares,RawUsage,NormUsage,EffectvUsage,FairShare",
    ]
)

MY_ACCOUNT_INFO = AnalysisScript(
    id="my_account_info",
    name="My Account Info",
    description="Show my account associations and limits",
    category=AnalysisCategory.ACCOUNT,
    commands=[
        "sacctmgr show user $USER withassoc format=User,Account,DefaultAccount,Share,MaxJobs,MaxSubmit,QOS",
    ]
)

ACCOUNT_USAGE = AnalysisScript(
    id="account_usage",
    name="Account Usage Report",
    description="Show account usage report for the past month",
    category=AnalysisCategory.ACCOUNT,
    commands=[
        "sreport cluster AccountUtilizationByUser start=$(date -d '30 days ago' +%Y-%m-%d) end=$(date +%Y-%m-%d) --tres=cpu,mem,gres/gpu -t hourper",
    ]
)


# ============ DEBUG/TROUBLESHOOTING ============

DEBUG_PENDING = AnalysisScript(
    id="debug_pending",
    name="Debug Pending Jobs",
    description="Analyze why jobs are pending - check resources and reasons",
    category=AnalysisCategory.DEBUG,
    commands=[
        "squeue --me --state=PENDING --format='%.18i %.30j %R'",
        "sinfo --format='%20P %5a %10A'",
    ]
)

DEBUG_FAILED = AnalysisScript(
    id="debug_failed",
    name="Debug Failed Jobs",
    description="Analyze recent job failures with detailed info",
    category=AnalysisCategory.DEBUG,
    commands=[
        "sacct --me --state=FAILED,TIMEOUT,OUT_OF_MEMORY --format=JobID,JobName%30,State,ExitCode,Elapsed,MaxRSS,NodeList,Start -S $(date -d '3 days ago' +%Y-%m-%d)",
    ]
)

SCHEDULER_STATS = AnalysisScript(
    id="scheduler_stats",
    name="Scheduler Statistics",
    description="Show Slurm scheduler diagnostics and performance",
    category=AnalysisCategory.DEBUG,
    commands=[
        "sdiag",
    ]
)

QOS_INFO = AnalysisScript(
    id="qos_info",
    name="QOS Information",
    description="Show available QOS levels and their limits",
    category=AnalysisCategory.DEBUG,
    commands=[
        "sacctmgr show qos format=Name,Priority,MaxWall,MaxTRES%50,MaxJobsPU,MaxSubmitPU",
    ]
)


# ============ REGISTRY ============

ALL_SCRIPTS: Dict[str, AnalysisScript] = {
    # Jobs
    "list_my_jobs": LIST_MY_JOBS,
    "list_all_jobs": LIST_ALL_JOBS,
    "my_job_history": MY_JOB_HISTORY,
    "my_failed_jobs": MY_FAILED_JOBS,
    "my_pending_jobs": MY_PENDING_JOBS,
    "job_priorities": JOB_PRIORITIES,
    # Cluster
    "cluster_status": CLUSTER_STATUS,
    "cluster_load": CLUSTER_LOAD,
    "node_status": NODE_STATUS,
    "gpu_status": GPU_STATUS,
    "down_nodes": DOWN_NODES,
    "partition_limits": PARTITION_LIMITS,
    # Account
    "my_fairshare": MY_FAIRSHARE,
    "my_account_info": MY_ACCOUNT_INFO,
    "account_usage": ACCOUNT_USAGE,
    # Debug
    "debug_pending": DEBUG_PENDING,
    "debug_failed": DEBUG_FAILED,
    "scheduler_stats": SCHEDULER_STATS,
    "qos_info": QOS_INFO,
}

SCRIPTS_BY_CATEGORY: Dict[AnalysisCategory, List[AnalysisScript]] = {
    AnalysisCategory.JOBS: [LIST_MY_JOBS, LIST_ALL_JOBS, MY_JOB_HISTORY, MY_FAILED_JOBS, MY_PENDING_JOBS, JOB_PRIORITIES],
    AnalysisCategory.CLUSTER: [CLUSTER_STATUS, CLUSTER_LOAD, NODE_STATUS, GPU_STATUS, DOWN_NODES, PARTITION_LIMITS],
    AnalysisCategory.ACCOUNT: [MY_FAIRSHARE, MY_ACCOUNT_INFO, ACCOUNT_USAGE],
    AnalysisCategory.DEBUG: [DEBUG_PENDING, DEBUG_FAILED, SCHEDULER_STATS, QOS_INFO],
}


def get_script(script_id: str) -> Optional[AnalysisScript]:
    """Get a script by ID"""
    return ALL_SCRIPTS.get(script_id)


def get_script_list_for_prompt() -> str:
    """Generate script list for agent prompt - compact format"""
    lines = []
    for cat, scripts in SCRIPTS_BY_CATEGORY.items():
        lines.append(f"[{cat.value}]")
        for s in scripts:
            lines.append(f"  {s.id}: {s.description}")
    return "\n".join(lines)


def get_all_script_ids() -> List[str]:
    """Get all available script IDs"""
    return list(ALL_SCRIPTS.keys())
