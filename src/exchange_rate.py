"""Exchange rate fetcher from China Foreign Exchange Trade System (CFETS / chinamoney.com.cn)."""

import logging
from datetime import date, timedelta
from pathlib import Path

import requests

from .utils import load_json, save_json

logger = logging.getLogger(__name__)

CFETS_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.chinamoney.com.cn/chinese/bkccpr/",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Fallback rates (approximate, updated periodically)
FALLBACK_RATES = {
    "USD": 7.18,
    "HKD": 0.923,
    "EUR": 7.82,
    "GBP": 9.12,
    "JPY": 4.78,  # per 100 JPY
    "SGD": 5.38,
    "AUD": 4.68,
    "CAD": 5.18,
    "CHF": 8.12,
}


def _get_first_workday(year: int, month: int) -> date:
    """Get the first workday (Mon-Fri) of a given month."""
    d = date(year, month, 1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d += timedelta(days=1)
    return d


def _fetch_rate_for_date(target_date: date) -> dict[str, float] | None:
    """Fetch exchange rates for a specific date from CFETS API."""
    date_str = target_date.strftime("%Y-%m-%d")
    try:
        resp = requests.post(
            CFETS_URL,
            data={"startDate": date_str, "endDate": date_str},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # API returns: data.searchlist = ["USD/CNY", "EUR/CNY", "100JPY/CNY", ...]
        #              records[0].values = ["7.18", "7.82", ...]
        searchlist = data.get("data", {}).get("searchlist", [])
        records = data.get("records", [])

        if not searchlist or not records:
            return None

        values = records[0].get("values", [])
        if not values:
            return None

        rates = {}
        for pair_name, val_str in zip(searchlist, values):
            try:
                rate_val = float(str(val_str).replace(",", ""))
            except (ValueError, TypeError):
                continue

            pair = pair_name.strip().upper()
            # Format: "USD/CNY" → rate is CNY per 1 USD
            # Format: "100JPY/CNY" → rate is CNY per 100 JPY
            # Format: "CNY/MOP" → inverse, skip for now (we only need XXX/CNY)
            if pair.startswith("CNY/"):
                continue  # Skip inverse pairs
            if "/" not in pair:
                continue

            left = pair.split("/")[0]
            # Handle "100JPY" → "JPY"
            if left.startswith("100"):
                code = left[3:]
            else:
                code = left
            rates[code] = rate_val

        if rates:
            return rates
    except Exception as e:
        logger.warning(f"获取 {date_str} 汇率失败: {e}")
    return None


def fetch_exchange_rates(
    year: int, month: int, cache_dir: Path, currencies: list[str] | None = None
) -> dict:
    """Fetch exchange rates for the given month.

    Returns:
        {
            "rates": {"USD": 7.18, "HKD": 0.923, ...},
            "date": "2026-03-02",
            "source": "chinamoney" | "fallback",
            "url": "https://..."
        }
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"rates_{year}_{month:02d}.json"

    # Check cache
    cached = load_json(cache_file)
    if cached and cached.get("rates"):
        logger.info(f"使用缓存汇率: {cache_file.name}")
        return cached

    # Try fetching from the first workday, then subsequent days
    start_date = _get_first_workday(year, month)
    rates = None
    actual_date = None

    for offset in range(15):  # Try up to 15 days
        try_date = start_date + timedelta(days=offset)
        if try_date.month != month and offset > 0:
            break
        rates = _fetch_rate_for_date(try_date)
        if rates:
            actual_date = try_date
            break

    if rates:
        result = {
            "rates": rates,
            "date": actual_date.strftime("%Y-%m-%d"),
            "source": "chinamoney",
            "url": f"https://www.chinamoney.com.cn/chinese/bkccpr/?date={actual_date.strftime('%Y-%m-%d')}",
        }
        save_json(cache_file, result)
        logger.info(f"汇率获取成功: {actual_date}")
        return result

    # Fallback
    logger.warning("无法从人民银行获取汇率，使用备用汇率")
    result = {
        "rates": FALLBACK_RATES.copy(),
        "date": start_date.strftime("%Y-%m-%d"),
        "source": "fallback",
        "url": "",
    }
    save_json(cache_file, result)
    return result


def convert_to_rmb(amount: float, currency: str, rates: dict[str, float]) -> tuple[float, float]:
    """Convert foreign currency amount to RMB.

    Returns (rmb_amount, rate_used).
    """
    currency = currency.upper().strip()
    if currency in ("RMB", "CNY"):
        return amount, 1.0

    rate = rates.get(currency, 0)
    if rate == 0:
        logger.warning(f"未找到 {currency} 汇率")
        return amount, 1.0

    # JPY rate is per 100 JPY
    if currency == "JPY":
        rmb = amount * rate / 100
    else:
        rmb = amount * rate

    return round(rmb, 2), rate
