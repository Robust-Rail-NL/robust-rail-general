#!/bin/bash
# Summarise the pilot arrays listed in ~/issa_pilot_jobs.txt: per task partition, node, elapsed time,
# peak memory (MaxRSS) and state, plus the tool (from tasks.tsv) so the numbers can be read per tool.
# usage: experiments/issa-grid/pilot_report.sh            (from anywhere)
set -uo pipefail
while read -r ARM VARIANT ARRAY OUT; do
    echo "=== arm=$ARM variant=$VARIANT array=$ARRAY ($(cat "$OUT/arm.txt" 2>/dev/null))"
    # tasks.tsv: index instance tool planner seed tool_dir; array task i is row with index i.
    sacct -j "$ARRAY" -P -n -o JobID,Partition,NodeList,Elapsed,MaxRSS,State \
      | awk -F'|' -v tsv="$OUT/tasks.tsv" '
          BEGIN { while ((getline line < tsv) > 0) { split(line, f, "\t"); if (f[1] ~ /^[0-9]+$/) lab[f[1]] = f[2] " " f[3] (f[4] != "" ? "/" f[4] : "") } }
          { split($1, p, "[_.]"); idx = p[2]; if ($1 ~ /\.extern/) next; if ($1 ~ /\.batch/) { rss[idx] = $5; next } ; row[idx] = $2 " " $3 " " $4 " " $6 }
          END { for (i in row) printf "%-4s %-40s %s  maxrss=%s\n", i, lab[i], row[i], rss[i] }' | sort -n
done < "$HOME/issa_pilot_jobs.txt"
