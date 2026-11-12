"""
Calculate dealer gamma exposure (GEX) for QQQ from a saved option chain,
then find the gamma flip, the call wall and the put wall, and plot them.

Sign convention (an assumption, not something we can observe):
dealers are LONG calls  -> calls count as POSITIVE gamma
dealers are SHORT puts  -> puts count as NEGATIVE gamma
"""
import csv
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
NEW_YORK = ZoneInfo("America/New_York")
RATE = 0.04                         # risk-free interest rate (approximate)
SECONDS_PER_YEAR = 365 * 24 * 60 * 60
MIN_YEARS = 1 / (365 * 24)          # never let time to expiry go below one hour


# Step 1: Black-Scholes gamma for one option
def gamma(spot, strike, years, vol):
    """How much the option's delta changes when the stock moves $1.
    The formula is the same for calls and puts."""
    d1 = (math.log(spot / strike) + (RATE + vol ** 2 / 2) * years) / (vol * math.sqrt(years))
    normal_pdf = math.exp(-d1 ** 2 / 2) / math.sqrt(2 * math.pi)
    return normal_pdf / (spot * vol * math.sqrt(years))


# Step 2: load the CSV and keep only the contracts we can use
def load_contracts(path):
    contracts = []
    with open(path) as f:
        for row in csv.DictReader(f):
            # When was the data collected? Convert to New York time.
            collected = datetime.fromisoformat(row["collected_at"])
            if collected.tzinfo is None:          # older files had no time zone:
                collected = collected.astimezone()  # assume this computer's time zone
            collected = collected.astimezone(NEW_YORK)

            # Options stop trading at 4pm New York time on their expiry day.
            expiry = datetime.fromisoformat(row["expiry"]).replace(hour=16, tzinfo=NEW_YORK)
            years_left = (expiry - collected).total_seconds() / SECONDS_PER_YEAR

            open_interest = float(row["openInterest"] or 0)
            vol = float(row["impliedVolatility"] or 0)

            # Skip options that have expired, have no open interest,
            # or have a nonsense implied volatility (common in free data).
            if years_left <= 0 or open_interest <= 0 or not 0.01 <= vol <= 3.0:
                continue

            contracts.append({
                "strike": float(row["strike"]),
                "type": row["type"],
                "years": max(years_left, MIN_YEARS),
                "vol": vol,
                "open_interest": open_interest,
                "spot": float(row["spot"]),
            })
    return contracts


# Step 3: GEX for one contract = dollars of QQQ dealers must trade per 1% move
def contract_gex(c, spot):
    g = gamma(spot, c["strike"], c["years"], c["vol"])
    gex = g * c["open_interest"] * 100 * spot ** 2 * 0.01
    if c["type"] == "put":
        gex = -gex   # our sign convention: puts are negative
    return gex


# Step 4: add up GEX at each strike, separately for calls and puts
def gex_by_strike(contracts, spot):
    calls = {}   # strike -> total call GEX
    puts = {}    # strike -> total put GEX
    for c in contracts:
        gex = contract_gex(c, spot)
        if c["type"] == "call":
            calls[c["strike"]] = calls.get(c["strike"], 0) + gex
        else:
            puts[c["strike"]] = puts.get(c["strike"], 0) + gex
    return calls, puts


# Step 5: the gamma flip = the price where total GEX changes sign
def total_gex(contracts, spot):
    total = 0
    for c in contracts:
        total += contract_gex(c, spot)
    return total


def find_gamma_flip(contracts, spot):
    """Pretend QQQ is at different prices (from 10% below to 10% above today),
    recalculate total GEX at each one, and find where it crosses zero."""
    low, high, steps = spot * 0.90, spot * 1.10, 400
    step_size = (high - low) / steps

    prices = [low + i * step_size for i in range(steps + 1)]
    totals = [total_gex(contracts, p) for p in prices]

    best = None
    for i in range(steps):
        if (totals[i] < 0) != (totals[i + 1] < 0):       # the sign changed here
            # estimate exactly where between the two prices it hit zero
            fraction = totals[i] / (totals[i] - totals[i + 1])
            crossing = prices[i] + fraction * step_size
            # if there is more than one crossing, keep the one nearest to today's price
            if best is None or abs(crossing - spot) < abs(best - spot):
                best = crossing
    return best


