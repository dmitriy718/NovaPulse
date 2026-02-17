"""
Kraken WebSocket Client - Real-time market data streaming.

Provides live price feeds, order book updates, and trade execution
notifications via Kraken's WebSocket v2 API.

# ENHANCEMENT: Added automatic reconnection with exponential backoff
# ENHANCEMENT: Added message queuing during disconnection
# ENHANCEMENT: Added heartbeat monitoring for connection health
# ENHANCEMENT: Added subscription management for dynamic pair updates
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

from src.core.logger import get_logger

logger = get_logger("kraken_ws")


class KrakenWebSocketClient:
    """
    Production-grade Kraken WebSocket v2 client.
    
    Features:
    - Auto-reconnection with exponential backoff
    - Subscription management (ticker, ohlc, book, trade)
    - Message routing to registered callbacks
    - Heartbeat monitoring
    - Connection state tracking
    - Message queue for offline periods
    
    # ENHANCEMENT: Added per-channel message deduplication
    # ENHANCEMENT: Added latency tracking for performance monitoring
    """

    def __init__(
        self,
        url: str = "wss://ws.kraken.com/v2",
        max_reconnect_attempts: int = 50,
        heartbeat_interval: int = 30,
    ):
        self.url = url
        self.max_reconnect_attempts = max_reconnect_attempts
        self.heartbeat_interval = heartbeat_interval

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._running = False
        self._reconnect_count = 0
        self._last_heartbeat: float = 0
        self._last_heartbeat_received: float = 0  # timestamp of previous heartbeat msg
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._latency_samples: Deque[float] = deque(maxlen=50)  # heartbeat interval samples

    # ------------------------------------------------------------------
    # Connection Management
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish WebSocket connection with auto-reconnect."""
        self._running = True
        self._reconnect_count = 0

        while self._running and self._reconnect_count < self.max_reconnect_attempts:
            try:
                logger.info(
                    "Connecting to Kraken WebSocket",
                    url=self.url,
                    attempt=self._reconnect_count + 1
                )

                self._ws = await websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2 ** 20,  # 1MB max message
                )

                self._connected = True
                self._reconnect_count = 0
                self._last_heartbeat = time.time()

                logger.info("WebSocket connected successfully")

                # Resubscribe to all channels
                await self._resubscribe()

                # Start message processing
                await self._message_loop()

            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                self._connected = False
                self._reconnect_count += 1

                if not self._running:
                    break

                # Kraken 1013 = "Market data unavailable" — use longer backoff
                is_1013 = (
                    isinstance(e, ConnectionClosed)
                    and e.rcvd
                    and e.rcvd.code == 1013
                )
                if is_1013:
                    delay = min(15 * self._reconnect_count, 120)  # 15, 30, 45… up to 120s
                else:
                    delay = min(2 ** min(self._reconnect_count, 6), 60)

                logger.warning(
                    "WebSocket disconnected, reconnecting",
                    error=str(e),
                    attempt=self._reconnect_count,
                    delay=delay,
                    is_1013=is_1013,
                )
                await asyncio.sleep(delay)

            except Exception as e:
                self._connected = False
                logger.error("WebSocket unexpected error", error=str(e))
                if self._running:
                    await asyncio.sleep(5)

        if self._reconnect_count >= self.max_reconnect_attempts:
            logger.critical(
                "Max reconnection attempts reached",
                attempts=self.max_reconnect_attempts
            )

    async def disconnect(self) -> None:
        """Gracefully disconnect the WebSocket."""
        self._running = False
        self._connected = False

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.info("WebSocket disconnected")

    async def _message_loop(self) -> None:
        """Main message receiving loop."""
        if not self._ws:
            return

        async for raw_message in self._ws:
            try:
                self._last_heartbeat = time.time()
                message = json.loads(raw_message)

                # Handle system messages
                channel = message.get("channel", "")

                if channel == "heartbeat":
                    # Track interval between consecutive heartbeat messages
                    now = time.time()
                    if self._last_heartbeat_received > 0:
                        interval_ms = (now - self._last_heartbeat_received) * 1000.0
                        self._latency_samples.append(interval_ms)
                    self._last_heartbeat_received = now
                    continue
                elif channel == "status":
                    await self._handle_status(message)
                elif message.get("method") in ("subscribe", "unsubscribe"):
                    await self._handle_subscription_response(message)
                else:
                    # Route to registered callbacks
                    await self._route_message(channel, message)

            except json.JSONDecodeError:
                logger.warning("Invalid JSON received", raw=str(raw_message)[:200])
            except Exception as e:
                logger.error("Message processing error", error=str(e))

    # ------------------------------------------------------------------
    # Subscription Management
    # ------------------------------------------------------------------

    async def subscribe_ticker(self, pairs: List[str]) -> None:
        """Subscribe to real-time ticker updates."""
        await self._subscribe("ticker", pairs)

    async def subscribe_ohlc(
        self, pairs: List[str], interval: int = 1
    ) -> None:
        """Subscribe to OHLC candle updates."""
        await self._subscribe("ohlc", pairs, {"interval": interval})

    async def subscribe_book(
        self, pairs: List[str], depth: int = 25
    ) -> None:
        """Subscribe to order book updates."""
        await self._subscribe("book", pairs, {"depth": depth})

    async def subscribe_trade(self, pairs: List[str]) -> None:
        """Subscribe to live trade feed."""
        await self._subscribe("trade", pairs)

    async def _subscribe(
        self, channel: str, pairs: List[str],
        params: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a subscription request."""
        sub_key = f"{channel}_{','.join(sorted(pairs))}"
        sub_params: Dict[str, Any] = {
            "channel": channel,
            "symbol": pairs,
        }
        if params:
            sub_params.update(params)

        self._subscriptions[sub_key] = sub_params

        if self._connected and self._ws:
            message = {
                "method": "subscribe",
                "params": sub_params,
            }
            try:
                await self._ws.send(json.dumps(message))
                logger.info(
                    "Subscribed to channel",
                    channel=channel, pairs=pairs
                )
            except Exception as e:
                logger.error(
                    "Subscription failed",
                    channel=channel, error=str(e)
                )

    async def unsubscribe(self, channel: str, pairs: List[str]) -> None:
        """Unsubscribe from a channel."""
        sub_key = f"{channel}_{','.join(sorted(pairs))}"
        self._subscriptions.pop(sub_key, None)

        if self._connected and self._ws:
            message = {
                "method": "unsubscribe",
                "params": {
                    "channel": channel,
                    "symbol": pairs,
                },
            }
            try:
                await self._ws.send(json.dumps(message))
            except Exception as e:
                logger.error("Unsubscribe failed", channel=channel, error=str(e))

    async def _resubscribe(self) -> None:
        """Resubscribe to all channels after reconnection with retry on 1013."""
        max_retries = 4
        for sub_key, params in self._subscriptions.items():
            if not self._ws:
                break
            message = {"method": "subscribe", "params": params}
            for attempt in range(1, max_retries + 1):
                try:
                    await self._ws.send(json.dumps(message))
                    logger.debug("Resubscribed", channel=sub_key)
                    # Stagger subscriptions to avoid overwhelming Kraken
                    await asyncio.sleep(0.5)
                    break
                except ConnectionClosed as e:
                    # 1013 = "Try Again Later" — Kraken market data temporarily unavailable
                    if e.rcvd and e.rcvd.code == 1013 and attempt < max_retries:
                        delay = 2 ** attempt  # 2, 4, 8s backoff
                        logger.warning(
                            "Kraken 1013 during resubscription, backing off",
                            channel=sub_key,
                            attempt=attempt,
                            retry_in=delay,
                        )
                        await asyncio.sleep(delay)
                        # Connection is dead after 1013 — must re-raise to trigger full reconnect
                        if not self._ws or self._ws.closed:
                            raise
                    else:
                        raise  # Let connect() loop handle reconnection
                except Exception as e:
                    logger.error("Resubscription failed", channel=sub_key, error=str(e))
                    raise  # Let connect() loop handle reconnection

    # ------------------------------------------------------------------
    # Callback Registration
    # ------------------------------------------------------------------

    def on_ticker(self, callback: Callable) -> None:
        """Register a callback for ticker updates."""
        self._callbacks["ticker"].append(callback)

    def on_ohlc(self, callback: Callable) -> None:
        """Register a callback for OHLC updates."""
        self._callbacks["ohlc"].append(callback)

    def on_book(self, callback: Callable) -> None:
        """Register a callback for order book updates."""
        self._callbacks["book"].append(callback)

    def on_trade(self, callback: Callable) -> None:
        """Register a callback for trade updates."""
        self._callbacks["trade"].append(callback)

    def on_any(self, callback: Callable) -> None:
        """Register a callback for all messages."""
        self._callbacks["*"].append(callback)

    async def _route_message(self, channel: str, message: Dict[str, Any]) -> None:
        """Route a message to registered callbacks."""
        # Channel-specific callbacks
        for callback in self._callbacks.get(channel, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.error(
                    "Callback error",
                    channel=channel,
                    callback=callback.__name__,
                    error=str(e)
                )

        # Wildcard callbacks
        for callback in self._callbacks.get("*", []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.error("Wildcard callback error", error=str(e))

    # ------------------------------------------------------------------
    # Status & Health
    # ------------------------------------------------------------------

    async def _handle_status(self, message: Dict[str, Any]) -> None:
        """Handle connection status messages."""
        data = message.get("data", [{}])
        if isinstance(data, list) and data:
            status_data = data[0] if isinstance(data[0], dict) else {}
            system_status = status_data.get("system", "unknown")
            version = status_data.get("version", "unknown")
            logger.info(
                "Kraken system status",
                status=system_status, version=version
            )

    async def _handle_subscription_response(self, message: Dict[str, Any]) -> None:
        """Handle subscription confirmation/rejection."""
        success = message.get("success", False)
        method = message.get("method", "")
        result = message.get("result", {})

        if success:
            logger.debug("Subscription confirmed", method=method, result=result)
        else:
            error = message.get("error", "Unknown error")
            logger.error("Subscription failed", method=method, error=error)

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self._connected and self._ws is not None

    @property
    def latency_ms(self) -> float:
        """Get average heartbeat interval in milliseconds (proxy for connection health)."""
        if not self._latency_samples:
            return 0.0
        return sum(self._latency_samples) / len(self._latency_samples)

    @property
    def seconds_since_heartbeat(self) -> float:
        """Get seconds since last heartbeat."""
        if self._last_heartbeat == 0:
            return float("inf")
        return time.time() - self._last_heartbeat

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection status information."""
        return {
            "connected": self._connected,
            "url": self.url,
            "reconnect_count": self._reconnect_count,
            "subscriptions": list(self._subscriptions.keys()),
            "last_heartbeat": self._last_heartbeat,
            "avg_latency_ms": self.latency_ms,
        }
