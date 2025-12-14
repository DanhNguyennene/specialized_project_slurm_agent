#!/usr/bin/env python3
"""
Quick Start: Create a Slurm job in 3 lines of Python
"""
from utils.slurm_commands import *

# 1. Define your job
job = SlurmCommandSequence(
    description="My training job",
    commands=[
        SbatchCommand(
            script_path="/tmp/my_job.sh",
            command="python train.py --epochs 100",
            job_name="my_training",
            partition="gpu",
            nodes=1,
            ntasks=1,
            cpus_per_task=8,
            mem="32GB",
            time="4:00:00",
            output="/logs/job_%j.out",
            error="/logs/job_%j.err"
        )
    ]
)

# 2. Build it
builder = SlurmCommandBuilder()

# 3. Save and done!
builder.save_script(job, "/tmp/my_slurm_job.sh")

print("✅ Created: /tmp/my_slurm_job.sh")
print("Run on Slurm cluster: bash /tmp/my_slurm_job.sh")
