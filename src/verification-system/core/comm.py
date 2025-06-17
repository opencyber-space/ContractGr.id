import asyncio
import json
import os
import logging
from nats.aio.client import Client as NATS
from typing import Dict


class NATSClient:
    def __init__(self):

        self.server = os.getenv("NATS_SERVER_URL")

        self.nc = NATS()
        self.connected = False
        self.logger = logging.getLogger("NATSClient")

    async def connect(self):
        if not self.connected:
            try:
                await self.nc.connect(servers=[self.servers])
                self.connected = True
                self.logger.info(f"Connected to NATS at {self.servers}")
            except Exception as e:
                self.logger.error(f"Failed to connect to NATS: {e}")
                raise

    async def _publish_async(self, subject: str, message: Dict):
        try:
            await self.connect()
            payload = json.dumps(message).encode()
            await self.nc.publish(subject, payload)
            self.logger.info(f"Published message to {subject}")
        except Exception as e:
            self.logger.error(f"Error publishing to {subject}: {e}")

    def publish(self, subject: str, message: Dict):
        asyncio.run(self._publish_async(subject, message))
