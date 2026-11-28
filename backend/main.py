from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from math import ceil
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from optimizer import (
    calculate_interruptions,
    optimize_schedule,
)


ENERGY_CHARTS_BASE_URL = "https://api.energy-charts.info"
ENERGY_CHARTS_ENDPOINT = "/v2/price_next_day"
BIDDING_ZONE = "DE-LU"

CACHE_TTL_SECONDS = 15 * 60
HTTP_TIMEOUT_SECONDS = 20.0

FRONTEND_ORIGINS = [
    "http://localhost:4200",
    "https://victorious-smoke-018405803.3.azurestaticapps.net",
]


app = FastAPI(
    title="EV Charging Planner API",
    version="1.0.0",
    description=(
        "EV charging optimization using DE-LU day-ahead prices "
        "from Energy-Charts."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class OptimizationRequest(BaseModel):
    energyKwh: float = Field(gt=0, le=200)
    chargingPowerKw: float = Field(gt=0, le=350)
    providerMarkupCt: float = Field(ge=0, le=100)
    optimizationMethod: str
    departureTime: str
    maxInterruptions: int = Field(ge=0, le=20)


_cache_lock = asyncio.Lock()

_price_cache: dict[str, Any] = {
    "payload": None,
    "stored_at": None,
}


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "EV Charging Planner API",
        "status": "running",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    """
    Schlanker Endpunkt für Health Checks und das Aufwecken
    einer auf null skalierten Azure Container App.
    """
    return {
        "status": "healthy",
        "service": "EV Charging Planner API",
    }


def cache_is_fresh() -> bool:
    stored_at = _price_cache.get("stored_at")

    if stored_at is None:
        return False

    age_seconds = (
        datetime.now(timezone.utc) - stored_at
    ).total_seconds()

    return age_seconds < CACHE_TTL_SECONDS


def get_cached_payload(
    cache_status: str,
) -> dict[str, Any] | None:
    payload = _price_cache.get("payload")

    if payload is None:
        return None

    result = dict(payload)
    result["dataStatus"] = cache_status

    return result


def detect_price_series_id(
    api_payload: dict[str, Any],
) -> str:
    """
    Ermittelt die Preisreihe aus dem selbstbeschreibenden
    Energy-Charts-v2-Format.
    """
    descriptors = api_payload.get("series", [])

    preferred_ids = {
        "price",
        "day_ahead_price",
        "day-ahead-price",
        "value",
    }

    for descriptor in descriptors:
        series_id = str(descriptor.get("id", ""))

        if series_id.lower() in preferred_ids:
            return series_id

    for descriptor in descriptors:
        series_id = str(descriptor.get("id", ""))
        unit = str(descriptor.get("unit", api_payload.get("unit", "")))

        if "eur/mwh" in unit.lower():
            return series_id

    data = api_payload.get("data", [])

    for point in data:
        values = point.get("values", {})

        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(value, (int, float)):
                    return str(key)

    raise ValueError(
        "No numeric price series was found in the Energy-Charts response."
    )


def extract_license_info(
    api_payload: dict[str, Any],
) -> str:
    attributes = api_payload.get("attributes", {})

    candidates = [
        api_payload.get("license_info"),
        api_payload.get("license"),
        attributes.get("license_info"),
        attributes.get("license"),
    ]

    for candidate in candidates:
        if candidate:
            return str(candidate)

    return (
        "CC BY 4.0; source: Bundesnetzagentur | SMARD.de; "
        "provided unchanged by Energy-Charts.info"
    )


def convert_eur_mwh_to_ct_kwh(
    price_eur_mwh: float,
) -> float:
    # 1 EUR/MWh entspricht 0,1 ct/kWh.
    return round(price_eur_mwh / 10.0, 4)


def transform_energy_charts_response(
    api_payload: dict[str, Any],
) -> dict[str, Any]:
    series_id = detect_price_series_id(api_payload)
    data_points = api_payload.get("data", [])

    prices: list[dict[str, Any]] = []

    for slot_number, point in enumerate(data_points):
        values = point.get("values", {})
        raw_price = values.get(series_id)

        if raw_price is None:
            continue

        timestamp = (
            point.get("timestamp")
            or point.get("time")
            or point.get("datetime")
        )

        if timestamp is None:
            continue

        parsed_timestamp = datetime.fromisoformat(
            str(timestamp).replace("Z", "+00:00")
        )

        prices.append(
            {
                "slot": slot_number,
                "time": parsed_timestamp.strftime("%H:%M"),
                "timestamp": str(timestamp),
                "priceEurMwh": round(float(raw_price), 4),
                "priceCt": convert_eur_mwh_to_ct_kwh(
                    float(raw_price)
                ),
            }
        )

    if not prices:
        raise ValueError(
            "Energy-Charts returned no usable day-ahead prices."
        )

    attributes = api_payload.get("attributes", {})

    return {
        "generatedAt": api_payload.get("generated_at"),
        "deliveryDate": attributes.get("delivery_date"),
        "availableFrom": api_payload.get("available_from"),
        "availableUntil": api_payload.get("available_until"),
        "timezone": api_payload.get("timezone", "Europe/Berlin"),
        "resolution": api_payload.get("resolution"),
        "intervalMinutes": api_payload.get("interval_minutes", 15),
        "unitOriginal": api_payload.get("unit", "EUR/MWh"),
        "unitDisplay": "ct/kWh",
        "biddingZone": api_payload.get(
            "bidding_zone",
            BIDDING_ZONE,
        ),
        "dataStatus": "live",
        "source": {
            "provider": "Energy-Charts.info",
            "organization": "Fraunhofer ISE",
            "originalDataSource": (
                "Bundesnetzagentur | SMARD.de"
            ),
            "license": extract_license_info(api_payload),
            "licenseUrl": (
                "https://creativecommons.org/licenses/by/4.0/"
            ),
            "apiEndpoint": (
                f"{ENERGY_CHARTS_BASE_URL}"
                f"{ENERGY_CHARTS_ENDPOINT}"
                f"?bzn={BIDDING_ZONE}"
            ),
        },
        "prices": prices,
    }


async def fetch_next_day_prices(
    force_refresh: bool = False,
) -> dict[str, Any]:
    if not force_refresh and cache_is_fresh():
        cached = get_cached_payload("cache-fresh")

        if cached is not None:
            return cached

    async with _cache_lock:
        if not force_refresh and cache_is_fresh():
            cached = get_cached_payload("cache-fresh")

            if cached is not None:
                return cached

        url = (
            f"{ENERGY_CHARTS_BASE_URL}"
            f"{ENERGY_CHARTS_ENDPOINT}"
        )

        params = {
            "bzn": BIDDING_ZONE,
        }

        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers={
                        "User-Agent": (
                            "EV-Charging-Planner/1.0"
                        )
                    },
                    )

        except httpx.TimeoutException as exc:
            cached = get_cached_payload("cache-stale")

            if cached is not None:
                return cached

            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=(
                    "Energy-Charts did not respond in time."
                ),
        ) from exc

        except httpx.HTTPError as exc:
            cached = get_cached_payload("cache-stale")

            if cached is not None:
                return cached

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Energy-Charts could not be reached."
                ),
            ) from exc

        if response.status_code == 404:
            cached = get_cached_payload("cache-stale")

            if cached is not None:
                cached["message"] = (
                    "Tomorrow's day-ahead prices are not yet "
                    "published. The last cached curve is shown."
                )
                return cached

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Tomorrow's DE-LU day-ahead prices are not "
                    "yet published."
                ),
            )

        if response.status_code == 429:
            cached = get_cached_payload("cache-stale")

            if cached is not None:
                cached["message"] = (
                    "Energy-Charts rate limit reached. "
                    "Cached prices are shown."
                )
                return cached

            retry_after = response.headers.get(
                "Retry-After",
                "60",
            )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": (
                        "Energy-Charts rate limit reached."
                    ),
                    "retryAfterSeconds": retry_after,
                },
                headers={
                    "Retry-After": retry_after,
                },
            )

        response.raise_for_status()

        try:
            transformed = transform_energy_charts_response(
                response.json()
            )

        except (ValueError, KeyError, TypeError) as exc:
            cached = get_cached_payload("cache-stale")

            if cached is not None:
                return cached

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "The Energy-Charts response could not be "
                    "processed."
                ),
            ) from exc

        _price_cache["payload"] = transformed
        _price_cache["stored_at"] = datetime.now(
            timezone.utc
        )

        return transformed


