#!/usr/bin/env bash

(
    unset $PROVISON
    unset $DASHBOARD
    /opt/bitnami/scripts/grafana/entrypoint.sh /opt/bitnami/scripts/grafana/run.sh
) &

set -u


GRAFANA_URL=${GRAFANA_URL:-http://localhost:3000}

printf "\nGrafana Provisioning: complete.\n"

wait
