#!/bin/bash

# modules/kestra/startup-script.sh

set -e

# Log everything
exec > >(tee /var/log/kestra-startup.log)
exec 2>&1

echo "Starting Kestra installation at $(date)"

# Update system
echo "Updating system packages..."
apt-get update

# Install basic dependencies
apt-get install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
echo "Adding Docker GPG key..."
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo "Adding Docker repository..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# Update package index
apt-get update

# Install Docker Engine, containerd, and Docker Compose
echo "Installing Docker..."
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker service
echo "Starting Docker service..."
systemctl start docker
systemctl enable docker

# Add user to docker group
usermod -aG docker ubuntu

# Install Google Cloud SDK
echo "Installing Google Cloud SDK..."
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add -
echo "deb https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
apt-get update
apt-get install -y google-cloud-sdk

# Create directory for Kestra
echo "Creating Kestra directory..."
mkdir -p /opt/kestra
cd /opt/kestra

# Debug: Show variables
echo "Debug: Database host: ${db_host}"
echo "Debug: Database name: ${db_name}"
echo "Debug: Database user: ${db_user}"
echo "Debug: GCS bucket: ${gcs_bucket}"
echo "Debug: Project ID: ${project_id}"

# Create docker-compose.yml file
echo "Creating Docker Compose configuration..."
cat > docker-compose.yml << EOF
version: "3.8"

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

# Wait for database to be ready
echo "Waiting for database to be ready..."
max_attempts=30
attempt=1

while [ $attempt -le $max_attempts ]; do
    echo "Attempt $attempt/$max_attempts: Testing database connection..."
    if docker run --rm postgres:15 pg_isready -h ${db_host} -p 5432 -U ${db_user} >/dev/null 2>&1; then
        echo "Database is ready!"
        break
    else
        echo "Database not ready, waiting 10 seconds..."
        sleep 10
        ((attempt++))
    fi
done

if [ $attempt -gt $max_attempts ]; then
    echo "ERROR: Database failed to become ready after $max_attempts attempts"
    exit 1
fi

# Start Kestra
echo "Starting Kestra..."
docker compose up -d

# Wait for Kestra to be healthy
echo "Waiting for Kestra to start..."
max_attempts=30
attempt=1

while [ $attempt -le $max_attempts ]; do
    echo "Attempt $attempt/$max_attempts: Testing Kestra health..."
    if curl -f http://localhost:8080/health >/dev/null 2>&1; then
        echo "SUCCESS: Kestra is healthy and ready!"
        break
    else
        echo "Kestra not ready, waiting 15 seconds..."
        sleep 15
        ((attempt++))
    fi
done

if [ $attempt -gt $max_attempts ]; then
    echo "WARNING: Kestra failed to become healthy after $max_attempts attempts"
    echo "Showing container logs for debugging:"
    docker compose logs
    echo "Kestra may still be starting up. Check logs with: docker compose logs -f"
else
    echo "SUCCESS: Kestra deployment completed successfully!"
fi

# Get external IP
EXTERNAL_IP=$(curl -s ifconfig.me)
echo "Kestra UI is available at: http://$EXTERNAL_IP:8080"

echo "Installation completed at $(date)"