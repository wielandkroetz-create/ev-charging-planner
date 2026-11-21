from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from datetime import datetime
import random

from optimizer import (
    optimize_schedule,
    calculate_cost,
    calculate_interruptions
)

app = FastAPI(
    title="EV Charging Planner API",
    version="0.6"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


class OptimizationRequest(BaseModel):
    energyKwh: float
    chargingPowerKw: float
    providerMarkupCt: float
    optimizationMethod: str
    departureTime: str
    maxInterruptions: int


def generate_day_ahead_prices():

    prices = []

    for slot in range(96):

        hour = slot // 4
        minute = (slot % 4) * 15

        base_price = 8

        if 0 <= hour < 6:

            base_price += random.uniform(0, 4)

        elif 6 <= hour < 17:

            base_price += random.uniform(8, 14)

        elif 17 <= hour < 22:

            base_price += random.uniform(15, 28)

        else:

            base_price += random.uniform(5, 12)

        prices.append(
            {
                "slot": slot,
                "time": f"{hour:02d}:{minute:02d}",
                "priceCt": round(base_price, 2)
            }
        )

    return prices


@app.get("/")
def root():

    return {
        "service": "EV Charging Planner API",
        "status": "running"
    }


@app.get("/api/dayahead")
def dayahead():

    return {
        "generatedAt": datetime.utcnow(),
        "prices": generate_day_ahead_prices()
    }


@app.post("/api/optimize")
def optimize(request: OptimizationRequest):

    prices = generate_day_ahead_prices()

    #
    # Departure Time
    #

    hour, minute = map(
        int,
        request.departureTime.split(":")
    )

    latest_slot = (
        hour * 4
    ) + (
        minute // 15
    )

    prices = [

        p

        for p in prices

        if p["slot"] <= latest_slot

    ]

    if len(prices) == 0:

        return {
            "error": "No charging slots available"
        }

    #
    # Required quarters
    #

    hours_needed = (
        request.energyKwh
        / request.chargingPowerKw
    )

    quarters_needed = max(
        1,
        round(
            (hours_needed * 60) / 15
        )
    )

    #
    # Optimization
    #

    selected = optimize_schedule(
        prices=prices,
        method=request.optimizationMethod,
        quarters_needed=quarters_needed,
        max_interruptions=request.maxInterruptions
    )

    #
    # Safety fallback
    #

    if len(selected) == 0:

        return {
            "error":
                "No feasible charging schedule found"
        }

    #
    # Truncate if optimizer returns too many
    #

    if len(selected) > quarters_needed:

        selected = selected[:quarters_needed]

    #
    # Statistics
    #

    interruptions = calculate_interruptions(
        selected
    )

    total_cost = calculate_cost(
        selected,
        request.chargingPowerKw,
        request.providerMarkupCt
    )

    #
    # Energy
    #

    delivered_energy = round(
        len(selected)
        * request.chargingPowerKw
        * 0.25,
        2
    )

    missing_energy = round(
        max(
            0,
            request.energyKwh
            - delivered_energy
        ),
        2
    )

    charging_feasible = (
        missing_energy < 0.01
    )

    #
    # Result
    #

    return {

        "optimizationMethod":
            request.optimizationMethod,

        "energyKwh":
            round(
                request.energyKwh,
                2
            ),

        "deliveredEnergyKwh":
            delivered_energy,

        "missingEnergyKwh":
            missing_energy,

        "chargingFeasible":
            charging_feasible,

        "chargingPowerKw":
            request.chargingPowerKw,

        "providerMarkupCt":
            request.providerMarkupCt,

        "departureTime":
            request.departureTime,

        "maxInterruptions":
            request.maxInterruptions,

        "actualInterruptions":
            interruptions,

        "quartersNeeded":
            quarters_needed,

        "estimatedCostEuro":
            total_cost,

        "startTime":
            selected[0]["time"],

        "endTime":
            selected[-1]["time"],

        "selectedSlots":
            selected,

        "prices":
            prices
    }