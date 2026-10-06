#!/usr/bin/env bash
#
# collect-environment.sh
#
# Records the identity of the EC2 instance and the software environment
# so that a benchmark result can be reproduced later.
#
# Usage:
#   ./collect-environment.sh            # prints and saves to $HOME/article-environment.txt
#
set -euo pipefail

IMDS_BASE="http://169.254.169.254/latest"

TOKEN=$(curl --noproxy '*' \
    --fail \
    --silent \
    --show-error \
    --request PUT \
    --header "X-aws-ec2-metadata-token-ttl-seconds: 300" \
    "$IMDS_BASE/api/token")

imds() {
    curl --noproxy '*' --fail --silent --show-error \
        --header "X-aws-ec2-metadata-token: $TOKEN" \
        "$IMDS_BASE/meta-data/$1"
    echo
}

{
    echo "=== EC2 identity ==="
    printf 'Instance type: ';     imds instance-type
    printf 'AMI ID: ';            imds ami-id
    printf 'Availability Zone: '; imds placement/availability-zone

    echo
    echo "=== Operating system ==="
    cat /etc/os-release

    echo
    echo "=== Kernel ==="
    uname -a

    echo
    echo "=== Packages ==="
    rpm -q openssl kernel-core 2>/dev/null || true

    echo
    echo "=== CPU topology (short) ==="
    lscpu | grep -E \
        'Architecture|^CPU\(s\)|Model name|Vendor ID|Socket|Core|Thread|NUMA'

    echo
    echo "=== Logical CPU to physical core mapping ==="
    lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
} | tee "$HOME/article-environment.txt"
