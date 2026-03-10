# CTA Data Streaming with Apache Kafka — Complete Guide

> A real-time Chicago Transit Authority dashboard built with Kafka, Faust, KSQL, Kafka Connect, and REST Proxy.

## What this project does

Streams CTA simulation data through Kafka and shows live status in a web dashboard.

Data flow:
- Producer writes arrivals, turnstile events, and weather
- Kafka Connect loads station reference data from Postgres
- Faust transforms station data into `org.chicago.cta.stations.table.v1`
- KSQL builds turnstile summary table
- Consumer serves dashboard at http://localhost:3000

## Prerequisites

- Docker Desktop running
- Environment variables for Postgres credentials

Create environment file:

```bash
cp .env.example .env
```

Set values in `.env`:

```env
POSTGRES_USER=<your_user>
POSTGRES_PASSWORD=<your_password>
POSTGRES_DB=cta
```

## Run

Recommended:

```bash
./docker-startup.sh
```

Manual Run:

```bash
docker compose down --volumes --remove-orphans
docker compose up --build -d
```

## Verify

```bash
docker compose ps
docker compose logs --tail=120 producer
docker compose logs --tail=120 faust
docker compose logs --tail=120 consumer
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) as stations_count from stations;"
```

Dashboard:
- http://localhost:3000

## Stop

```bash
docker compose down
```
