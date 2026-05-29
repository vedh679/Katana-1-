# ══════════════════════════════════════════════════════════════════════════════
#  KATANA-1  —  USER CONFIGURATION
#  Edit this file freely. Do NOT edit main.py unless changing strategy logic.
# ══════════════════════════════════════════════════════════════════════════════


# ── Interactive Brokers Gateway ───────────────────────────────────────────────
IB_HOST         = "127.0.0.1"
IB_PORT         = 4002      # 4001 = live account  |  4002 = paper account
IB_CLIENT_ID    = 2         # must be unique if multiple scripts run at once
RECONNECT_DELAY = 30        # seconds to wait between reconnection attempts


# ── Rebalancing schedule ──────────────────────────────────────────────────────
REBALANCE_EVERY_DAYS = 4    # calendar days between rebalances
                            # e.g.  4 = ~weekly  |  7 = weekly  |  30 = monthly


# ── Trailing stop-loss ────────────────────────────────────────────────────────
TRAILING_STOP = 0.079       # exit if price falls this % below its rolling peak
                            # e.g.  0.079 = 7.9%  |  0.10 = 10%


# ── Post-stop-loss capital reallocation ───────────────────────────────────────
REALLOCATION_DELAY_DAYS = 5 # calendar days before freed capital is redeployed
                            # to remaining holdings after a stop-loss triggers
                            # 0 = same day  |  5 = wait ~one week


# ── Re-entry cooldown ─────────────────────────────────────────────────────────
COOLDOWN_DAYS = 7           # calendar days a stopped-out stock must wait
                            # before it is allowed back into the portfolio


# ── Momentum signal ───────────────────────────────────────────────────────────
LOOKBACK = 180              # trading days used to compute Sharpe score
SKIP     = 20               # ignore the most recent N days (reduces reversal)


# ── Portfolio construction ────────────────────────────────────────────────────
PERCENTILE   = 0.80         # select stocks in the top (1 - PERCENTILE) fraction
                            # 0.80 = top 20%  |  0.70 = top 30%
MIN_HOLDINGS = 5            # minimum number of stocks required to trade
MAX_WEIGHT   = 0.20         # maximum allocation per position (20%)
BUFFER       = 0.10         # a new entrant must score >10% above the weakest
                            # incumbent to displace it (reduces turnover)


# ── Liquidity entry filters ───────────────────────────────────────────────────
MIN_PRICE  = 5.0            # minimum stock price at entry ($)
MIN_VOLUME = 1_000_000      # minimum average daily dollar volume ($)


# ══════════════════════════════════════════════════════════════════════════════
#  UNIVERSE
#  Add or remove tickers in any sector list below.
#  Duplicates across lists are automatically deduplicated.
# ══════════════════════════════════════════════════════════════════════════════

AI_SOFTWARE = [
    "MSFT", "GOOGL", 
]

CHIPS = [
    "NVDA", "AMD", 
]

NEOCLOUD = [
    "APLD", "CORZ", 
]

HYPERSCALERS = [
    "AMZN", "GOOG", 
]

ROBOTICS = [
    "ISRG", "ROK",
]

SPACE_ENERGY = [
    "RKLB", "SPCE", 
]
