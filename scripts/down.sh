#!/usr/bin/env bash
# Destroy the demo environment, then check nothing billable is left behind.
# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "$0")/_common.sh"

tf_init
terraform -chdir="$DEMO_DIR" destroy -input=false
echo
"$ROOT/scripts/whats-running.sh"
