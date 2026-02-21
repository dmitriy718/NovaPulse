from __future__ import annotations

import asyncio
from typing import Any, Dict, Literal, Optional

import httpx

from src.core.logger import get_logger

logger = get_logger("alpaca_client")


class AlpacaClient:
    """Minimal async Alpaca trading client (orders + close position)."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://paper-api.alpaca.markets",
        timeout_seconds: float = 20.0,
    ):
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.base_url = (base_url or "https://paper-api.alpaca.markets").rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def initialize(self) -> None:
        if self._client is None:
            headers = {
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
                "Content-Type": "application/json",
            }
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def submit_market_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        asset_class: Literal["equity", "option"] = "equity",
        time_in_force: str = "day",
        wait_fill_seconds: float = 8.0,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if self._client is None:
            await self.initialize()
        symbol_raw = str(symbol or "").strip().upper()
        if asset_class == "option" and symbol_raw.startswith("O:"):
            symbol_raw = symbol_raw[2:]
        payload = {
            "symbol": symbol_raw,
            "qty": str(max(float(qty), 0.0)),
            "side": side,
            "type": "market",
            "time_in_force": time_in_force,
        }
        orders_path = "/v2/options/orders" if asset_class == "option" else "/v2/orders"
        try:
            resp = await self._client.post(f"{self.base_url}{orders_path}", json=payload)
            resp.raise_for_status()
            order = resp.json()
            if self._is_filled(order):
                return order

            # Market orders are usually quick, but not always synchronous.
            # Poll briefly so internal state uses filled qty/price when available.
            oid = str(order.get("id", "")).strip()
            if oid and wait_fill_seconds > 0:
                deadline = asyncio.get_running_loop().time() + float(wait_fill_seconds)
                while asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.5)
                    fresh = await self.get_order(oid)
                    if fresh:
                        order = fresh
                    if self._is_filled(order):
                        break
            return order
        except Exception as e:
            logger.warning(
                "Alpaca submit order failed",
                symbol=symbol_raw,
                asset_class=asset_class,
                side=side,
                qty=qty,
                error=repr(e),
            )
            return None

    async def close_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if self._client is None:
            await self.initialize()
        try:
            resp = await self._client.delete(f"{self.base_url}/v2/positions/{symbol.upper()}")
            if resp.status_code in (200, 202):
                return resp.json()
            if resp.status_code == 404:
                return {"status": "no_position"}
            logger.warning(
                "Alpaca close position rejected",
                symbol=symbol,
                status_code=resp.status_code,
                body=resp.text[:200],
            )
            return None
        except Exception as e:
            logger.warning("Alpaca close position failed", symbol=symbol, error=repr(e))
            return None

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if self._client is None:
            await self.initialize()
        oid = (order_id or "").strip()
        if not oid:
            return None
        try:
            resp = await self._client.get(f"{self.base_url}/v2/orders/{oid}")
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None

    async def list_open_positions(self) -> list[Dict[str, Any]]:
        """Return currently open broker positions."""
        if not self.enabled:
            return []
        if self._client is None:
            await self.initialize()
        try:
            resp = await self._client.get(f"{self.base_url}/v2/positions")
            if resp.status_code == 200:
                payload = resp.json()
                return payload if isinstance(payload, list) else []
            logger.warning(
                "Alpaca list positions failed",
                status_code=resp.status_code,
                body=resp.text[:200],
            )
            return []
        except Exception as e:
            logger.warning("Alpaca list positions exception", error=repr(e))
            return []

    @staticmethod
    def _is_filled(order: Dict[str, Any]) -> bool:
        try:
            status = str(order.get("status", "")).strip().lower()
            filled_qty = float(order.get("filled_qty", 0.0) or 0.0)
            return status == "filled" and filled_qty > 0
        except Exception:
            return False
