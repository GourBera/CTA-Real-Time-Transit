"""Configures a Kafka Connector for Postgres Station data"""
import json
import logging
import os

import requests
from confluent_kafka.admin import AdminClient, NewTopic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BROKER_URL = os.getenv("KAFKA_BROKER_URL", "PLAINTEXT://localhost:9092")
KAFKA_CONNECT_URL = os.getenv("KAFKA_CONNECT_URL", "http://localhost:8083/connectors")
CONNECTOR_NAME = "stations"
CONNECTOR_TOPIC = "org.chicago.cta.stations"


def _create_connector_topic():
    """Pre-creates the Kafka Connect stations topic with optimal settings
    instead of relying on Kafka auto-create (standout feature)."""
    client = AdminClient({"bootstrap.servers": BROKER_URL})
    topic_metadata = client.list_topics(timeout=5)
    existing = {t.topic for t in topic_metadata.topics.values()}
    if CONNECTOR_TOPIC in existing:
        logger.debug("connector topic already exists: %s", CONNECTOR_TOPIC)
        return

    futures = client.create_topics(
        [
            NewTopic(
                topic=CONNECTOR_TOPIC,
                num_partitions=1,
                replication_factor=1,
                config={
                    "cleanup.policy": "compact",
                    "compression.type": "lz4",
                },
            )
        ]
    )
    for topic, future in futures.items():
        try:
            future.result()
            logger.info("connector topic created: %s", topic)
        except Exception as e:
            logger.warning("failed to create connector topic %s: %s", topic, e)


def configure_connector():
    """Starts and configures the Kafka Connect connector"""
    logging.debug("creating or updating kafka connect connector...")

    resp = requests.get(f"{KAFKA_CONNECT_URL}/{CONNECTOR_NAME}")
    if resp.status_code == 200:
        logging.debug("connector already created skipping recreation")
        return

    _create_connector_topic()

    resp = requests.post(
        KAFKA_CONNECT_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "name": CONNECTOR_NAME,
            "config": {
                "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
                "key.converter": "org.apache.kafka.connect.json.JsonConverter",
                "key.converter.schemas.enable": "false",
                "value.converter": "org.apache.kafka.connect.json.JsonConverter",
                "value.converter.schemas.enable": "false",
                "batch.max.rows": "500",
                "connection.url": f"jdbc:postgresql://postgres:5432/{os.getenv('POSTGRES_DB', 'cta')}",
                "connection.user": os.environ["POSTGRES_USER"],
                "connection.password": os.environ["POSTGRES_PASSWORD"],
                "table.whitelist": "stations",
                "mode": "incrementing",
                "incrementing.column.name": "stop_id",
                "topic.prefix": "org.chicago.cta.",
                "poll.interval.ms": "60000",
            }
        }),
    )

    # Ensure a healthy response was given
    try:
        resp.raise_for_status()
        logging.debug("connector created successfully")
    except Exception:
        logging.error("failed to create connector: %s %s", resp.status_code, resp.text)


if __name__ == "__main__":
    configure_connector()
