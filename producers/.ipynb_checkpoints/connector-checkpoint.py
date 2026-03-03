"""Configures a Kafka Connector for Postgres Station data"""
import os
import json
import logging
import requests
from dotenv import load_dotenv
from confluent_kafka.admin import AdminClient, NewTopic


load_dotenv()
logger = logging.getLogger(__name__)


BROKER_URL = os.getenv("KAFKA_BROKER_URL", "PLAINTEXT://localhost:9092")
KAFKA_CONNECT_URL = os.getenv("KAFKA_CONNECT_URL", "http://localhost:8083/connectors")
CONNECTOR_NAME = "stations"
CONNECTOR_TOPIC = "org.chicago.cta.stations"

def _create_connector_topic():
    """Pre-creates the Kafka Connect stations topic with optimal settings"""
    client = AdminClient({"bootstrap.servers": BROKER_URL})

    topic = NewTopic(
        topic=CONNECTOR_TOPIC,
        num_partitions=1,
        replication_factor=1,
        config={
            "cleanup.policy": "compact",
            "compression.type": "lz4",
            "delete.retention.ms": "100",
            "file.delete.delay.ms": "100",
        }
    )

    futures = client.create_topics([topic])

    for topic_name, future in futures.items():
        try:
            future.result()
            logger.info(f"topic created: {topic_name}")
        except Exception as e:
            logger.info(f"topic creation failed for {topic_name}: {e}")


def configure_connector():
    """Starts and configures the Kafka Connect connector"""
    logging.debug("creating or updating kafka connect connector...")

    resp = requests.get(f"{KAFKA_CONNECT_URL}/{CONNECTOR_NAME}")
    if resp.status_code == 200:
        logging.debug("connector already created skipping recreation")
        return

    # Pre-create the topic
    _create_connector_topic()

    # Complete Kafka Connect Config
    # Uses JDBC Source Connector to connect to Postgres and load the stations table
    # Using incrementing mode with stop_id as the incrementing column
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
                "connection.url": "jdbc:postgresql://postgres:5432/cta",
                "connection.user": os.getenv("POSTGRES_USER", "cta_admin"),
                "connection.password": os.getenv("POSTGRES_PASSWORD", "chicago"),
                "table.whitelist": "stations",
                "mode": "incrementing",
                "incrementing.column.name": "stop_id",
                "topic.prefix": "org.chicago.cta.",
                "poll.interval.ms": "60000",  # Poll every 60 seconds (not too often)
            }
        }),
    )

    # Ensure a healthy response was given
    try:
        resp.raise_for_status()
        logging.info("connector created successfully")
    except Exception as e:
        logging.error(f"failed to create connector: {e}")
        logging.error(f"response: {resp.text}")


if __name__ == "__main__":
    configure_connector()
