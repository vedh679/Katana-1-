# ══════════════════════════════════════════════════════════════════════════════
#  KATANA-1  —  USER CONFIGURATION
#  Edit this file freely. Do NOT edit main.py unless changing strategy logic.
# ══════════════════════════════════════════════════════════════════════════════


# ── Capital ───────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 1_000_000     # starting capital ($) — used for since-inception P&L


# ── Interactive Brokers Gateway ───────────────────────────────────────────────
IB_HOST         = "127.0.0.1"
IB_PORT         = 4002      # 4001 = live account  |  4002 = paper account
IB_CLIENT_ID    = 2         # must be unique if multiple scripts run at once
RECONNECT_DELAY = 30        # seconds to wait between reconnection attempts

# ── Nightly Gateway-restart avoidance (machine LOCAL time, 24h "HH:MM") ────────
# The IB Gateway auto-restarts once per day (default ~11:11 PM). The algorithm
# disconnects at DAILY_PAUSE_START and reconnects at DAILY_PAUSE_END so it never
# meets the restart mid-operation. These are the MACHINE'S LOCAL clock times
# (NOT US/Eastern) — that is the clock the Gateway restart itself uses.
DAILY_PAUSE_START = "23:00"     # disconnect at 11:00 PM local
DAILY_PAUSE_END   = "23:30"     # reconnect at 11:30 PM local


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
    "MSFT", "GOOGL", "META", "IBM", "CRM", "PLTR", "AI", "BBAI",
    "SOUN", "AMBA", "PATH", "GTLB", "MDB", "SNOW", "DDOG",
    "NET", "HUBS", "ZS",
]

CHIPS = [
    "NVDA", "AMD", "INTC", "AVGO", "QCOM", "TXN", "AMAT", "LRCX",
    "KLAC", "ASML", "TSM", "MU", "MRVL", "NXPI", "SWKS", "QRVO",
    "MPWR", "ENTG", "MKSI", "CRUS", "ACLS", "ONTO", "UCTT", "AMKR",
    "GFS", "NVMI", "AXTI", "IPGP", "COHR", "VIAV", "MTSI", "ALAB",
    "AAOI", "CAMT", "FN", "LITE",
]

NEOCLOUD = [
    "APLD", "CORZ", "CLSK", "HUT", "MARA", "RIOT", "BTBT", "CIFR",
    "WULF", "IREN", "VRT", "SMCI", "NTAP", "STX", "WDC",
]

HYPERSCALERS = [
    "AMZN", "GOOG", "MSFT", "META", "ORCL", "IBM", "CSCO", "ANET",
    "CALX", "NTAP", "GLW", "APH", "BDC", "FLEX",
]

ROBOTICS = [
    "ISRG", "ROK", "EMR", "HON", "ETN", "DOV", "HUBB",
    "TT", "GEV", "CAT", "MOD", "GNRC", "NVT", "FIX", "IESC",
    "EME", "PWR", "J", "TER", "ONTO",
]

SPACE_ENERGY = [
    "RKLB", "SPCE", "ASTS", "MNTS", "RDW", "PL", "BKSY",
    "NEE", "DUK", "SO", "PCG", "AES", "OKLO", "SMR", "LEU",
]
