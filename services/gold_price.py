# ─────────────────────────────────────────────────────────────
# services/gold_price.py — live XAUUSD price via Gold-API.com
# ─────────────────────────────────────────────────────────────
import time
import logging
import httpx
from config.settings import GOLD_API_URL, get_gold_api_key

logger = logging.getLogger(__name__)

_cached_price: float | None = None
_cache_time: float = 0


async def get_live_gold_price() -> float:
    global _cached_price, _cache_time

    if _cached_price and (time.time() - _cache_time) < 60:
        return _cached_price

    api_key = get_gold_api_key()
    if not api_key:
        logger.warning("No Gold API key set. Use /setconfig goldkey <key> in Telegram.")
        return _cached_price or 2320.00

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                GOLD_API_URL,
                headers={"x-access-token": api_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            price = float(resp.json()["price"])
            _cached_price = price
            _cache_time = time.time()
            logger.info(f"Live gold price: {price}")
            return price
    except Exception as e:
        logger.warning(f"Gold API error: {e}")
        return _cached_price or 2320.00
