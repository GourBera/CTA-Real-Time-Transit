# CTA Data Streaming with Apache Kafka — Complete Guide

> A real-time Chicago Transit Authority dashboard built with Kafka, Faust, KSQL, Kafka Connect, and REST Proxy.

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Architecture — The Big Picture](#2-architecture--the-big-picture)
3. [Concepts You Need to Know](#3-concepts-you-need-to-know)
4. [Project File Map](#4-project-file-map)
5. [Step-by-Step Walkthrough](#5-step-by-step-walkthrough)
   - Step 1 — Kafka Producers (Avro)
   - Step 2 — REST Proxy (Weather)
   - Step 3 — Kafka Connect (PostgreSQL → Kafka)
   - Step 4 — Faust Stream Processor
   - Step 5 — KSQL Aggregation
   - Step 6 — Kafka Consumers & Web Dashboard
6. [How to Run](#6-how-to-run)
7. [Topic Naming Convention](#7-topic-naming-convention)
8. [Avro Schemas Explained](#8-avro-schemas-explained)
9. [Environment Variables & Security](#9-environment-variables--security)
10. [Verification & Debugging](#10-verification--debugging)
11. [Rubric Checklist](#11-rubric-checklist)
12. [Key Learnings](#12-key-learnings)

---

## 1. What This Project Does

The Chicago Transit Authority (CTA) operates three train lines — **Red**, **Blue**, and **Green**.  This project simulates the entire transit system and streams real-time data through Kafka so a web dashboard can show:

- **Where trains are** (which station, which direction)
- **How many people entered** each station (turnstile count)
- **Current weather** (temperature and conditions)

**Data flow in one sentence:**  
Producers emit train arrivals, turnstile entries and weather → Kafka stores them → Faust transforms station data → KSQL aggregates turnstile counts → Consumers read everything → Tornado web server renders the dashboard at `http://localhost:3000`.

---

## 2. Architecture — The Big Picture

```
                     ┌─────────────────────────┐
                     │   simulation.py          │
                     │   (Python Producer)      │
                     └──────┬──────┬──────┬─────┘
                            │      │      │
             Avro Producer  │      │      │  HTTP POST
          ┌─────────────────┘      │      └────────────────┐
          ▼                        ▼                        ▼
  ┌───────────────┐    ┌───────────────────┐    ┌───────────────────┐
  │ Station Topic │    │ Turnstile Topic   │    │  REST Proxy       │
  │ (per station) │    │ (single topic)    │    │  → Weather Topic  │
  └───────┬───────┘    └───────┬───────────┘    └───────┬───────────┘
          │                    │                        │
          │         ┌──────────┴────────────────────────┘
          │         │
          ▼         ▼
  ┌──────────────────────────────────┐
  │         Apache Kafka             │
  │  47+ topics, Avro serialisation  │
  │  Schema Registry for schemas     │
  └──────┬──────────┬───────┬────────┘
         │          │       │
         │          │       │   Kafka Connect
         │          │       │   (JDBC Source)
         │          │       ▼
         │          │   ┌────────────┐     ┌────────────┐
         │          │   │ PostgreSQL │────▶│ stations   │
         │          │   │ (cta DB)   │     │ topic      │
         │          │   └────────────┘     └─────┬──────┘
         │          │                            │
         │          ▼                            ▼
         │   ┌─────────────┐           ┌──────────────────┐
         │   │    KSQL     │           │  Faust Stream    │
         │   │ turnstile → │           │  stations →      │
         │   │ TURNSTILE_  │           │  stations.table  │
         │   │ SUMMARY     │           │  .v1             │
         │   └──────┬──────┘           └────────┬─────────┘
         │          │                           │
         ▼          ▼                           ▼
  ┌──────────────────────────────────────────────────┐
  │              Tornado Web Server                  │
  │   4 KafkaConsumer instances (consumer.py)        │
  │   → Lines model → Station model → Weather model │
  │   → HTML dashboard at localhost:3000             │
  └──────────────────────────────────────────────────┘
```

### Service Ports

| Service | Host Port | Docker-Internal URL | Purpose |
|---|---|---|---|
| Kafka | 9092 | kafka0:29092 | Message broker |
| Zookeeper | 2181 | zookeeper:2181 | Kafka coordination |
| Schema Registry | 8081 | schema-registry:8081 | Avro schema storage |
| REST Proxy | 8082 | rest-proxy:8082 | HTTP → Kafka bridge |
| Kafka Connect | 8083 | connect:8083 | Database → Kafka bridge |
| KSQL | 8088 | ksql:8088 | SQL over streams |
| PostgreSQL | 5432 | postgres:5432 | Station reference data |
| Dashboard | 3000 | — | Transit status web UI |

> **Important:** When code runs *inside* Docker, use the Docker-Internal URL. When code runs on your host machine, use `localhost:<port>`.

---

## 3. Concepts You Need to Know

### 3.1 Apache Kafka

Kafka is a distributed event-streaming platform.  Think of it as a durable, high-throughput message queue.

- **Topic** — a named stream of records (like a database table for events).
- **Partition** — each topic is split into partitions for parallelism.
- **Producer** — writes records to a topic.
- **Consumer** — reads records from a topic.
- **Consumer Group** — a set of consumers that share the work of reading a topic.  Kafka guarantees each partition is read by only one consumer in a group.
- **Offset** — a sequential ID for each message in a partition.

**Example:**  
When a train arrives at Clark & Lake, the producer writes one record to `org.chicago.cta.station.arrivals.clark_and_lake`.

### 3.2 Avro & Schema Registry

Avro is a compact binary serialization format with schemas.

```json
{
  "namespace": "com.udacity",
  "type": "record",
  "name": "arrival.value",
  "fields": [
    {"name": "station_id", "type": "int"},
    {"name": "train_id",   "type": "string"},
    {"name": "direction",  "type": "string"},
    {"name": "line",       "type": "string"}
  ]
}
```

- The **Schema Registry** stores these schemas so producers and consumers agree on the format.
- The Python `AvroProducer` / `AvroConsumer` automatically register and validate schemas.

### 3.3 Kafka REST Proxy

An HTTP interface to Kafka.  Useful when you can't use a native client (e.g. old hardware).

```
POST /topics/org.chicago.cta.weather.v1
Content-Type: application/vnd.kafka.avro.v2+json

{
  "key_schema": "...",
  "value_schema": "...",
  "records": [{"key": {...}, "value": {...}}]
}
```

### 3.4 Kafka Connect

A framework for streaming data **into** or **out of** Kafka without writing code.

- We use the **JDBC Source Connector** to pull the `stations` table from PostgreSQL into the `org.chicago.cta.stations` topic.
- Configuration is sent via REST API to port 8083.

### 3.5 Faust (Stream Processing in Python)

Faust lets you write Kafka stream processors in pure Python using `async/await`.

```python
@app.agent(input_topic)
async def process(stream):
    async for record in stream:
        # transform and write to a table / output topic
```

### 3.6 KSQL

SQL-like queries that run continuously over Kafka streams.

```sql
CREATE STREAM turnstile (...) WITH (KAFKA_TOPIC='...', VALUE_FORMAT='AVRO');

CREATE TABLE turnstile_summary AS
    SELECT station_id, COUNT(*) AS count
    FROM turnstile
    GROUP BY station_id;
```

### 3.7 Tornado

An asynchronous Python web framework.  The consumer web server uses Tornado to serve the HTML dashboard and simultaneously consume from Kafka.

---

## 4. Project File Map

```
home/
├── docker-compose.yml            # All infrastructure services
├── .env                          # PostgreSQL credentials (root level)
│
├── producers/
│   ├── .env                      # KAFKA_BROKER_URL, SCHEMA_REGISTRY_URL, etc.
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── simulation.py             # Main entry — runs the time simulation
│   ├── connector.py              # Step 3: Kafka Connect configuration
│   ├── models/
│   │   ├── producer.py           # Step 1: Base Producer class (shared)
│   │   ├── station.py            # Step 1: Station arrival events
│   │   ├── turnstile.py          # Step 1: Turnstile entry events
│   │   ├── weather.py            # Step 2: Weather via REST Proxy
│   │   ├── line.py               # Train line model (Blue/Red/Green)
│   │   ├── train.py              # Individual train model
│   │   └── schemas/
│   │       ├── arrival_key.json
│   │       ├── arrival_value.json
│   │       ├── turnstile_key.json
│   │       ├── turnstile_value.json
│   │       ├── weather_key.json
│   │       └── weather_value.json
│   └── data/
│       └── cta_stations.csv      # Source station data
│
├── consumers/
│   ├── .env                      # KAFKA_BROKER_URL, KSQL_URL, SERVER_PORT
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── server.py                 # Step 6: Tornado web server
│   ├── consumer.py               # Step 6: Base KafkaConsumer class
│   ├── faust_stream.py           # Step 4: Faust stream processor
│   ├── ksql.py                   # Step 5: KSQL table creation
│   ├── topic_check.py            # Utility — check if a topic exists
│   ├── models/
│   │   ├── station.py            # Station consumer model
│   │   ├── line.py               # Line consumer model
│   │   ├── lines.py              # Aggregates all three lines
│   │   └── weather.py            # Weather consumer model
│   └── templates/
│       └── status.html           # Dashboard HTML template
│
└── db-init/
    └── init.sh                   # Creates stations table in PostgreSQL
```

---

## 5. Step-by-Step Walkthrough

### Step 1 — Kafka Producers (Avro)

**Goal:** Emit train arrival and turnstile events to Kafka with Avro serialization.

#### 1a. Base Producer (`producers/models/producer.py`)

This is the **shared base class** that all producers inherit from (standout feature).

```python
class Producer:
    existing_topics = set()  # Class-level cache — avoid re-creating topics

    def __init__(self, topic_name, key_schema, value_schema, num_partitions, num_replicas):
        # 1. Store settings
        # 2. Create the topic if it doesn't exist
        # 3. Create an AvroProducer
        self.producer = AvroProducer(broker_properties,
                                     default_key_schema=key_schema,
                                     default_value_schema=value_schema)
```

**Key design decisions:**
- `existing_topics` is a **class variable** — shared across all instances so we only create each topic once.
- Topics are created **manually** with `AdminClient.create_topics()` — never relying on auto-create (standout feature).
- Topic config uses **LZ4 compression** to reduce disk usage.

#### 1b. Station Producer (`producers/models/station.py`)

```python
class Station(Producer):                          # Inherits from Producer
    key_schema = avro.load("schemas/arrival_key.json")
    value_schema = avro.load("schemas/arrival_value.json")

    def __init__(self, station_id, name, color, ...):
        topic_name = f"org.chicago.cta.station.arrivals.{station_name}"
        super().__init__(topic_name, ...)          # Creates the topic

    def run(self, train, direction, prev_station_id, prev_direction):
        self.producer.produce(
            topic=self.topic_name,
            key={"timestamp": self.time_millis()},
            value={
                "station_id": self.station_id,
                "train_id": train.train_id,
                "direction": direction,
                "line": self.color.name,
                "train_status": train.status.name,
                "prev_station_id": prev_station_id,
                "prev_direction": prev_direction,
            },
        )
```
            ### Recommended: Docker startup (single command)
            ```bash
            cd "/Users/gourbera/Udacity/Data Streaming/project-v1"

            docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) as stations_count from stations;"

#### 1c. Turnstile Producer (`producers/models/turnstile.py`)

```python
class Turnstile(Producer):
    def run(self, timestamp, time_step):
        num_entries = self.turnstile_hardware.get_entries(timestamp, time_step)
        for _ in range(num_entries):
            self.producer.produce(
                topic="org.chicago.cta.turnstile",
                key={"timestamp": self.time_millis()},
                value={
                    "station_id": self.station.station_id,
                    "station_name": self.station.name,
                    "line": self.station.color.name,
                },
            )
```
                docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT * FROM stations LIMIT 5;"
**Result:** A single `org.chicago.cta.turnstile` topic gets one record per person entering any station.

---

### Step 2 — REST Proxy (Weather)

**Goal:** Send weather data to Kafka via HTTP because the "hardware" can't use a native client.

```python
class Weather(Producer):
    rest_proxy_url = os.getenv("REST_PROXY_URL", "http://localhost:8082")

    def run(self, month):
        self._set_weather(month)   # Randomly adjust temp and status

        resp = requests.post(
            f"{self.rest_proxy_url}/topics/{self.topic_name}",
            headers={"Content-Type": "application/vnd.kafka.avro.v2+json"},
            data=json.dumps({
                "key_schema": json.dumps(Weather.key_schema),
                "value_schema": json.dumps(Weather.value_schema),
                "records": [{
                    "key": {"timestamp": self.time_millis()},
                    "value": {"temperature": self.temp, "status": self.status.name},
                }],
            }),
        )
        resp.raise_for_status()
```

**Key learnings:**
- The `Content-Type` **must** be `application/vnd.kafka.avro.v2+json` — not plain JSON.
- You must send the full key and value schemas as JSON strings inside the body.
- Topic: `org.chicago.cta.weather.v1`.

---

### Step 3 — Kafka Connect (PostgreSQL → Kafka)

**Goal:** Stream the `stations` reference table from PostgreSQL into Kafka automatically.

```python
def configure_connector():
    resp = requests.post(
        KAFKA_CONNECT_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "name": "stations",
            "config": {
                "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
                "connection.url": "jdbc:postgresql://postgres:5432/cta",
                "connection.user": os.getenv("POSTGRES_USER"),
                "connection.password": os.getenv("POSTGRES_PASSWORD"),
                "table.whitelist": "stations",
                "mode": "incrementing",
                "incrementing.column.name": "stop_id",
                "topic.prefix": "org.chicago.cta.",
                "poll.interval.ms": "60000",
            }
        }),
    )
```

**Key learnings:**
- `mode: incrementing` means Connect tracks the highest `stop_id` it has seen and only loads new rows.
- `topic.prefix: org.chicago.cta.` + table name `stations` → topic `org.chicago.cta.stations`.
- `poll.interval.ms: 60000` — checks for new data every 60 seconds (station data rarely changes).
- JSON converters (not Avro) because the Connect REST config is simpler with JSON for this use case.
- `connection.url` uses `postgres` (the Docker service name), not `localhost`.

---

### Step 4 — Faust Stream Processor

**Goal:** Transform the raw station data from Kafka Connect into a cleaner format.

**Problem:** The raw `stations` topic has many columns (`red: bool`, `blue: bool`, `green: bool`).  We want a single `line: str` field.

```python
# Input format (from Kafka Connect / PostgreSQL)
class Station(faust.Record):
    stop_id: int
    station_name: str
    station_id: int
    order: int
    red: bool
    blue: bool
    green: bool
    # ... more fields

# Output format (what consumers need)
class TransformedStation(faust.Record):
    station_id: int
    station_name: str
    order: int
    line: str              # "red", "blue", or "green"

@app.agent(topic)
async def process_stations(stations):
    async for station in stations:
        if station.red:
            line = "red"
        elif station.blue:
            line = "blue"
        elif station.green:
            line = "green"
        else:
            line = "unknown"

        table[station.station_id] = TransformedStation(
            station_id=station.station_id,
            station_name=station.station_name,
            order=station.order,
            line=line,
        )
```

**Key learnings:**
- Faust uses `kafka://` scheme, not `PLAINTEXT://` — we strip the prefix.
- `store="memory://"` keeps the table in RAM (fine for development).
- Input topic: `org.chicago.cta.stations` → Output topic: `org.chicago.cta.stations.table.v1`.
- Run with: `faust -A faust_stream worker -l info`.

---

### Step 5 — KSQL Aggregation

**Goal:** Continuously count turnstile entries per station.

```sql
CREATE STREAM turnstile (
    station_id INT,
    station_name VARCHAR,
    line VARCHAR
) WITH (
    KAFKA_TOPIC='org.chicago.cta.turnstile',
    VALUE_FORMAT='AVRO'
);

CREATE TABLE turnstile_summary
WITH (VALUE_FORMAT='JSON') AS
    SELECT station_id, COUNT(station_id) AS count
    FROM turnstile
    GROUP BY station_id;
```

**Key learnings:**
- A **STREAM** is an unbounded sequence of events (immutable, append-only).
- A **TABLE** is a materialized view that updates as new events arrive.
- `GROUP BY station_id` keeps a running count per station — exactly what the dashboard needs.
- The output topic is auto-named `TURNSTILE_SUMMARY` (uppercase).
- The consumer reads this table to show `num_turnstile_entries` per station.

---

### Step 6 — Kafka Consumers & Web Dashboard

**Goal:** Read all the data and display it in a Tornado web app.

#### 6a. Base Consumer (`consumers/consumer.py`)

```python
class KafkaConsumer:
    def __init__(self, topic_name_pattern, message_handler, is_avro=True,
                 offset_earliest=False):
        self.broker_properties = {
            "bootstrap.servers": BROKER_URL,
            "group.id": f"cta-consumer-group-{topic_name_pattern}",
            "auto.offset.reset": "earliest" if offset_earliest else "latest",
        }

        if is_avro:
            self.consumer = AvroConsumer(self.broker_properties)
        else:
            self.consumer = Consumer(self.broker_properties)

        self.consumer.subscribe([topic_name_pattern], on_assign=self.on_assign)

    def on_assign(self, consumer, partitions):
        if self.offset_earliest:
            for p in partitions:
                p.offset = confluent_kafka.OFFSET_BEGINNING
        consumer.assign(partitions)

    def _consume(self):
        message = self.consumer.poll(self.consume_timeout)
        if message is None:
            return 0
        if message.error():
            return 0
        self.message_handler(message)
        return 1
```

**Key learnings:**
- `is_avro=True` → use `AvroConsumer` (auto-deserializes with Schema Registry).
- `is_avro=False` → use plain `Consumer` (for JSON topics like Faust output and KSQL).
- `offset_earliest=True` means "read from the beginning" — needed for station data so all stations appear.
- The `on_assign` callback sets `OFFSET_BEGINNING` when we need historical data.
- `topic_name_pattern` can be a regex like `^org.chicago.cta.station.arrivals.` to subscribe to all station topics at once.

#### 6b. Web Server (`consumers/server.py`)

Four consumers are created:

| Consumer | Topic | Purpose |
|---|---|---|
| Weather | `org.chicago.cta.weather.v1` | Update temperature/status |
| Stations | `org.chicago.cta.stations.table.v1` | Load station list (from Faust) |
| Arrivals | `^org.chicago.cta.station.arrivals.` | Track train positions |
| Turnstile | `TURNSTILE_SUMMARY` | Show entry counts (from KSQL) |

Tornado spawns each consumer as an async callback, and serves the HTML dashboard on port 3000.

---

## 6. How to Run

### Recommended: Docker startup (single command)
```bash
cd "/Users/gourbera/Udacity/Data Streaming/project-v1"
./docker-startup.sh
```

This script:
- starts all services with Docker Compose,
- waits for Kafka, Schema Registry, KSQL, and Faust readiness,
- validates that the dashboard is reachable.

Open `http://localhost:3000` after startup completes.

### Manual Docker startup (equivalent)
```bash
cd "/Users/gourbera/Udacity/Data Streaming/project-v1"
docker compose down --volumes --remove-orphans
docker compose up --build -d
```

### Verify runtime
```bash
docker compose ps
docker compose logs --tail=120 producer
docker compose logs --tail=120 faust
docker compose logs --tail=120 consumer
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) as stations_count from stations;"
```

### Stop everything
```bash
cd "/Users/gourbera/Udacity/Data Streaming/project-v1"
docker compose down
```

---

## 7. Topic Naming Convention

All topics follow `org.chicago.cta.<entity>[.<detail>]`:

| Topic | Source | Format |
|---|---|---|
| `org.chicago.cta.station.arrivals.{name}` | Station Producer | Avro |
| `org.chicago.cta.turnstile` | Turnstile Producer | Avro |
| `org.chicago.cta.weather.v1` | Weather / REST Proxy | Avro |
| `org.chicago.cta.stations` | Kafka Connect (PostgreSQL) | JSON |
| `org.chicago.cta.stations.table.v1` | Faust Stream | JSON |
| `TURNSTILE_SUMMARY` | KSQL Table | JSON |

---

## 8. Avro Schemas Explained

### arrival_key.json
```json
{"fields": [{"name": "timestamp", "type": "long"}]}
```

### arrival_value.json
```json
{
  "fields": [
    {"name": "station_id",      "type": "int"},
    {"name": "train_id",        "type": "string"},
    {"name": "direction",       "type": "string"},
    {"name": "line",            "type": "string"},
    {"name": "train_status",    "type": "string"},
    {"name": "prev_station_id", "type": ["null", "int"]},
    {"name": "prev_direction",  "type": ["null", "string"]}
  ]
}
```
Note: `["null", "int"]` is an Avro **union type** — the field can be null (first arrival has no previous station).

### turnstile_value.json
```json
{
  "fields": [
    {"name": "station_id",    "type": "int"},
    {"name": "station_name",  "type": "string"},
    {"name": "line",          "type": "string"}
  ]
}
```

### weather_value.json
```json
{
  "fields": [
    {"name": "temperature", "type": "double"},
    {"name": "status",      "type": "string"}
  ]
}
```

---

## 9. Environment Variables & Security

All configuration is managed with **python-dotenv** and **Docker environment variables** — no hardcoded credentials.

### Root `.env` (read by docker-compose)
```
POSTGRES_USER=<your_user>
POSTGRES_PASSWORD=<your_password>
POSTGRES_DB=cta
```

Create it from:
```bash
cp .env.example .env
```

### `producers/.env`
```
KAFKA_BROKER_URL=PLAINTEXT://localhost:9092
SCHEMA_REGISTRY_URL=http://localhost:8081
KAFKA_CONNECT_URL=http://localhost:8083/connectors
REST_PROXY_URL=http://localhost:8082
POSTGRES_USER=<your_user>
POSTGRES_PASSWORD=<your_password>
POSTGRES_DB=cta
```

### `consumers/.env`
```
KAFKA_BROKER_URL=PLAINTEXT://localhost:9092
SCHEMA_REGISTRY_URL=http://localhost:8081
KSQL_URL=http://localhost:8088
SERVER_PORT=3000
```

### How it works in docker-compose.yml
```yaml
# ${VAR:?error} requires a value from environment or .env
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}
```

### How it works in Python
```python
from dotenv import load_dotenv
import os

load_dotenv()  # reads .env file
BROKER_URL = os.getenv("KAFKA_BROKER_URL", "PLAINTEXT://localhost:9092")
```

### For production
Override via real environment variables or a secrets manager:
```bash
export POSTGRES_PASSWORD="strong_production_password"
docker compose up -d
```

---

## 10. Verification & Debugging

### Check services
```bash
docker compose ps
```

### List all Kafka topics
```bash
docker compose exec kafka0 kafka-topics --list --bootstrap-server localhost:9092
```

### Read messages from a topic
```bash
# Weather
docker compose exec kafka0 kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic org.chicago.cta.weather.v1 \
  --from-beginning --max-messages 3

# Station arrivals
docker compose exec kafka0 kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic org.chicago.cta.station.arrivals.clark_and_lake \
  --from-beginning --max-messages 5
```

### Check Schema Registry
```bash
curl http://localhost:8081/subjects
```

### Check Kafka Connect
```bash
curl http://localhost:8083/connectors
```

### Check KSQL
```bash
docker compose exec ksql ksql http://localhost:8088
# then: SHOW TABLES; SHOW STREAMS;
```

### Check PostgreSQL
```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT * FROM stations LIMIT 5;"
```

### Common issues

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'imp'` when running Faust | Python 3.13+ is not supported. Use Python 3.11 or 3.12, or run in Docker |
| `fatal error: 'librdkafka/rdkafka.h' file not found` | Install librdkafka: `brew install librdkafka`, then reinstall with: `CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" pip install --no-cache-dir confluent-kafka==1.9.2` |
| `command not found: faust` | Dependencies not installed. Run `pip install -r requirements.txt` in consumers directory |
| `ConnectionRefused` to REST Proxy from producer | Inside Docker use `rest-proxy:8082`, on host use `localhost:8082` |
| `TURNSTILE_SUMMARY` not found | Run `python ksql.py` first |
| `stations.table.v1` not found | Ensure the `faust` container is healthy: `docker compose ps` and `docker compose logs faust` |
| Weather crash `ConnectionError` | Ensure `REST_PROXY_URL` env var points to correct host |
| Connector fails with auth error | Check `POSTGRES_USER` / `POSTGRES_PASSWORD` env vars |

---

## 11. Rubric Checklist

### Kafka Producer ✅
- [x] Topics created with settings (LZ4 compression, partitions, cleanup policy)
- [x] Messages continuously produced for arrivals and turnstiles
- [x] Avro schemas registered in Schema Registry

### Kafka REST Proxy ✅
- [x] Weather messages visible in `org.chicago.cta.weather.v1`
- [x] `Content-Type: application/vnd.kafka.avro.v2+json` header used
- [x] Avro key and value schemas included in POST body

### Kafka Connect ✅
- [x] All stations from PostgreSQL visible in `org.chicago.cta.stations`
- [x] JSON converters configured
- [x] Incrementing mode with `stop_id`

### Faust Streams ✅
- [x] Consumer group created on stations topic
- [x] Station → TransformedStation (boolean flags → string line)
- [x] Every station ID present in output topic

### KSQL ✅
- [x] `TURNSTILE` stream created
- [x] `TURNSTILE_SUMMARY` table with COUNT by station_id

### Kafka Consumers ✅
- [x] Stations, status, and weather appear in dashboard
- [x] All Blue, Green, and Red line stations visible

### Standout Features ✅
- [x] Shared base `Producer` class to reduce duplication
- [x] Manual topic creation (not auto-create) with optimal settings
- [x] Consistent `org.chicago.cta.*` naming convention
- [x] Environment variable configuration with dotenv
- [x] Docker containerization with docker-compose

---

## 12. Key Learnings

### Kafka Fundamentals
1. **Topics are append-only logs.** Producers write, consumers read, nobody edits.
2. **Partitions give parallelism.** More partitions = more consumers can read concurrently.
3. **Consumer groups balance load.** Each partition goes to one consumer in the group.
4. **Offsets let consumers resume.** If a consumer restarts, it picks up where it left off.

### Serialization
5. **Avro is compact and schema-enforced.** Unlike JSON, the schema is stored once in the Registry, not in every message.
6. **Schema Registry is the single source of truth.** Producers register schemas, consumers fetch them.
7. **Union types `["null", "int"]` handle optional fields** in Avro.

### REST Proxy
8. **Content-Type matters.** `application/vnd.kafka.avro.v2+json` tells REST Proxy to use Avro.
9. **Schemas are embedded in the HTTP body** as JSON-encoded strings.

### Kafka Connect
10. **No code needed for simple ETL.** Just configure a JSON payload via REST API.
11. **Incrementing mode** efficiently loads only new rows.
12. **`topic.prefix`** controls the output topic name.

### Stream Processing
13. **Faust = Python-native stream processing.** No JVM required.
14. **KSQL = SQL over streams.** Perfect for aggregations like COUNT, SUM, AVG.
15. **Streams are unbounded.** Tables are the latest state per key.

### Consumers
16. **`AvroConsumer` auto-deserializes** using the Schema Registry.
17. **`offset_earliest` + `on_assign` callback** lets you replay all historical data.
18. **Regex subscriptions** (`^org.chicago.cta.station.arrivals.`) subscribe to many topics at once.

### Architecture
19. **Separate concerns.** Producers, stream processors, and consumers are independent services.
20. **Environment variables keep secrets out of code.** Use `.env` for dev, secrets managers for prod.
21. **Docker Compose orchestrates everything.** One `docker-compose up -d` spins up the whole platform.

---

*This is the single reference document for the CTA Data Streaming project.  Keep it alongside `project.md` (the original rubric/directions) and you have everything you need.*
