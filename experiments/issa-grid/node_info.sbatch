#!/bin/bash
# Print what a node of a partition looks like, to compare compute-p1 and memory.
# usage: sbatch --partition=compute-p1 --account=research-eemcs-st node_info.sbatch
#        sbatch --partition=memory     --account=research-eemcs-st --mem-per-cpu=8000M node_info.sbatch
# The memory partition refuses a request that would fit on the compute partitions (1 GB per CPU is
# refused with "requests the 'memory' partition, but the requested memory per CPU ... fits on the
# compute partitions"), so the command-line --mem-per-cpu must exceed about 4000M there.
#SBATCH --job-name=node-info
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=1G
#SBATCH --time=00:02:00
#SBATCH --output=slurm-logs/node-info-%j.out
hostname
lscpu | grep -E 'Model name|^CPU\(s\)|MHz|L3 cache'
free -m | head -2
