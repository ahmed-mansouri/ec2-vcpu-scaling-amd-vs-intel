#!/usr/bin/env bash
#
# cpu-scale.sh
#
# Measures how aggregate CPU throughput scales with the number of
# concurrently running, independently pinned OpenSSL workers.
#
# One OpenSSL process is pinned to exactly one logical CPU with taskset.
# Logical CPUs are selected so that one logical CPU from every physical
# core is used first; SMT siblings (if the instance exposes any) are used
# only after every physical core already has one worker.
#
# Usage:
#   DURATION=60 REPEATS=5 ./cpu-scale.sh
#
# Environment variables:
#   DURATION    seconds per repetition           (default 60)
#   REPEATS     repetitions per worker count     (default 5)
#   ALGORITHM   openssl speed algorithm          (default sha256)
#   BLOCK_SIZE  bytes per hashed block           (default 16384)
#
set -euo pipefail
export LC_ALL=C

# Benchmark configuration. Override these with environment variables.
DURATION="${DURATION:-60}"
REPEATS="${REPEATS:-5}"
ALGORITHM="${ALGORITHM:-sha256}"
BLOCK_SIZE="${BLOCK_SIZE:-16384}"

# Validate configuration.
if ! [[ "$DURATION" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: DURATION must be a positive integer." >&2
    exit 1
fi

if ! [[ "$REPEATS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: REPEATS must be a positive integer." >&2
    exit 1
fi

# Verify required commands.
REQUIRED_COMMANDS=(
    awk
    curl
    date
    lscpu
    openssl
    sort
    taskset
)

for COMMAND in "${REQUIRED_COMMANDS[@]}"; do
    if ! command -v "$COMMAND" >/dev/null 2>&1; then
        echo "ERROR: Required command not found: $COMMAND" >&2
        exit 1
    fi
done

# Retrieve the EC2 instance type using IMDSv2.
IMDS_BASE="http://169.254.169.254/latest"

TOKEN=$(curl --noproxy '*' \
    --fail \
    --silent \
    --show-error \
    --request PUT \
    --header "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
    "$IMDS_BASE/api/token")

INSTANCE_TYPE=$(curl --noproxy '*' \
    --fail \
    --silent \
    --show-error \
    --header "X-aws-ec2-metadata-token: $TOKEN" \
    "$IMDS_BASE/meta-data/instance-type")

if [[ -z "$INSTANCE_TYPE" ]]; then
    echo "ERROR: Could not determine the EC2 instance type." >&2
    exit 1
fi

# Use a timestamped directory so previous benchmark results are preserved.
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
BASE_OUTPUT="$HOME/cpu-comparison-$INSTANCE_TYPE"
OUTPUT="${BASE_OUTPUT}-${RUN_ID}"
LATEST_LINK="${BASE_OUTPUT}-latest"

mkdir -p "$OUTPUT/raw"
ln -sfn "$OUTPUT" "$LATEST_LINK"

# Discover CPU topology.
#
# ORDERED_CPUS contains:
#   1. One logical CPU from every physical core.
#   2. SMT sibling CPUs afterward.
#
# This ensures that on Intel:
#   - 16 workers use one thread on each of 16 physical cores.
#   - 32 workers use both threads on all 16 physical cores.
#
# On AMD c7a, every logical CPU represents a distinct physical core.
mapfile -t ORDERED_CPUS < <(
    lscpu -p=CPU,CORE,SOCKET |
    awk -F, '
        !/^#/ {
            key=$3 ":" $2

            if (!(key in seen)) {
                seen[key]=1
                primary[++primary_count]=$1
            } else {
                sibling[++sibling_count]=$1
            }
        }

        END {
            for (i=1; i<=primary_count; i++) {
                print primary[i]
            }

            for (i=1; i<=sibling_count; i++) {
                print sibling[i]
            }
        }
    '
)

TOTAL_CPUS="${#ORDERED_CPUS[@]}"

if (( TOTAL_CPUS == 0 )); then
    echo "ERROR: No online logical CPUs were discovered." >&2
    exit 1
fi

# Build the worker-count list, excluding values larger than this instance.
REQUESTED_COUNTS=(1 2 4 8 16 32)
COUNTS=()

for COUNT in "${REQUESTED_COUNTS[@]}"; do
    if (( COUNT <= TOTAL_CPUS )); then
        COUNTS+=("$COUNT")
    fi
done

# Save system and benchmark configuration.
{
    echo "run_id=$RUN_ID"
    echo "instance_type=$INSTANCE_TYPE"
    echo "logical_cpus=$TOTAL_CPUS"
    echo "duration_seconds=$DURATION"
    echo "repeats=$REPEATS"
    echo "algorithm=$ALGORITHM"
    echo "block_size_bytes=$BLOCK_SIZE"
    echo "ordered_cpus=${ORDERED_CPUS[*]}"
    echo
    echo "=== OpenSSL version ==="
    openssl version -a
    echo
    echo "=== CPU summary ==="
    lscpu
    echo
    echo "=== CPU topology ==="
    lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
} > "$OUTPUT/system-info.txt"

echo "workers,repeat,aggregate_kBps" > "$OUTPUT/results.csv"

echo "Instance type: $INSTANCE_TYPE"
echo "Logical CPUs: $TOTAL_CPUS"
echo "Worker counts: ${COUNTS[*]}"
echo "Duration per repetition: $DURATION seconds"
echo "Repetitions per worker count: $REPEATS"
echo "Output directory: $OUTPUT"
echo "Latest-results link: $LATEST_LINK"
echo

# Warm up OpenSSL and one CPU before collecting results.
echo "Running 10-second warm-up..."

taskset -c "${ORDERED_CPUS[0]}" \
    openssl speed \
        -seconds 10 \
        -elapsed \
        -bytes "$BLOCK_SIZE" \
        "$ALGORITHM" \
    >/dev/null 2>&1

echo "Warm-up complete."
echo

# Run each worker-count test.
for WORKERS in "${COUNTS[@]}"; do
    for REPEAT in $(seq 1 "$REPEATS"); do
        RUN_DIR="$OUTPUT/raw/workers-${WORKERS}-repeat-${REPEAT}"
        mkdir -p "$RUN_DIR"

        echo "Running $INSTANCE_TYPE: workers=$WORKERS repeat=$REPEAT/$REPEATS"

        PIDS=()

        # Start one independently pinned OpenSSL process per selected vCPU.
        for INDEX in $(seq 0 $((WORKERS - 1))); do
            CPU="${ORDERED_CPUS[$INDEX]}"

            taskset -c "$CPU" \
                openssl speed \
                    -seconds "$DURATION" \
                    -elapsed \
                    -bytes "$BLOCK_SIZE" \
                    "$ALGORITHM" \
                > "$RUN_DIR/cpu-${CPU}.log" 2>&1 &

            PIDS+=("$!")
        done

        # Wait for every worker and fail if any worker fails.
        WORKER_FAILED=0

        for PID in "${PIDS[@]}"; do
            if ! wait "$PID"; then
                WORKER_FAILED=1
            fi
        done

        if (( WORKER_FAILED != 0 )); then
            echo "ERROR: At least one OpenSSL worker failed." >&2
            echo "Inspect logs under: $RUN_DIR" >&2
            exit 1
        fi

        # Read the final OpenSSL throughput line from each worker log.
        #
        # OpenSSL normally reports throughput with a suffix such as:
        #   123456.78k
        #
        # All values are converted to decimal kilobytes per second and summed.
        if ! AGGREGATE=$(
            awk -v algorithm="$ALGORITHM" '
                $1 == algorithm {
                    value=$NF
                    unit=substr(value, length(value), 1)

                    if (unit == "k" || unit == "K") {
                        value=substr(value, 1, length(value)-1)
                    } else if (unit == "m" || unit == "M") {
                        value=substr(value, 1, length(value)-1) * 1000
                    } else if (unit == "g" || unit == "G") {
                        value=substr(value, 1, length(value)-1) * 1000000
                    }

                    total += value
                    matches++
                }

                END {
                    if (matches == 0) {
                        exit 2
                    }

                    printf "%.2f\n", total
                }
            ' "$RUN_DIR"/*.log
        ); then
            echo "ERROR: Could not parse OpenSSL throughput." >&2
            echo "Inspect logs under: $RUN_DIR" >&2
            exit 1
        fi

        echo "$WORKERS,$REPEAT,$AGGREGATE" |
            tee -a "$OUTPUT/results.csv"
    done
done

# Calculate averages and scaling efficiency.
#
# Scaling efficiency:
#
#   aggregate throughput with N workers
#   ------------------------------------ x 100
#   N x average single-worker throughput
#
# Each instance uses its own single-worker baseline.
echo \
    "workers,avg_aggregate_kBps,avg_per_worker_kBps,scaling_efficiency_pct" \
    > "$OUTPUT/summary.csv"

awk -F, '
    NR > 1 {
        workers=$1
        sum[workers]+=$3
        count[workers]++
    }

    END {
        if (!(1 in sum) || count[1] == 0) {
            print "ERROR: Missing single-worker baseline." > "/dev/stderr"
            exit 1
        }

        baseline=sum[1] / count[1]

        for (workers in sum) {
            aggregate=sum[workers] / count[workers]
            per_worker=aggregate / workers
            efficiency=100 * aggregate / (workers * baseline)

            printf "%d,%.2f,%.2f,%.2f\n",
                workers,
                aggregate,
                per_worker,
                efficiency
        }
    }
' "$OUTPUT/results.csv" |
    sort -t, -k1,1n >> "$OUTPUT/summary.csv"

echo
echo "=== BENCHMARK COMPLETE ==="
echo
column -s, -t "$OUTPUT/summary.csv" 2>/dev/null ||
    cat "$OUTPUT/summary.csv"

echo
echo "System information: $OUTPUT/system-info.txt"
echo "Raw measurements:   $OUTPUT/results.csv"
echo "Final summary:      $OUTPUT/summary.csv"
echo "Individual logs:    $OUTPUT/raw"
echo "Latest-results link: $LATEST_LINK"
