def calculate_interruptions(slots):

    if len(slots) <= 1:
        return 0

    interruptions = 0

    for i in range(1, len(slots)):

        if slots[i]["slot"] != (
            slots[i - 1]["slot"] + 1
        ):
            interruptions += 1

    return interruptions


def calculate_cost(
    slots,
    charging_power,
    markup
):

    total_cost = 0

    for slot in slots:

        slot_price = (
            slot["priceCt"] +
            markup
        )

        energy_per_slot = (
            charging_power * 0.25
        )

        total_cost += (
            slot_price / 100
        ) * energy_per_slot

    return round(total_cost, 2)


def block_average_price(block):

    return sum(
        s["priceCt"]
        for s in block
    ) / len(block)


def build_contiguous_blocks(
    prices,
    quarters_needed
):

    blocks = []

    for start in range(len(prices)):

        for length in range(
            1,
            quarters_needed + 1
        ):

            end = start + length

            if end > len(prices):
                break

            block = prices[start:end]

            blocks.append({
                "slots": block,
                "length": length,
                "avgPrice":
                    block_average_price(
                        block
                    ),
                "startSlot":
                    block[0]["slot"],
                "endSlot":
                    block[-1]["slot"]
            })

    return blocks


def pick_blocks(
    prices,
    quarters_needed,
    max_interruptions,
    ranking_key
):

    max_blocks = (
        max_interruptions + 1
    )

    blocks = build_contiguous_blocks(
        prices,
        quarters_needed
    )

    blocks.sort(
        key=ranking_key
    )

    selected = []

    used_slots = set()

    remaining = quarters_needed

    block_count = 0

    #
    # Zuerst möglichst große Blöcke
    # auswählen
    #

    for block in blocks:

        if block_count >= max_blocks:
            break

        overlap = False

        for slot in block["slots"]:

            if slot["slot"] in used_slots:

                overlap = True
                break

        if overlap:
            continue

        for slot in block["slots"]:

            selected.append(slot)

            used_slots.add(
                slot["slot"]
            )

        remaining -= block["length"]

        block_count += 1

        if remaining <= 0:
            break

    #
    # Fehlende Energie unbedingt
    # nachladen
    #

    if remaining > 0:

        remaining_slots = [

            p

            for p in prices

            if p["slot"] not in used_slots

        ]

        remaining_slots.sort(
            key=lambda x: (
                x["priceCt"],
                x["slot"]
            )
        )

        for slot in remaining_slots:

            selected.append(slot)

            used_slots.add(
                slot["slot"]
            )

            remaining -= 1

            if remaining <= 0:
                break

    selected = sorted(
        selected,
        key=lambda x: x["slot"]
    )

    return selected[:quarters_needed]


#
# LOWEST COST
#

def lowest_cost_schedule(
    prices,
    quarters_needed,
    max_interruptions
):

    return pick_blocks(
        prices,
        quarters_needed,
        max_interruptions,
        lambda b: (
            b["avgPrice"],
            -b["length"]
        )
    )


#
# BALANCED
#

def balanced_schedule(
    prices,
    quarters_needed,
    max_interruptions
):

    return pick_blocks(
        prices,
        quarters_needed,
        max_interruptions,
        lambda b: (
            b["avgPrice"] * 0.7
            - b["length"] * 0.3
        )
    )


#
# EARLY FINISH
#

def early_finish_schedule(
    prices,
    quarters_needed,
    max_interruptions
):

    return pick_blocks(
        prices,
        quarters_needed,
        max_interruptions,
        lambda b: (
            -b["endSlot"],
            b["avgPrice"]
        )
    )


def optimize_schedule(
    prices,
    method,
    quarters_needed,
    max_interruptions
):

    method = (
        method
        .lower()
        .strip()
    )

    if method == "lowest-cost":

        return lowest_cost_schedule(
            prices,
            quarters_needed,
            max_interruptions
        )

    if method == "early-finish":

        return early_finish_schedule(
            prices,
            quarters_needed,
            max_interruptions
        )

    return balanced_schedule(
        prices,
        quarters_needed,
        max_interruptions
    )