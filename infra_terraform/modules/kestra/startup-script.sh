#!/bin/bash

# modules/kestra/startup-script.sh
#
# Provisions Docker + Kestra (standalone, Postgres-backed, GCS storage) on a
# fresh Debian/Ubuntu GCE VM. Designed to be idempotent: safe to re-run via
# `sudo google_metadata_script_runner startup` or an instance reset/restart.

set -euo pipefail

# ── Logging ──────────────────────────────────────────────────────────────
exec > >(tee /var/log/kestra-startup.log)
exec 2>&1

echo "=== Starting Kestra installation at $(date) ==="

# Surface the exact failing command/line if anything goes wrong, instead of
# silently stopping mid-script.
trap 'echo "!!! Startup script FAILED at line $LINENO. Last command: $BASH_COMMAND"' ERR

export DEBIAN_FRONTEND=noninteractive

# ── apt-get update with retries (transient network/mirror issues) ─────────
apt_update_with_retry() {
  local attempts=0
  local max_attempts=5
  until apt-get update -y; do
    attempts=$((attempts + 1))
    if [ $attempts -ge $max_attempts ]; then
      echo "ERROR: apt-get update failed after $max_attempts attempts"
      return 1
    fi
    echo "apt-get update failed, retrying ($attempts/$max_attempts)..."
    sleep 5
  done
}

echo "Updating system packages..."
apt_update_with_retry

# ── Basic dependencies ──────────────────────────────────────────────────
apt-get install -y ca-certificates curl gnupg lsb-release postgresql-client

# ── Docker install (idempotent: skip if already present) ────────────────
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."

  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

  apt_update_with_retry
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  echo "Docker already installed, skipping."
fi

echo "Starting Docker service..."
systemctl start docker
systemctl enable docker
usermod -aG docker ubuntu || true

# ── Google Cloud CLI (optional convenience tool; NOT required by Kestra) ──
# NOTE: the Debian/Ubuntu package was renamed from google-cloud-sdk to
# google-cloud-cli. Installing it is best-effort — nothing later in this
# script depends on gcloud being present, so a failure here must never
# abort provisioning of Kestra itself.
if ! command -v gcloud >/dev/null 2>&1; then
  echo "Installing Google Cloud CLI (best-effort)..."
  set +e
  curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add - \
    && echo "deb https://packages.cloud.google.com/apt cloud-sdk main" | tee /etc/apt/sources.list.d/google-cloud-sdk.list \
    && apt_update_with_retry \
    && apt-get install -y google-cloud-cli
  if [ $? -ne 0 ]; then
    echo "WARNING: google-cloud-cli install failed — continuing without it (not required for Kestra)."
  fi
  set -e
else
  echo "gcloud already installed, skipping."
fi

# ── Kestra directory + compose file ──────────────────────────────────────
echo "Creating Kestra directory..."
mkdir -p /opt/kestra
mkdir -p /tmp/kestra-wd
cd /opt/kestra

echo "Debug: Database host: ${db_host}"
echo "Debug: Database name: ${db_name}"
echo "Debug: Database user: ${db_user}"
echo "Debug: GCS bucket: ${gcs_bucket}"
echo "Debug: Project ID: ${project_id}"

echo "Creating Docker Compose configuration..."
cat > docker-compose.yml << EOF
services:
  kestra:
    image: kestra/kestra:v0.23.9
    pull_policy: always
    user: "root"
    command: server standalone
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /tmp/kestra-wd:/tmp/kestra-wd:rw
    environment:
      KESTRA_CONFIGURATION: |
        kestra:
          server:
            access-log:
              enabled: false
          repository:
            type: postgres
          storage:
            type: gcs
            gcs:
              bucket: ${gcs_bucket}
              project-id: ${project_id}
          queue:
            type: postgres
          secret:
            type: postgres
        datasources:
          postgres:
            url: jdbc:postgresql://${db_host}:5432/${db_name}
            driverClassName: org.postgresql.Driver
            username: ${db_user}
            password: ${db_password}
        micronaut:
          security:
            enabled: false
          server:
            port: 8080
            host: 0.0.0.0
        logging:
          level:
            io.kestra: INFO
            root: WARN
    ports:
      - "8080:8080"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
EOF

# ── Wait for Postgres to accept connections ──────────────────────────────
echo "Waiting for database to be ready..."
max_attempts=30
attempt=1
db_ready=false

while [ $attempt -le $max_attempts ]; do
  echo "Attempt $attempt/$max_attempts: Testing database connection to ${db_host}..."
  if PGPASSWORD="${db_password}" pg_isready -h "${db_host}" -p 5432 -U "${db_user}" >/dev/null 2>&1; then
    echo "Database is ready!"
    db_ready=true
    break
  fi
  echo "Database not ready, waiting 10 seconds..."
  sleep 10
  attempt=$((attempt + 1))
done

if [ "$db_ready" != "true" ]; then
  echo "WARNING: Database did not become ready after $max_attempts attempts."
  echo "Proceeding to start Kestra anyway — it will retry its own DB connection on boot."
  echo "If Kestra fails to start, check Cloud SQL status and authorized networks, then run:"
  echo "  sudo google_metadata_script_runner startup"
fi

# ── Start Kestra ──────────────────────────────────────────────────────────
echo "Starting Kestra..."
docker compose up -d

echo "Waiting for Kestra to start..."
max_attempts=30
attempt=1
kestra_ready=false

while [ $attempt -le $max_attempts ]; do
  echo "Attempt $attempt/$max_attempts: Testing Kestra health..."
  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
    echo "SUCCESS: Kestra is healthy and ready!"
    kestra_ready=true
    break
  fi
  echo "Kestra not ready, waiting 15 seconds..."
  sleep 15
  attempt=$((attempt + 1))
done

if [ "$kestra_ready" != "true" ]; then
  echo "WARNING: Kestra failed to become healthy after $max_attempts attempts."
  echo "Showing container logs for debugging:"
  docker compose logs --tail=200
  echo "Kestra may still be starting up. Check logs with: docker compose logs -f"
else
  echo "SUCCESS: Kestra deployment completed successfully!"
fi

EXTERNAL_IP=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" || echo "unknown")
echo "Kestra UI is available at: http://$EXTERNAL_IP:8080"

echo "=== Installation completed at $(date) ==="