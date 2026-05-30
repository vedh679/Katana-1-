# Katana-1 — Known Bugs (Unresolved)

Audited 2026-05-30. Bugs 2 and 3 from the original audit have been fixed.
The items below are the remaining open issues, ordered by severity.

---

## CRITICAL

### BUG 1 — `SKIP = 0` wipes the entire portfolio
**File:** `main.py` — `_compute_sharpe_momentum()` (~line 886)

In Python `-0 == 0`, so `close_df.iloc[:-0]` evaluates to `close_df.iloc[:0]` — an empty
DataFrame. The function returns `{}`, which causes `_rebalance()` to call `_liquidate_all()`.

**Trigger:** Set `SKIP = 0` in `config.py`.

**Fix:**
```python
window = close_df.iloc[: -self.SKIP] if self.SKIP > 0 else close_df
```

---

## HIGH

### BUG 4 — Negative-Sharpe buffer threshold is inverted
**File:** `main.py` — `_rebalance()` (~line 666)

```python
promoted = {t for t in new_cands if scores[t] >= weakest * (1 + self.BUFFER)}
```

Multiplying a negative number by `1.10` makes it *more* negative, lowering the bar for new
entrants rather than raising it. The buffer is supposed to protect incumbents from displacement,
but in a bear market (negative Sharpe scores) it does the opposite.

**Trigger:** Any rebalance where the weakest incumbent has a negative Sharpe score.

**Fix:**
```python
threshold_score = weakest - abs(weakest) * self.BUFFER
promoted = {t for t in new_cands if scores[t] >= threshold_score}
```

---

### BUG 5 — Zombie tickers accumulate in `_current_holdings`
**File:** `main.py` — `_inv_vol_weights()` (~line 902) / `_rebalance()` (~line 716)

When `_inv_vol_weights()` has fewer than 5 return rows for a ticker it silently drops that
ticker from the returned `weights` dict. Back in `_rebalance()`, the ticker gets weight 0.0,
no order is placed, but it is still added to `self._current_holdings`. The ticker then enjoys
incumbent buffer advantage on every future rebalance while holding no shares, potentially
blocking better candidates indefinitely.

**Fix:** After `_inv_vol_weights()` returns, filter `final_selected` to only tickers present
in `weights`, then assign `_current_holdings = set(weights.keys())`.

---

## MEDIUM

### BUG 6 — `reqExecutions()` only returns today's fills; state inference fails after overnight restart
**File:** `main.py` — `_load_state()` (~line 776)

IB's `reqExecutions()` with no filter returns only current-session executions. If the last
rebalance ran yesterday or earlier and the state file is missing, `fills` is empty, inference
silently fails, and the strategy schedules a spurious rebalance at the next 10:00 AM ET.

**Trigger:** Delete `katana_state.json` and restart the day after a rebalance.

**Fix:** Either pass an `ExecutionFilter` with `time` set back far enough (e.g., 30 days), or
log an explicit warning that dates could not be inferred and a fresh rebalance will be scheduled.

---

### BUG 7 — `_apply_weight_cap` silently discards weight when every ticker exceeds the cap
**File:** `main.py` — `_apply_weight_cap()` (~line 920)

If all tickers are above `MAX_WEIGHT` simultaneously the `uncapped` dict is empty, the computed
`excess` is never redistributed, and the returned weights sum to less than 1.0. The portfolio
is silently under-invested by the lost fraction.

**Trigger:** Small `final_selected` cohort (e.g., 3 tickers) with equal volatility and a
`MAX_WEIGHT` below `1 / n_tickers`. Default config (MIN_HOLDINGS = 5, MAX_WEIGHT = 0.20)
makes this unreachable today, but any config reduction exposes it.

**Fix:** After the loop, if `sum(weights.values()) < 1.0 - 1e-9`, log a warning. Optionally
re-scale or distribute the residual equally across all capped positions.

---

### BUG 8 — Inverse-volatility window does not match the momentum scoring window
**File:** `main.py` — `_rebalance()` (~line 682)

```python
daily_rets = close_universe.pct_change().dropna()   # full multi-year history
weights    = self._inv_vol_weights(list(final_selected), daily_rets)
```

Momentum scores are computed over the last `LOOKBACK` days (skipping `SKIP`), but the
volatility used for position sizing is computed over the **entire fetched history** (up to 2
years). A stock that was volatile 18 months ago but calm recently will be underweighted
relative to its current risk.

**Fix:**
```python
skip_slice = -self.SKIP if self.SKIP > 0 else len(close_universe)
daily_rets = close_universe.iloc[:skip_slice].iloc[-self.LOOKBACK:].pct_change().dropna()
```

---

## MINOR / COSMETIC

### M1 — Double `_portfolio_value()` call on startup
**File:** `main.py` — `_display_startup()` (~line 801)

`_portfolio_value()` is called twice during `_display_startup()` (once at the top, once
implicitly). Each call retries for up to 10 seconds. Low impact but adds latency on cold start.

---

### M2 — P&L prints before market open and after market close on weekdays
**File:** `main.py` — `_event_loop()` (~line 1031)

The P&L display block has no market-hours guard. It will print at e.g. 7:00 AM ET using stale
overnight prices. Cosmetic issue only.

---

### M3 — Adding "SPY" to any sector list in `config.py` causes double-counting
**File:** `config.py` / `main.py` — `_build_universe()` (~line 129)

SPY is added to `self.contracts` unconditionally as the regime-filter ticker. If a user also
adds "SPY" to a sector list, SPY becomes both a momentum candidate and the regime filter,
influencing its own regime signal.

---

### M4 — Peak prices not refreshed after a long reconnect outage
**File:** `main.py` — `_reconnect_loop()` (~line 232)

`_reconnect_loop()` calls `_qualify_contracts()` but not `_sync_state_from_ib()`. After a
prolonged outage where IB positions changed externally (e.g., manual intervention in TWS),
`_peak_prices` would reflect pre-outage prices and the trailing stop could fire or fail to
fire incorrectly on the next check.
