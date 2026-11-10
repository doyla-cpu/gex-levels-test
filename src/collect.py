"""
Download today's full QQQ option chain from Yahoo Finance and save it as a CSV file.
Run this every evening after the US market closes (after 9pm Irish time).
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKER = "QQQ"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# the information we want to keep for every option contract
COLUMNS = ["contractSymbol", "strike", "bid", "ask", "lastPrice",
           "volume", "openInterest", "impliedVolatility"]


def add_contracts(table, option_type, expiry, spot, collected_at, rows):
    """Go through one table of options (all the calls OR all the puts for one
    expiry date) and add each contract to our list of rows."""
    for i in range(len(table)):
        contract = table.iloc[i]          # one row = one option contract
        row = {}
        for column in COLUMNS:
            row[column] = contract[column]
        row["type"] = option_type         # "call" or "put"
        row["expiry"] = expiry
        row["spot"] = spot
        row["collected_at"] = collected_at
        rows.append(row)


def main():
    qqq = yf.Ticker(TICKER)

    # today's closing price of QQQ
    prices = qqq.history(period="1d")
    spot = prices["Close"].iloc[-1]

    # the time right now, including the time zone, so gex.py can work out
    # exactly how long each option has left until it expires
    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")

    rows = []
    expiries = qqq.options               # list of every expiry date, e.g. "2026-11-14"
    for expiry in expiries:
        chain = qqq.option_chain(expiry)  # gives us a table of calls and a table of puts
        add_contracts(chain.calls, "call", expiry, spot, collected_at, rows)
        add_contracts(chain.puts, "put", expiry, spot, collected_at, rows)

    # turn our list of rows into a table and save it
    DATA_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = DATA_DIR / f"{TICKER.lower()}_chain_{today}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    print(f"Saved {len(rows)} contracts across {len(expiries)} expiries")
    print(f"File: {path.name}")
    print(f"QQQ price: {spot:.2f}")


if __name__ == "__main__":
    main()
