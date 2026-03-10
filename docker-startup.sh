#!/usr/bin/env bash
# Simple Docker-based startup for CTA data streaming stack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE=(docker compose -f "${SCRIPT_DIR}/docker-compose.yml")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== CTA Data Streaming — Docker Startup ===${NC}"
echo

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}✗ Docker daemon is not running${NC}"
    echo "Start Docker Desktop and try again."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose >/dev/null 2>&1 && ! docker compose --version >/dev/null 2>&1; then
    echo -e "${RED}✗ docker-compose is not available${NC}"
    exit 1
fi

has_dotenv_key() {
    local key=$1
    [[ -f "${SCRIPT_DIR}/.env" ]] && grep -Eq "^${key}=.+" "${SCRIPT_DIR}/.env"
}

missing_vars=()
for required_var in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
    if [[ -z "${!required_var:-}" ]] && ! has_dotenv_key "${required_var}"; then
        missing_vars+=("${required_var}")
    fi
done

if (( ${#missing_vars[@]} > 0 )); then
    echo -e "${RED}✗ Missing required DB credentials: ${missing_vars[*]}${NC}"
    echo "ERROR: POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB are required." >&2
    echo "Create ${SCRIPT_DIR}/.env from .env.example and set secure values." >&2
    exit 1
fi

echo -e "${YELLOW}Cleaning up previous containers...${NC}"
"${COMPOSE[@]}" down --remove-orphans 2>/dev/null || true
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo

echo -e "${YELLOW}Building images...${NC}"
"${COMPOSE[@]}" build --no-cache || {
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
}
echo -e "${GREEN}✓ Build complete${NC}"
echo

echo -e "${YELLOW}Starting infrastructure and services...${NC}"
"${COMPOSE[@]}" up -d
echo -e "${GREEN}✓ Containers started${NC}"
echo

# Wait for critical services
echo -e "${YELLOW}Waiting for services to be ready...${NC}"

wait_for_http() {
    local service=$1
    local url=$2
    local timeout=${3:-120}
    local waited=0

    echo -n "  Checking ${service}..."
    while ! curl -fsS "${url}" >/dev/null 2>&1; do
        if (( waited >= timeout )); then
            echo -e " ${RED}✗ Timeout${NC}"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
        echo -n "."
    done
    echo -e " ${GREEN}✓ Ready${NC}"
    return 0
}

wait_for_kafka() {
    local timeout=${1:-120}
    local waited=0

    echo -n "  Checking Kafka..."
    while ! "${COMPOSE[@]}" exec -T kafka0 kafka-topics --bootstrap-server localhost:9092 --list >/dev/null 2>&1; do
        if (( waited >= timeout )); then
            echo -e " ${RED}✗ Timeout${NC}"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
        echo -n "."
    done
    echo -e " ${GREEN}✓ Ready${NC}"
    return 0
}

wait_for_container_health() {
    local service=$1
    local timeout=${2:-120}
    local waited=0
    local container_id
    local status

    echo -n "  Checking ${service} health..."
    while true; do
        container_id=$("${COMPOSE[@]}" ps -q "${service}" 2>/dev/null || true)
        if [[ -n "${container_id}" ]]; then
            status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}" 2>/dev/null || echo "unknown")
            if [[ "${status}" == "healthy" || "${status}" == "running" ]]; then
                echo -e " ${GREEN}✓ Ready${NC}"
                return 0
            fi
            if [[ "${status}" == "exited" || "${status}" == "dead" ]]; then
                echo -e " ${RED}✗ ${status}${NC}"
                return 1
            fi
        fi

        if (( waited >= timeout )); then
            echo -e " ${RED}✗ Timeout${NC}"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
        echo -n "."
    done
}

wait_for_kafka 120 || {
    echo -e "${RED}Failed waiting for Kafka${NC}"
    "${COMPOSE[@]}" logs kafka0 | tail -20
    exit 1
}

wait_for_http "Schema Registry" "http://localhost:8081" 120 || {
    echo -e "${RED}Failed waiting for Schema Registry${NC}"
    exit 1
}

wait_for_http "KSQL" "http://localhost:8088/info" 180 || {
    echo -e "${RED}Failed waiting for KSQL${NC}"
    "${COMPOSE[@]}" logs ksql | tail -30
    exit 1
}

wait_for_container_health "faust" 180 || {
    echo -e "${RED}Failed waiting for Faust${NC}"
    "${COMPOSE[@]}" logs faust | tail -30
    exit 1
}

wait_for_http "Dashboard" "http://localhost:3000" 120 || {
    echo -e "${RED}Failed waiting for Dashboard${NC}"
    "${COMPOSE[@]}" logs consumer | tail -30
    exit 1
}

echo
echo -e "${GREEN}✓ All services are ready!${NC}"
echo
echo -e "${GREEN}=== Startup Complete ===${NC}"
echo
echo "Services:"
echo -e "  Dashboard:      ${GREEN}http://localhost:3000${NC}"
echo "  Kafka Broker:   localhost:9092"
echo "  Schema Registry: http://localhost:8081"
echo "  KSQL:           http://localhost:8088"
echo "  Faust:          healthy inside Docker"
echo
echo "Useful commands:"
echo "  List service names:    docker compose config --services"
echo "  View all logs:         docker compose logs -f"
echo "  View Faust logs:       docker compose logs -f faust"
echo "  View Producer logs:    docker compose logs -f producer"
echo "  View Consumer logs:    docker compose logs -f consumer"
echo "  Stop everything:      docker compose down"
echo "  Restart a service:    docker compose restart <service>"
echo "  Health check:         docker compose ps"
echo
