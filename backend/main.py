from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from datetime import datetime
import random

app = FastAPI(
    title="EV Charging Planner API",
    version="0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OptimizationRequest(BaseModel):
    energyKwh: float
    chargingPowerKw: float
    providerMarkupCt: float
    optimizationMethod: str


def generate_day_ahead_prices():

    prices = []

    for slot in range(96):

        hour = slot // 4
        minute = (slot % 4) * 15

        base = 8

        if 0 <= hour < 6:
            base += random.uniform(0, 4)

        elif 6 <= hour < 17:
            base += random.uniform(8, 14)

        elif 17 <= hour < 22:
            base += random.uniform(15, 28)

        else:
            base += random.uniform(5, 12)

        prices.append(
            {
                "slot": slot,
                "time": f"{hour:02d}:{minute:02d}",
                "priceCt": round(base, 2)
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

    hours_needed = request.energyKwh / request.chargingPowerKw

    quarters_needed = max(
        1,
        round((hours_needed * 60) / 15)
    )

    method = request.optimizationMethod.lower()

    if method == "lowest-cost":

        selected = sorted(
            prices,
            key=lambda x: x["priceCt"]
        )[:quarters_needed]

    elif method == "early-finish":

        selected = prices[:quarters_needed]

    else:
        cheapest = sorted(
            prices,
            key=lambda x: x["priceCt"]
        )[:quarters_needed]

        selected = sorted(
            cheapest,
            key=lambda x: x["slot"]
        )

    total_cost = 0

    for slot in selected:

        price = (
            slot["priceCt"]
            + request.providerMarkupCt
        )

        energy_per_slot = (
            request.chargingPowerKw * 0.25
        )

        total_cost += (
            price / 100
        ) * energy_per_slot

    selected = sorted(
        selected,
        key=lambda x: x["slot"]
    )

    return {

        "optimizationMethod":
            request.optimizationMethod,

        "energyKwh":
            request.energyKwh,

        "chargingPowerKw":
            request.chargingPowerKw,

        "providerMarkupCt":
            request.providerMarkupCt,

        "quartersNeeded":
            quarters_needed,

        "estimatedCostEuro":
            round(total_cost, 2),

        "startTime":
            selected[0]["time"],

        "endTime":
            selected[-1]["time"],

        "selectedSlots":
            selected,

        "prices":
            prices
    }