@app.get("/api/dayahead")
async def dayahead(
    response: Response,
    refresh: bool = False,
) -> dict[str, Any]:
    result = await fetch_next_day_prices(
        force_refresh=refresh
    )

    response.headers["Cache-Control"] = (
        "public, max-age=300"
    )

    return result


def departure_slot_from_time(
    departure_time: str,
    available_slots: int,
) -> int:
    try:
        hour_text, minute_text = departure_time.split(":")
        hour = int(hour_text)
        minute = int(minute_text)

    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "departureTime must use the format HH:MM."
            ),
        ) from exc

    if (
        hour < 0
        or hour > 23
        or minute not in {0, 15, 30, 45}
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "departureTime must be a valid 15-minute time."
            ),
        )

    slot = (hour * 4) + (minute // 15)

    return min(slot, available_slots)


def calculate_energy_and_cost(
    selected_slots: list[dict[str, Any]],
    requested_energy_kwh: float,
    charging_power_kw: float,
    provider_markup_ct: float,
) -> tuple[float, float, float]:
    remaining_energy = requested_energy_kwh
    delivered_energy = 0.0
    total_cost = 0.0

    maximum_slot_energy = charging_power_kw * 0.25

    for slot in selected_slots:
        if remaining_energy <= 0:
            break

        slot_energy = min(
            maximum_slot_energy,
            remaining_energy,
        )

        effective_price_ct = (
            float(slot["priceCt"])
            + provider_markup_ct
        )

        total_cost += (
            effective_price_ct / 100.0
        ) * slot_energy

        delivered_energy += slot_energy
        remaining_energy -= slot_energy

    missing_energy = max(
        0.0,
        requested_energy_kwh - delivered_energy,
    )

    return (
        round(delivered_energy, 3),
        round(missing_energy, 3),
        round(total_cost, 2),
    )


@app.post("/api/optimize")
async def optimize(
    request: OptimizationRequest,
) -> dict[str, Any]:
    market_data = await fetch_next_day_prices()

    all_prices = market_data["prices"]

    departure_slot = departure_slot_from_time(
        request.departureTime,
        len(all_prices),
    )

    available_prices = [
        price
        for price in all_prices
        if price["slot"] < departure_slot
    ]

    if not available_prices:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No charging slots are available before "
                "the selected departure time."
            ),
        )

    energy_per_full_slot = (
        request.chargingPowerKw * 0.25
    )

    quarters_needed = max(
        1,
        ceil(
            request.energyKwh
            / energy_per_full_slot
        ),
    )

    selectable_quarters = min(
        quarters_needed,
        len(available_prices),
    )

    selected = optimize_schedule(
        prices=available_prices,
        method=request.optimizationMethod,
        quarters_needed=selectable_quarters,
        max_interruptions=request.maxInterruptions,
    )

    selected = sorted(
        selected,
        key=lambda item: item["slot"],
    )

    if not selected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No feasible charging schedule was found."
            ),
        )

    actual_interruptions = calculate_interruptions(
        selected
    )

    (
        delivered_energy,
        missing_energy,
        estimated_cost,
    ) = calculate_energy_and_cost(
        selected_slots=selected,
        requested_energy_kwh=request.energyKwh,
        charging_power_kw=request.chargingPowerKw,
        provider_markup_ct=request.providerMarkupCt,
    )

    return {
        "optimizationMethod": request.optimizationMethod,
        "energyKwh": round(request.energyKwh, 3),
        "deliveredEnergyKwh": delivered_energy,
        "missingEnergyKwh": missing_energy,
        "chargingFeasible": missing_energy < 0.001,
        "chargingPowerKw": request.chargingPowerKw,
        "providerMarkupCt": request.providerMarkupCt,
        "departureTime": request.departureTime,
        "maxInterruptions": request.maxInterruptions,
        "actualInterruptions": actual_interruptions,
        "quartersNeeded": quarters_needed,
        "quartersSelected": len(selected),
        "estimatedCostEuro": estimated_cost,
        "startTime": selected[0]["time"],
        "endTime": selected[-1]["time"],
        "selectedSlots": selected,
        "prices": all_prices,
        "marketData": {
            "deliveryDate": market_data.get(
                "deliveryDate"
            ),
            "biddingZone": market_data.get(
                "biddingZone"
            ),
            "dataStatus": market_data.get(
                "dataStatus"
            ),
            "source": market_data.get("source"),
        },
    }