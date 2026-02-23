"""Dynamic crypto pair universe scanner.

Fetches top coins from CoinGecko by volume/market cap, cross-references
against the exchange's available pairs, applies filters, merges with
pinned pairs, and caches the result.  Refreshes periodically (24/7).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx

from src.core.logger import get_logger

logger = get_logger("crypto_universe")


class CryptoUniverseScanner:
    """Build and cache a dynamic crypto trading pair universe."""

    def __init__(
        self,
        rest_client: Any,
        config: Any,
        pinned_pairs: List[str],
        coingecko_api_key: str = "",
        exchange_name: str = "kraken",
    ) -> None:
        self._rest_client = rest_client
        self._cfg = config
        self._exchange_name = exchange_name.lower()
        self._coingecko_api_key = coingecko_api_key

        self._pinned: List[str] = [
            p.strip().upper() for p in pinned_pairs if p and p.strip()
        ]
        self._cached_pairs: List[str] = list(self._pinned)
        self._exchange_pair_catalog: Dict[str, str] = {}  # canonical -> exchange native
        self._coingecko_id_map: Dict[str, str] = {}       # canonical -> coingecko id
        self._cached_market_data: Dict[str, Dict[str, Any]] = {}
        self._last_refresh_ts: float = 0.0
        self._last_request_ts: float = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def pairs(self) -> List[str]:
        """Current universe. Returns pinned pairs if never refreshed."""
        return list(self._cached_pairs)

    @property
    def exchange_pair_map(self) -> Dict[str, str]:
        """Dynamic mapping from canonical pair to exchange-native pair."""
        return dict(self._exchange_pair_catalog)

    @property
    def coingecko_id_map(self) -> Dict[str, str]:
        """Dynamic mapping from canonical pair to CoinGecko ID."""
        return dict(self._coingecko_id_map)

    @property
    def cached_market_data(self) -> Dict[str, Dict[str, Any]]:
        """CoinGecko market data keyed by pair."""
        return self._cached_market_data

    async def refresh(self) -> List[str]:
        """Full universe rebuild: CoinGecko fetch -> cross-ref -> filter -> merge."""
        async with self._lock:
            return await self._do_refresh()

    async def build_exchange_pair_catalog(self) -> None:
        """Fetch all exchange pairs and build the canonical mapping. Call once at startup."""
        try:
            if self._exchange_name == "coinbase":
                await self._build_catalog_coinbase()
            else:
                await self._build_catalog_kraken()
            logger.info(
                "Exchange pair catalog built",
                exchange=self._exchange_name,
                count=len(self._exchange_pair_catalog),
            )
        except Exception as e:
            logger.warning("Failed to build exchange pair catalog", error=repr(e))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _do_refresh(self) -> List[str]:
        logger.info("Crypto universe refresh starting")
        t0 = time.monotonic()

        # Step 1: Fetch top coins from CoinGecko
        await self._rate_limit_delay()
        coins = await self._fetch_coingecko_top_coins()
        if not coins:
            logger.warning("No CoinGecko data obtained, keeping previous universe")
            return self._cached_pairs

        # Step 2: Build symbol -> pair mapping and cross-reference with exchange
        candidates: List[Dict[str, Any]] = []
        cg_id_map: Dict[str, str] = {}
        market_data: Dict[str, Dict[str, Any]] = {}

        for coin in coins:
            symbol = (coin.get("symbol") or "").strip().upper()
            cg_id = coin.get("id", "")
            if not symbol or not cg_id:
                continue

            canonical = f"{symbol}/USD"

            # Cross-reference: only include if exchange supports this pair
            if self._exchange_pair_catalog and canonical not in self._exchange_pair_catalog:
                continue

            cg_id_map[canonical] = cg_id
            market_data[canonical] = coin
            candidates.append({
                "pair": canonical,
                "volume_24h": float(coin.get("total_volume", 0) or 0),
                "market_cap": float(coin.get("market_cap", 0) or 0),
                "change_pct": float(coin.get("price_change_percentage_24h", 0) or 0),
            })

        # Step 3: Apply filters
        filtered = self._apply_filters(candidates)

        # Step 4: Merge with pinned
        universe = self._merge(filtered)

        # Step 5: Cache
        self._cached_pairs = universe
        self._coingecko_id_map = cg_id_map
        self._cached_market_data = market_data
        self._last_refresh_ts = time.time()

        elapsed = time.monotonic() - t0
        logger.info(
            "Crypto universe refresh complete",
            total=len(universe),
            dynamic=len(universe) - len([p for p in self._pinned if p in universe]),
            pinned=len([p for p in self._pinned if p in universe]),
            candidates=len(candidates),
            elapsed_s=round(elapsed, 1),
        )
        return universe

    async def _fetch_coingecko_top_coins(
        self, per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch top coins from CoinGecko ordered by volume."""
        url = "https://api.coingecko.com/api/v3/coins/markets"
        headers: Dict[str, str] = {}
        if self._coingecko_api_key:
            headers["x-cg-demo-key"] = self._coingecko_api_key
        params = {
            "vs_currency": "usd",
            "order": "volume_desc",
            "per_page": per_page,
            "page": 1,
            "sparkline": "false",
        }
        try:
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                coins = resp.json()
                logger.info("CoinGecko top coins fetched", count=len(coins))
                return coins
        except Exception as e:
            logger.warning("CoinGecko fetch failed", error=repr(e))
            return []

    def _apply_filters(self, candidates: List[Dict[str, Any]]) -> List[str]:
        """Filter by volume/market cap, rank by volume descending."""
        min_vol = self._cfg.min_volume_24h
        min_cap = self._cfg.min_market_cap

        passed: List[tuple[str, float]] = []
        for c in candidates:
            if c["volume_24h"] < min_vol:
                continue
            if c["market_cap"] < min_cap:
                continue
            passed.append((c["pair"], c["volume_24h"]))

        # Sort by volume descending
        passed.sort(key=lambda x: x[1], reverse=True)

        # Reserve slots for pinned pairs
        max_dynamic = max(0, self._cfg.max_universe_size - len(self._pinned))
        return [pair for pair, _ in passed[:max_dynamic]]

    def _merge(self, dynamic: List[str]) -> List[str]:
        """Merge pinned + dynamic, deduplicated, capped."""
        seen: set[str] = set()
        result: List[str] = []

        for pair in self._pinned:
            if pair not in seen:
                seen.add(pair)
                result.append(pair)

        for pair in dynamic:
            if len(result) >= self._cfg.max_universe_size:
                break
            if pair not in seen:
                seen.add(pair)
                result.append(pair)

        return result

    async def _build_catalog_kraken(self) -> None:
        """Build pair catalog from Kraken's get_asset_pairs() response."""
        raw = await self._rest_client.get_asset_pairs()
        kraken_renames = {"XBT": "BTC", "XDG": "DOGE", "XETC": "ETC"}
        for kraken_key, info in raw.items():
            wsname = info.get("wsname", "")
            if not wsname or "/" not in wsname:
                continue
            base, quote = wsname.split("/", 1)
            base = kraken_renames.get(base, base)
            canonical = f"{base}/{quote}"
            self._exchange_pair_catalog[canonical] = kraken_key

    async def _build_catalog_coinbase(self) -> None:
        """Build pair catalog from Coinbase's get_asset_pairs() response."""
        raw = await self._rest_client.get_asset_pairs()
        products = raw.get("products", []) if isinstance(raw, dict) else raw
        for product in products:
            product_id = product.get("product_id", "")
            if not product_id or "-" not in product_id:
                continue
            # BTC-USD -> BTC/USD
            canonical = product_id.replace("-", "/")
            self._exchange_pair_catalog[canonical] = product_id

    async def _rate_limit_delay(self) -> None:
        """Enforce minimum inter-request delay for CoinGecko API."""
        rate = max(1, self._cfg.coingecko_rate_limit_per_min)
        min_interval = 60.0 / rate
        elapsed = time.time() - self._last_request_ts
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_ts = time.time()
