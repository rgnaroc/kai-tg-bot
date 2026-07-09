"""Курсы валют через API ЦБ РФ (бесплатно, без ключа)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"


@dataclass
class RateResult:
    source: str  = "ЦБ РФ"
    rates: list[tuple[str, str, float]] = None  # (код, название, курс)


async def get_usd_rub_rate() -> float | None:
    """Получить курс USD/RUB напрямую из API ЦБ РФ."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(CBR_URL)
            data = r.json()
            usd = data["Valute"]["USD"]
            return float(usd["Value"])
    except Exception as e:
        logger.warning("CBR API failed: %s", e)
        return None


async def get_eur_rub_rate() -> float | None:
    """Получить курс EUR/RUB."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(CBR_URL)
            data = r.json()
            eur = data["Valute"]["EUR"]
            return float(eur["Value"])
    except Exception as e:
        logger.warning("CBR EUR failed: %s", e)
        return None


async def format_rates_text() -> str:
    """Вернуть отформатированный текст с курсами основных валют."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(CBR_URL)
            data = r.json()

        currencies = ["USD", "EUR", "CNY", "GBP", "JPY", "KZT", "BYN"]
        lines = ["**💱 Курсы ЦБ РФ**\n"]
        for code in currencies:
            if code in data["Valute"]:
                v = data["Valute"][code]
                name = v["Name"]
                val = float(v["Value"])
                nom = int(v["Nominal"])
                if nom > 1:
                    lines.append(f"• {nom} {code} ({name}) = **{val:.2f}₽**")
                else:
                    lines.append(f"• {code} ({name}) = **{val:.2f}₽**")

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Не удалось получить курсы: {e}"
