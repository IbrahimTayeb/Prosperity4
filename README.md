# Prosperity Round 0 Starter (with local backtest)

This workspace now includes:

- `trader1.py`: main submission-ready `Trader` implementation.
- `starter.py`: thin wrapper that delegates to `trader1.Trader`.
- `datamodel.py`: local-compatible datamodel classes.
- `backtest.py`: lightweight replay/backtest on provided price CSVs.

## Strategy overview

The trader uses two components:

1. **Fair value estimation**
   - `EMERALDS`: anchored near 10000, with a small pull toward current midpoint.
   - `TOMATOES`: rolling mean of recent mid prices (mean-reversion).
2. **Execution logic**
   - Aggressively crosses quotes when edge vs fair value is favorable.
   - Places inventory-aware passive quotes with skewed prices/sizes to reduce risk.

All orders are size-limited by per-product position limits.

## Quick run

```bash
python3 backtest.py
```

## Notes

- The local backtest is intentionally simple: it only simulates immediate fills against current top-of-book levels.
- Passive order fills by bots are not modeled, so this backtest is mainly a quick sanity check.

