"""Defines a Tornado Server that consumes Kafka Event data for display"""
import logging
import logging.config
import os
from pathlib import Path

import tornado.ioloop
import tornado.template
import tornado.web
from dotenv import load_dotenv

load_dotenv()

# Import logging before models to ensure configuration is picked up
logging.config.fileConfig(f"{Path(__file__).parents[0]}/logging.ini")

import ksql  # noqa: E402
import topic_check  # noqa: E402
from consumer import KafkaConsumer  # noqa: E402
from models import Lines, Weather  # noqa: E402

logger = logging.getLogger(__name__)


class MainHandler(tornado.web.RequestHandler):
    """Defines a web request handler class"""

    template_dir = tornado.template.Loader(f"{Path(__file__).parents[0]}/templates")
    template = template_dir.load("status.html")

    def initialize(self, weather, lines):
        """Initializes the handler with required configuration"""
        self.weather = weather
        self.lines = lines

    def get(self):
        """Responds to get requests"""
        logging.debug("rendering and writing handler template")
        self.write(
            MainHandler.template.generate(weather=self.weather, lines=self.lines)
        )


def run_server():
    """Runs the Tornado Server and begins Kafka consumption"""
    # Get port from environment or use default
    port = int(os.getenv("SERVER_PORT", "3000"))

    # Configure KSQL
    ksql.execute_statement()
    if topic_check.topic_exists("TURNSTILE_SUMMARY") is False:
        logger.fatal(
            "Ensure that the KSQL Command has run successfully before running the web server!"
        )
        exit(1)
    if topic_check.topic_exists("org.chicago.cta.stations.table.v1") is False:
        logger.fatal(
            "Ensure that Faust Streaming is running successfully before running the web server!"
        )
        exit(1)

    weather_model = Weather()
    lines = Lines()

    application = tornado.web.Application(
        [(r"/", MainHandler, {"weather": weather_model, "lines": lines})]
    )
    application.listen(port)

    # Build kafka consumers
    consumers = [
        KafkaConsumer(
            "org.chicago.cta.weather.v1",
            weather_model.process_message,
            offset_earliest=True,
        ),
        KafkaConsumer(
            "org.chicago.cta.stations.table.v1",
            lines.process_message,
            offset_earliest=True,
            is_avro=False,
        ),
        KafkaConsumer(
            "^org.chicago.cta.station.arrivals.",
            lines.process_message,
            offset_earliest=True,
        ),
        KafkaConsumer(
            "TURNSTILE_SUMMARY",
            lines.process_message,
            offset_earliest=True,
            is_avro=False,
        ),
    ]

    try:
        logger.info(
            f"Click on the Preview button to see the Transit Status Page. "
            f"If running locally - Open a web browser to http://localhost:{port} to see the Transit Status Page"
        )
        for consumer in consumers:
            tornado.ioloop.IOLoop.current().spawn_callback(consumer.consume)

        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt as e:
        logger.info("shutting down server")
        tornado.ioloop.IOLoop.current().stop()
        for consumer in consumers:
            consumer.close()


if __name__ == "__main__":
    run_server()
