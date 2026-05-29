#!/usr/bin/env python3
"""
Katana-1: Cross-Sectional Sharpe Momentum Strategy
Live / Paper trading via Interactive Brokers Gateway (ib_insync)
All historical and current price data sourced directly from IB.

Edit config.py to change parameters, universe, or IB connection settings.

NOTE: IB allows max 60 historical-data requests per 10-minute window.
      With ~82 universe symbols the history fetch takes ~16 minutes
      (12 s pacing between requests). This runs once per rebalance cycle.

Run:  python main.py
Stop: Ctrl+C
"""

import logging
import math
import sys
import time
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd
import pytz
from ib_insync import IB, Stock, MarketOrder, util

import config

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("katana1.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


class KatanaStrategy:
    """
    Cross-Sectional Sharpe Momentum Strategy
    Sectors: AI Software, Chip Manufacturing, Neocloud, Hyperscalers, Robotics, Space Tech

    Signal:  Sharpe-ratio momentum (mean daily return / std) over LOOKBACK days, skip SKIP days
    Select:  Top (1 - PERCENTILE), minimum MIN_HOLDINGS stocks required
    Weight:  Inverse volatility, capped at MAX_WEIGHT per position
    Rebal:   Every REBALANCE_EVERY_DAYS calendar days with BUFFER score advantage for incumbents
    Filter:  MIN_PRICE minimum price, MIN_VOLUME minimum daily dollar volume
    Risk:    SPY 200-day MA regime filter + TRAILING_STOP + COOLDOWN_DAYS re-entry cooldown

    All parameters are read from config.py at startup.
    """

    # ════════════════════════════════════════════════════════════════════════
    # INIT
    # ════════════════════════════════════════════════════════════════════════
    def __init__(self):
        self.ib = IB()
        self._load_config()
        self._build_universe()
        self._init_state()
        self._register_ib_callbacks()

    def _load_config(self):
        """Read all parameters from config.py into instance attributes."""
        # IB connection
        self.IB_HOST         = config.IB_HOST
        self.IB_PORT         = config.IB_PORT
        self.IB_CLIENT_ID    = config.IB_CLIENT_ID
        self.RECONNECT_DELAY = config.RECONNECT_DELAY
        # Rebalancing
        self.REBALANCE_EVERY_DAYS    = config.REBALANCE_EVERY_DAYS
        # Risk
        self.TRAILING_STOP           = config.TRAILING_STOP
        self.REALLOCATION_DELAY_DAYS = config.REALLOCATION_DELAY_DAYS
        self.COOLDOWN_DAYS           = config.COOLDOWN_DAYS
        # Signal
        self.LOOKBACK    = config.LOOKBACK
        self.SKIP        = config.SKIP
        # Construction
        self.PERCENTILE   = config.PERCENTILE
        self.MIN_HOLDINGS = config.MIN_HOLDINGS
        self.MAX_WEIGHT   = config.MAX_WEIGHT
        self.BUFFER       = config.BUFFER
        # Filters
        self.MIN_PRICE  = config.MIN_PRICE
        self.MIN_VOLUME = config.MIN_VOLUME

        log.info(
            f"Config loaded — "
            f"Port: {self.IB_PORT} ({'PAPER' if self.IB_PORT == 4002 else 'LIVE'}) | "
            f"Rebal every {self.REBALANCE_EVERY_DAYS}d | "
            f"Stop: {self.TRAILING_STOP:.1%} | "
            f"Lookback: {self.LOOKBACK}d / skip {self.SKIP}d"
        )

    def _build_universe(self):
        raw = list(dict.fromkeys(
            config.AI_SOFTWARE + config.CHIPS + config.NEOCLOUD +
            config.HYPERSCALERS + config.ROBOTICS + config.SPACE_ENERGY
        ))
        self.all_tickers: List[str] = raw
        self.contracts: Dict[str, Stock] = {t: Stock(t, "SMART", "USD") for t in raw}
        self.contracts["SPY"] = Stock("SPY", "SMART", "USD")
        log.info(f"Universe: {len(raw)} unique tickers across 6 sectors.")

    def _init_state(self):
        self._peak_prices:      Dict[str, float] = {}
        self._cooldown_until:   Dict[str, date]  = {}
        self._pending_realloc:  Dict[str, date]  = {}
        self._current_holdings: Set[str]          = set()
        self._next_rebal_date:  Optional[date]    = None
        self._last_log_date:    Optional[date]    = None
        self._stop_checked_today  = False
        self._daily_checked_today = False
        self._last_event_date: Optional[date]     = None
        # IB historical data caches (populated by _fetch_universe_history)
        self._close_cache:  pd.DataFrame = pd.DataFrame()
        self._volume_cache: pd.DataFrame = pd.DataFrame()

    def _register_ib_callbacks(self):
        self.ib.disconnectedEvent += self._on_ib_disconnect
        self.ib.errorEvent        += self._on_ib_error

    # ════════════════════════════════════════════════════════════════════════
    # IB CALLBACKS
    # ════════════════════════════════════════════════════════════════════════
    def _on_ib_disconnect(self):
        log.warning("IB Gateway disconnected.")

    def _on_ib_error(self, reqId, errorCode, errorString, contract):
        if errorCode in {2104, 2106, 2107, 2108, 2158, 2100}:
            return   # suppress routine farm/connectivity info messages
        if errorCode in (1100, 2110):
            log.warning(f"IB connectivity lost  [{errorCode}]: {errorString}")
        elif errorCode == 1102:
            log.info(f"IB connectivity restored [{errorCode}]: {errorString}")
        else:
            sym = contract.symbol if contract else "—"
            log.error(f"IB error {errorCode} ({sym}): {errorString}")

    # ════════════════════════════════════════════════════════════════════════
    # CONNECTION
    # ════════════════════════════════════════════════════════════════════════
    def _connect(self):
        """Connect to IB Gateway, retrying indefinitely until successful."""
        attempt = 0
        while True:
            attempt += 1
            try:
                log.info(
                    f"Connecting to IB Gateway {self.IB_HOST}:{self.IB_PORT} "
                    f"(attempt {attempt}) ..."
                )
                self.ib.connect(
                    self.IB_HOST, self.IB_PORT,
                    clientId=self.IB_CLIENT_ID,
                    timeout=20,
                )
                log.info("Connected to IB Gateway.")
                self._qualify_contracts()
                self._sync_state_from_ib()
                return
            except Exception as e:
                log.warning(f"Connection failed: {e}  — retrying in {self.RECONNECT_DELAY}s")
                time.sleep(self.RECONNECT_DELAY)

    def _reconnect_loop(self):
        """
        Block here retrying until IB Gateway comes back.
        All strategy state (holdings, peaks, cooldowns) is preserved in memory
        across the outage — the strategy resumes exactly where it left off.
        """
        try:
            self.ib.disconnect()
        except Exception:
            pass
        attempt = 0
        while True:
            attempt += 1
            log.info(f"Reconnect attempt {attempt} — waiting {self.RECONNECT_DELAY}s ...")
            time.sleep(self.RECONNECT_DELAY)
            try:
                self.ib.connect(
                    self.IB_HOST, self.IB_PORT,
                    clientId=self.IB_CLIENT_ID,
                    timeout=20,
                )
                log.info("Reconnected to IB Gateway.")
                self._qualify_contracts()
                return
            except Exception as e:
                log.warning(f"Reconnect failed: {e}")

    def _qualify_contracts(self):
        """Fill in conId / exchange details for every contract via IB."""
        log.info(f"Qualifying {len(self.contracts)} contracts ...")
        items      = list(self.contracts.items())
        batch_size = 50
        qualified: Dict[str, Stock] = {}

        for i in range(0, len(items), batch_size):
            batch = [c for _, c in items[i : i + batch_size]]
            try:
                result = self.ib.qualifyContracts(*batch)
                for c in result:
                    qualified[c.symbol] = c
            except Exception as e:
                log.warning(f"Qualification error (batch {i // batch_size + 1}): {e}")
            self.ib.sleep(1)

        if qualified:
            self.contracts.update(qualified)
            self.all_tickers = [t for t in self.all_tickers if t in qualified]
            log.info(f"{len(qualified)} contracts qualified. Universe: {len(self.all_tickers)} tickers.")
        else:
            log.error("No contracts qualified — verify IB Gateway is running.")

    def _sync_state_from_ib(self):
        """
        On startup, seed _current_holdings from any existing IB positions so
        the strategy is aware of trades placed in a previous run.
        Peak prices are set to current price (conservative: no immediate stop).
        """
        positions = self._positions()
        if not positions:
            return
        log.info(f"Existing IB positions found — syncing {len(positions)} holdings ...")
        prices = self._snapshot_prices(list(positions.keys()))
        for ticker, qty in positions.items():
            if qty != 0 and ticker in self.contracts:
                self._current_holdings.add(ticker)
                p = prices.get(ticker, 0.0)
                if p > 0:
                    self._peak_prices[ticker] = p
        log.info(f"Synced holdings: {sorted(self._current_holdings)}")

    # ════════════════════════════════════════════════════════════════════════
    # PORTFOLIO / PRICE HELPERS
    # ════════════════════════════════════════════════════════════════════════
    def _portfolio_value(self) -> float:
        # Retry up to 10 s — account data stream may still be arriving
        for attempt in range(10):
            for currency in ("USD", "BASE"):
                for av in self.ib.accountValues():
                    if av.tag == "NetLiquidation" and av.currency == currency:
                        try:
                            v = float(av.value)
                            if v > 0:
                                return v
                        except ValueError:
                            pass
            self.ib.sleep(1)
        available = [(av.tag, av.currency, av.value) for av in self.ib.accountValues()]
        log.warning(f"NetLiquidation not found after 10s. Available tags: {available[:8]}")
        return 0.0

    def _positions(self) -> Dict[str, float]:
        return {p.contract.symbol: float(p.position) for p in self.ib.positions()}

    def _snapshot_prices(self, tickers: List[str]) -> Dict[str, float]:
        """One-shot IB snapshot of last/close price for each ticker."""
        contracts = [self.contracts[t] for t in tickers if t in self.contracts]
        if not contracts:
            return {}
        try:
            tdata = self.ib.reqTickers(*contracts)
        except Exception as e:
            log.warning(f"Snapshot price request failed: {e}")
            return {}
        prices: Dict[str, float] = {}
        for td in tdata:
            sym = td.contract.symbol
            p   = td.last if (td.last and td.last > 0) else td.close
            if p and p > 0:
                prices[sym] = float(p)
        return prices

    def _single_price(self, ticker: str) -> float:
        return self._snapshot_prices([ticker]).get(ticker, 0.0)

    # ════════════════════════════════════════════════════════════════════════
    # ORDER HELPERS
    # ════════════════════════════════════════════════════════════════════════
    def _set_holdings(
        self,
        ticker: str,
        weight: float,
        pv: float,
        prices: Dict[str, float],
        positions: Dict[str, float],
    ) -> bool:
        """Adjust position in `ticker` to `weight` × portfolio value."""
        if ticker not in self.contracts or pv <= 0:
            return False
        price = prices.get(ticker) or self._single_price(ticker)
        if not price or price <= 0:
            log.warning(f"No price for {ticker} — skipping order.")
            return False

        target_shares  = int(weight * pv / price)
        current_shares = int(positions.get(ticker, 0))
        delta          = target_shares - current_shares
        if abs(delta) < 1:
            return False

        action = "BUY" if delta > 0 else "SELL"
        try:
            self.ib.placeOrder(self.contracts[ticker], MarketOrder(action, abs(delta)))
            self.ib.sleep(0.1)
            log.info(
                f"ORDER  {action} {abs(delta):>6} {ticker:<6}  "
                f"~${price:.2f}  target {weight:.1%}"
            )
            return True
        except Exception as e:
            log.error(f"Order failed for {ticker}: {e}")
            return False

    def _liquidate(self, ticker: str, positions: Optional[Dict[str, float]] = None) -> bool:
        if positions is None:
            positions = self._positions()
        qty = int(positions.get(ticker, 0))
        if qty == 0 or ticker not in self.contracts:
            return False
        try:
            self.ib.placeOrder(self.contracts[ticker], MarketOrder("SELL", abs(qty)))
            self.ib.sleep(0.1)
            log.info(f"LIQUIDATE  SELL {abs(qty)} {ticker}")
            return True
        except Exception as e:
            log.error(f"Liquidate failed for {ticker}: {e}")
            return False

    def _liquidate_all(self):
        positions = self._positions()
        for ticker, qty in positions.items():
            if qty != 0:
                self._liquidate(ticker, positions)

    # ════════════════════════════════════════════════════════════════════════
    # HISTORICAL DATA  (IB reqHistoricalData — ADJUSTED_LAST daily bars)
    # ════════════════════════════════════════════════════════════════════════
    def _fetch_universe_history(self, trading_days: int):
        """
        Pull split/dividend-adjusted daily OHLCV from IB for every universe
        ticker plus SPY.  Results are cached in self._close_cache and
        self._volume_cache.

        IB pacing rule: max 60 historical-data requests per 10-minute window.
        We sleep 12 s between requests → ~54 req/10 min (safe margin).
        """
        cal_days = math.ceil(trading_days * 365 / 252) + 30
        years    = max(1, math.ceil(cal_days / 365))
        duration = f"{years} Y"

        fetch_list = self.all_tickers + ["SPY"]
        n          = len(fetch_list)
        eta_min    = n * 12 // 60 + 1
        log.info(
            f"Fetching {trading_days} trading-day history from IB "
            f"for {n} symbols (~{eta_min} min) ..."
        )

        all_close:  Dict[str, pd.Series] = {}
        all_volume: Dict[str, pd.Series] = {}

        for i, ticker in enumerate(fetch_list):
            if ticker not in self.contracts:
                continue
            if not self.ib.isConnected():
                log.warning("IB disconnected mid-fetch — aborting history pull.")
                break
            try:
                bars = self.ib.reqHistoricalData(
                    self.contracts[ticker],
                    endDateTime    = "",
                    durationStr    = duration,
                    barSizeSetting = "1 day",
                    whatToShow     = "ADJUSTED_LAST",
                    useRTH         = True,
                    formatDate     = 1,
                    keepUpToDate   = False,
                )
                if bars:
                    _raw = util.df(bars)
                    df   = _raw.set_index(pd.to_datetime(_raw["date"]))
                    all_close[ticker] = df["close"]
                    if "volume" in df.columns:
                        all_volume[ticker] = df["volume"]
                    log.info(f"  [{i+1}/{n}] {ticker}: {len(bars)} bars")
                else:
                    log.warning(f"  [{i+1}/{n}] {ticker}: no data returned")
            except Exception as e:
                log.warning(f"  [{i+1}/{n}] {ticker}: {e}")

            if i < n - 1:
                self.ib.sleep(12)   # IB pacing: max 60 req / 10 min

        self._close_cache = (
            pd.DataFrame(all_close).dropna(how="all")
            if all_close else pd.DataFrame()
        )
        self._volume_cache = (
            pd.DataFrame(all_volume).dropna(how="all")
            if all_volume else pd.DataFrame()
        )
        log.info(
            f"History fetch complete: {len(all_close)} symbols, "
            f"{len(self._close_cache)} trading days cached."
        )

    def _cached_close(self, tickers: List[str]) -> pd.DataFrame:
        if self._close_cache.empty:
            return pd.DataFrame()
        valid = [t for t in tickers if t in self._close_cache.columns]
        return self._close_cache[valid]

    def _get_avg_dollar_volume(self, tickers: List[str], window: int = 5) -> Dict[str, float]:
        """Average daily dollar volume over the last `window` bars from cache."""
        result: Dict[str, float] = {}
        for t in tickers:
            try:
                vol   = (float(self._volume_cache[t].dropna().tail(window).mean())
                         if t in self._volume_cache.columns else 0.0)
                price = (float(self._close_cache[t].dropna().iloc[-1])
                         if t in self._close_cache.columns else 0.0)
                result[t] = vol * price
            except Exception:
                result[t] = 0.0
        return result

    # ════════════════════════════════════════════════════════════════════════
    # 1. TRAILING STOP CHECK  (daily, 9:40 AM ET)
    # ════════════════════════════════════════════════════════════════════════
    def _check_trailing_stops(self):
        log.info("── Trailing stop check ──────────────────────────────")
        if not self._current_holdings:
            return

        today     = self._today_et()
        prices    = self._snapshot_prices(list(self._current_holdings))
        positions = self._positions()
        to_exit   = []

        for ticker in list(self._current_holdings):
            if positions.get(ticker, 0) == 0:
                continue
            current = prices.get(ticker) or self._single_price(ticker)
            if not current or current <= 0:
                continue

            peak = self._peak_prices.get(ticker, current)
            if current > peak:
                self._peak_prices[ticker] = current
                peak = current

            drawdown = (peak - current) / peak if peak > 0 else 0.0
            if drawdown >= self.TRAILING_STOP:
                to_exit.append((ticker, peak, current, drawdown))

        for ticker, peak, current, drawdown in to_exit:
            self._liquidate(ticker, positions)
            self._cooldown_until[ticker]  = today + timedelta(days=self.COOLDOWN_DAYS)
            self._pending_realloc[ticker] = today + timedelta(days=self.REALLOCATION_DELAY_DAYS)
            self._current_holdings.discard(ticker)
            self._peak_prices.pop(ticker, None)
            log.warning(
                f"TRAILING STOP | {ticker} | "
                f"Peak ${peak:.2f} → Now ${current:.2f} | "
                f"Drawdown {drawdown*100:.1f}% | "
                f"Cooldown until {self._cooldown_until[ticker]} | "
                f"Realloc from {self._pending_realloc.get(ticker)}"
            )

    # ════════════════════════════════════════════════════════════════════════
    # 2. DAILY CHECK  (daily, 10:00 AM ET)
    # ════════════════════════════════════════════════════════════════════════
    def _daily_check(self):
        log.info("── Daily check ──────────────────────────────────────")
        today = self._today_et()

        if self._current_holdings:
            prices    = self._snapshot_prices(list(self._current_holdings))
            positions = self._positions()
            for ticker in list(self._current_holdings):
                if positions.get(ticker, 0) != 0:
                    p = prices.get(ticker, 0.0)
                    if p > 0:
                        self._peak_prices[ticker] = max(
                            self._peak_prices.get(ticker, p), p
                        )

        if self._next_rebal_date is None or today >= self._next_rebal_date:
            self._rebalance()
            self._next_rebal_date = today + timedelta(days=self.REBALANCE_EVERY_DAYS)
        else:
            self._process_pending_reallocations(today)

    # ════════════════════════════════════════════════════════════════════════
    # 3. PENDING REALLOCATION
    # ════════════════════════════════════════════════════════════════════════
    def _process_pending_reallocations(self, today: date):
        due = [t for t, d in self._pending_realloc.items() if today >= d]
        if not due:
            return
        for t in due:
            self._pending_realloc.pop(t, None)

        positions = self._positions()
        active    = [t for t in self._current_holdings if positions.get(t, 0) != 0]
        if not active:
            return

        pv = self._portfolio_value()
        if pv <= 0:
            return

        prices      = self._snapshot_prices(active)
        active_vals = {
            t: abs(prices.get(t, 0.0) * positions.get(t, 0.0))
            for t in active
        }
        active_total = sum(active_vals.values())
        if active_total <= 0:
            return

        raw = {
            t: (active_vals[t] + active_vals[t] / active_total *
                (pv - active_total)) / pv
            for t in active
        }
        weights = self._apply_weight_cap(raw)

        for ticker, w in weights.items():
            self._set_holdings(ticker, w, pv, prices, positions)

        log.info(
            f"REALLOC | Freed: [{', '.join(due)}] → "
            f"Active: [{', '.join(active)}] | "
            f"Weights: { {t: f'{w:.1%}' for t, w in weights.items()} }"
        )

    # ════════════════════════════════════════════════════════════════════════
    # 4. REBALANCE
    # ════════════════════════════════════════════════════════════════════════
    def _rebalance(self):
        log.info("══ REBALANCE ════════════════════════════════════════")
        today          = self._today_et()
        lookback_total = self.LOOKBACK + self.SKIP + 5

        # Pull fresh adjusted-close + volume history from IB for all symbols
        self._fetch_universe_history(lookback_total)

        # SPY 200-day MA regime filter (SPY included in the fetch above)
        bullish       = self._spy_is_bullish()
        cash_fraction = 0.0 if bullish else 0.5

        close = self._cached_close(self.all_tickers)
        if close.empty or close.shape[0] < self.LOOKBACK + self.SKIP:
            log.warning("Insufficient history — skipping rebalance.")
            return

        valid_tickers  = [t for t in self.all_tickers if t in close.columns]
        close_universe = close[valid_tickers]

        scores = self._compute_sharpe_momentum(close_universe)
        if not scores:
            self._liquidate_all()
            return

        # Liquidity filter (price + volume from cache) + cooldown block
        volumes = self._get_avg_dollar_volume(list(scores.keys()))
        scores = {
            t: sc for t, sc in scores.items()
            if (float(self._close_cache[t].dropna().iloc[-1]
                      if t in self._close_cache.columns else 0) >= self.MIN_PRICE
                and volumes.get(t, 0) >= self.MIN_VOLUME
                and today >= self._cooldown_until.get(t, today))
        }
        if not scores:
            self._liquidate_all()
            return

        # Percentile selection
        threshold  = np.percentile(list(scores.values()), self.PERCENTILE * 100)
        candidates = {t: sc for t, sc in scores.items() if sc >= threshold}

        if len(candidates) < self.MIN_HOLDINGS:
            candidates = dict(
                sorted(scores.items(), key=lambda x: x[1], reverse=True)[: self.MIN_HOLDINGS]
            )

        # Rebalance buffer — favour incumbents
        existing  = self._current_holdings & set(candidates)
        new_cands = set(candidates) - self._current_holdings

        if existing:
            weakest  = min(scores.get(t, -999) for t in existing)
            promoted = {t for t in new_cands if scores[t] >= weakest * (1 + self.BUFFER)}
            final_selected = existing | promoted
        else:
            final_selected = set(candidates)

        if len(final_selected) < self.MIN_HOLDINGS:
            for t, _ in sorted(candidates.items(), key=lambda x: x[1], reverse=True):
                final_selected.add(t)
                if len(final_selected) >= self.MIN_HOLDINGS:
                    break

        if not final_selected:
            self._liquidate_all()
            return

        # Inverse-volatility weights
        daily_rets = close_universe.pct_change().dropna()
        weights    = self._inv_vol_weights(list(final_selected), daily_rets)
        weights    = {t: w * (1 - cash_fraction) for t, w in weights.items()}

        # Execute: exit dropped positions first
        pv        = self._portfolio_value()
        positions = self._positions()
        if pv <= 0:
            log.warning("Portfolio value = 0 — aborting rebalance.")
            return

        for ticker, qty in list(positions.items()):
            if qty != 0 and ticker not in final_selected:
                self._liquidate(ticker, positions)
                self._peak_prices.pop(ticker, None)
                self._pending_realloc.pop(ticker, None)

        self.ib.sleep(2)
        pv        = self._portfolio_value()
        positions = self._positions()
        prices_all = self._snapshot_prices(list(final_selected))

        # Enter / adjust positions
        for ticker in final_selected:
            w = weights.get(ticker, 0.0)
            if w <= 0:
                continue
            is_new = ticker not in self._current_holdings
            self._set_holdings(ticker, w, pv, prices_all, positions)
            if is_new:
                p = prices_all.get(ticker, 0.0)
                if p > 0:
                    self._peak_prices[ticker] = p

        self._current_holdings = set(final_selected)
        for t in final_selected:
            self._pending_realloc.pop(t, None)

        # Monthly status log
        if self._last_log_date is None or today.month != self._last_log_date.month:
            self._last_log_date = today
            pv_now    = self._portfolio_value()
            regime    = "BULL" if bullish else "BEAR (50% cash)"
            top3      = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
            top3_str  = ", ".join(f"{t}:{sc:.3f}" for t, sc in top3)
            cooldowns = {t: str(d) for t, d in self._cooldown_until.items() if d > today}
            log.info(
                f"{today} | Regime: {regime} | Value: ${pv_now:,.0f} | "
                f"Holdings: {len(final_selected)} | "
                f"Threshold: {threshold:.4f} | Top3: {top3_str} | "
                f"Cooldowns: {cooldowns} | Next rebal: {self._next_rebal_date}"
            )

    # ════════════════════════════════════════════════════════════════════════
    # HELPERS  (identical logic to the QuantConnect version)
    # ════════════════════════════════════════════════════════════════════════
    def _spy_is_bullish(self) -> bool:
        """SPY 200-day MA regime filter using the IB history cache."""
        if "SPY" in self._close_cache.columns:
            c = self._close_cache["SPY"].dropna().values
            if len(c) >= 200:
                return float(c[-1]) > float(np.mean(c[-200:]))
        return True   # default bullish if cache unavailable

    def _compute_sharpe_momentum(self, close_df: pd.DataFrame) -> dict:
        window = close_df.iloc[: -(self.SKIP)]
        if len(window) < self.LOOKBACK:
            return {}
        window = window.iloc[-self.LOOKBACK:]
        rets   = window.pct_change().dropna()
        scores = {}
        for ticker in rets.columns:
            r   = rets[ticker].dropna().values
            if len(r) < 20:
                continue
            std = float(np.std(r))
            if std == 0:
                continue
            scores[ticker] = float(np.mean(r)) / std
        return scores

    def _inv_vol_weights(self, selected: List[str], daily_rets: pd.DataFrame) -> dict:
        vols = {}
        for t in selected:
            if t in daily_rets.columns:
                r = daily_rets[t].dropna().values
                if len(r) > 5:
                    vols[t] = max(float(np.std(r)), 1e-6)
        if not vols:
            w = 1.0 / len(selected)
            return {t: min(w, self.MAX_WEIGHT) for t in selected}
        inv_v = {t: 1.0 / v for t, v in vols.items()}
        total = sum(inv_v.values())
        return self._apply_weight_cap({t: iv / total for t, iv in inv_v.items()})

    def _apply_weight_cap(self, weights: dict) -> dict:
        """Iteratively redistribute weight above MAX_WEIGHT to uncapped positions."""
        weights = dict(weights)
        for _ in range(10):
            capped   = {t: w for t, w in weights.items() if w >= self.MAX_WEIGHT}
            uncapped = {t: w for t, w in weights.items() if w < self.MAX_WEIGHT}
            if not capped:
                break
            excess = sum(w - self.MAX_WEIGHT for w in capped.values())
            for t in capped:
                weights[t] = self.MAX_WEIGHT
            if uncapped:
                unc_total = sum(uncapped.values())
                for t in uncapped:
                    weights[t] += excess * (uncapped[t] / unc_total)
        return weights

    # ════════════════════════════════════════════════════════════════════════
    # TIME HELPERS
    # ════════════════════════════════════════════════════════════════════════
    def _now_et(self) -> datetime:
        return datetime.now(ET)

    def _today_et(self) -> date:
        return self._now_et().date()

    def _is_weekday(self, d: date) -> bool:
        return d.weekday() < 5   # Mon=0 … Fri=4

    # ════════════════════════════════════════════════════════════════════════
    # MAIN RUN LOOP — 24/7, reconnects automatically on IB Gateway restart
    # ════════════════════════════════════════════════════════════════════════
    def run(self):
        """
        Entry point. Runs forever. Handles:
          - Initial connection (retries until Gateway is up)
          - Automatic reconnection on the IB Gateway daily restart (~11:45 PM ET)
          - All strategy state preserved in memory across disconnects
          - Catch-up on any scheduled events missed during an outage
        """
        log.info("Katana-1 starting up ...")
        while True:
            try:
                self._connect()
                self._event_loop()
            except KeyboardInterrupt:
                log.info("Shutdown requested by user.")
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                sys.exit(0)
            except Exception as e:
                log.error(f"Unhandled error: {e}", exc_info=True)
                log.info(f"Recovering in {self.RECONNECT_DELAY}s ...")
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                time.sleep(self.RECONNECT_DELAY)

    def _event_loop(self):
        """
        Core tick loop (1 s resolution).
        Detects disconnects and calls _reconnect_loop() inline so strategy
        state is never lost. After reconnect, catches up on any missed events.
        """
        log.info("Event loop active — waiting for market events ...")
        while True:
            if not self.ib.isConnected():
                log.warning("IB connection lost — entering reconnect loop ...")
                self._reconnect_loop()
                continue

            try:
                self.ib.sleep(1)
            except Exception as e:
                log.warning(f"ib.sleep() error: {e} — reconnecting ...")
                self._reconnect_loop()
                continue

            now   = self._now_et()
            today = now.date()

            if self._last_event_date != today:
                self._stop_checked_today  = False
                self._daily_checked_today = False
                self._last_event_date     = today

            if not self._is_weekday(today):
                continue

            market_open      = now.replace(hour=9, minute=30, second=0, microsecond=0)
            stop_check_time  = market_open + timedelta(minutes=10)   # 9:40 AM ET
            daily_check_time = market_open + timedelta(minutes=30)   # 10:00 AM ET

            # If offline at 9:40 and reconnect at e.g. 9:55, flag is still False
            # so both events fire immediately on catch-up.
            if not self._stop_checked_today and now >= stop_check_time:
                try:
                    self._check_trailing_stops()
                except Exception as e:
                    log.error(f"Trailing stop error: {e}", exc_info=True)
                finally:
                    self._stop_checked_today = True

            if not self._daily_checked_today and now >= daily_check_time:
                try:
                    self._daily_check()
                except Exception as e:
                    log.error(f"Daily check error: {e}", exc_info=True)
                finally:
                    self._daily_checked_today = True


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    strategy = KatanaStrategy()
    strategy.run()