# Step 6: save today's levels to results/levels.csv
def save_levels(date, spot, total, flip, call_wall, put_wall):
    """Add one row per day to levels.csv. If the date is already there,
    replace that row instead of adding a duplicate."""
    path = RESULTS_DIR / "levels.csv"
    columns = ["date", "spot", "total_gex_bn", "gamma_flip", "call_wall", "put_wall"]

    # read the rows we already have, keyed by date
    rows = {}
    if path.exists():
        with open(path) as f:
            for row in csv.DictReader(f):
                rows[row["date"]] = row

    # add (or replace) today's row
    rows[date] = {
        "date": date,
        "spot": f"{spot:.2f}",
        "total_gex_bn": f"{total:.2f}",
        "gamma_flip": f"{flip:.2f}" if flip else "",
        "call_wall": f"{call_wall:.0f}",
        "put_wall": f"{put_wall:.0f}",
    }

    # write everything back, sorted by date
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for d in sorted(rows):
            writer.writerow(rows[d])


# Step 7: put it all together and plot
def main():
    latest_file = sorted(DATA_DIR.glob("*_chain_*.csv"))[-1]
    contracts = load_contracts(latest_file)
    spot = contracts[0]["spot"]

    calls, puts = gex_by_strike(contracts, spot)
    # call wall = biggest call GEX ABOVE spot (resistance, a ceiling)
    calls_above = {}
    for strike in calls:
        if strike > spot:
            calls_above[strike] = calls[strike]
    call_wall = max(calls_above, key=calls_above.get)

    # put wall = most negative put GEX BELOW spot (support, a floor)
    puts_below = {}
    for strike in puts:
        if strike < spot:
            puts_below[strike] = puts[strike]
    put_wall = min(puts_below, key=puts_below.get)
    flip = find_gamma_flip(contracts, spot)

    print(f"Spot:        {spot:.2f}")

    total = total_gex(contracts, spot) / 1e9

    if total < 0:
        print(f"Total GEX:   -${abs(total):.2f}bn")
    else:
        print(f"Total GEX:   ${total:.2f}bn")

    print(f"Gamma flip:  {flip:.2f}" if flip else "Gamma flip:  none found")
    print(f"Call wall:   {call_wall:.0f}")
    print(f"Put wall:    {put_wall:.0f}")

    # file names look like qqq_chain_2026-11-11, so the date is the last part
    date = latest_file.stem.split("_")[-1]
    save_levels(date, spot, total, flip, call_wall, put_wall)
    print(f"Saved to results/levels.csv")

    # net GEX at each strike, only for strikes within 8% of spot
    strikes, net = [], []
    for strike in sorted(set(calls) | set(puts)):
        if spot * 0.92 <= strike <= spot * 1.08:
            strikes.append(strike)
            net.append((calls.get(strike, 0) + puts.get(strike, 0)) / 1e6)

    colours = ["tab:green" if value >= 0 else "tab:red" for value in net]
    plt.figure(figsize=(12, 6))
    plt.bar(strikes, net, width=0.8, color=colours)
    plt.axvline(spot, color="black", label=f"Spot {spot:.2f}")
    if flip:
        plt.axvline(flip, color="orange", linestyle="--", label=f"Gamma flip {flip:.2f}")
    plt.axvline(call_wall, color="tab:green", linestyle=":", label=f"Call wall {call_wall:.0f}")
    plt.axvline(put_wall, color="tab:red", linestyle=":", label=f"Put wall {put_wall:.0f}")
    plt.xlabel("Strike")
    plt.ylabel("Net GEX ($m per 1% move)")
    plt.title(f"QQQ dealer GEX by strike — {latest_file.stem}")
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
