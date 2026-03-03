"""Defines trends calculations for stations"""
import logging
import os

import faust
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Faust Record schemas
# ---------------------------------------------------------------------------

class Station(faust.Record):
    """Raw station record ingested from the Kafka Connect topic"""

    stop_id: int
    direction_id: str
    stop_name: str
    station_name: str
    station_descriptive_name: str
    station_id: int
    order: int
    red: bool
    blue: bool
    green: bool


class TransformedStation(faust.Record):
    """Cleaned station record written to the output topic"""

    station_id: int
    station_name: str
    order: int
    line: str


# ---------------------------------------------------------------------------
# Faust application and topics
# ---------------------------------------------------------------------------

_broker_url = os.getenv("KAFKA_BROKER_URL", "PLAINTEXT://localhost:9092")
_faust_broker = _broker_url.replace("PLAINTEXT://", "kafka://")

app = faust.App("stations-stream", broker=_faust_broker, store="memory://")

topic = app.topic("org.chicago.cta.stations", value_type=Station)
out_topic = app.topic("org.chicago.cta.stations.table.v1", partitions=1)

table = app.Table(
    "org.chicago.cta.stations.table.v1",
    default=TransformedStation,
    partitions=1,
    changelog_topic=out_topic,
)


# ---------------------------------------------------------------------------
# Stream processor
# ---------------------------------------------------------------------------

@app.agent(topic)
async def process_stations(stations):
    """Transform incoming Station records into TransformedStation records"""
    async for station in stations:
        if station.red:
            line = "red"
        elif station.blue:
            line = "blue"
        elif station.green:
            line = "green"
        else:
            line = "unknown"

        transformed = TransformedStation(
            station_id=station.station_id,
            station_name=station.station_name,
            order=station.order,
            line=line,
        )
        table[station.station_id] = transformed


if __name__ == "__main__":
    app.main()
