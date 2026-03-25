from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Optional, Tuple
import json
import statistics


class Trader:
    POSITION_LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    EMERALD_ANCHOR = 10000.0
    EMERALD_TAKE_EDGE = 1.0
    TOMATO_WINDOW = 40
    TOMATO_TAKE_EDGE = 1.5
    TOMATO_SOFT_LIMIT = 60

    def bid(self):
        return 15

    def _mid(self, depth: OrderDepth) -> Optional[float]:
        if not depth.buy_orders or not depth.sell_orders:
            return None
        return (max(depth.buy_orders) + min(depth.sell_orders)) / 2.0

    def _inventory_skew(self, position: int, limit: int) -> float:
        if limit <= 0:
            return 0.0
        return position / float(limit)

    def _fair_value(
        self,
        product: str,
        depth: OrderDepth,
        tomato_mids: List[float],
        tomato_fast_ema: Optional[float],
        tomato_slow_ema: Optional[float],
    ) -> Tuple[Optional[float], Optional[float], Optional[float], float]:
        if product == "EMERALDS":
            mid = self._mid(depth)
            if mid is None:
                return self.EMERALD_ANCHOR, tomato_fast_ema, tomato_slow_ema, 0.0
            return 0.85 * self.EMERALD_ANCHOR + 0.15 * mid, tomato_fast_ema, tomato_slow_ema, 0.0

        if product == "TOMATOES":
            mid = self._mid(depth)
            if mid is not None:
                tomato_mids.append(mid)
                if tomato_fast_ema is None:
                    tomato_fast_ema = mid
                else:
                    tomato_fast_ema = 0.35 * mid + 0.65 * tomato_fast_ema

                if tomato_slow_ema is None:
                    tomato_slow_ema = mid
                else:
                    tomato_slow_ema = 0.08 * mid + 0.92 * tomato_slow_ema

            if len(tomato_mids) > self.TOMATO_WINDOW:
                tomato_mids[:] = tomato_mids[-self.TOMATO_WINDOW :]
            if tomato_fast_ema is not None and tomato_slow_ema is not None:
                trend = tomato_fast_ema - tomato_slow_ema
                base = statistics.mean(tomato_mids) if len(tomato_mids) >= 5 else tomato_slow_ema
                fair = 0.7 * base + 0.3 * tomato_fast_ema
                return fair, tomato_fast_ema, tomato_slow_ema, trend
            return mid, tomato_fast_ema, tomato_slow_ema, 0.0

        return None, tomato_fast_ema, tomato_slow_ema, 0.0

    def _aggressive_orders(
        self,
        product: str,
        depth: OrderDepth,
        fair: float,
        position: int,
        limit: int,
        trend: float,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        buy_capacity = limit - position
        sell_capacity = limit + position

        edge = self.EMERALD_TAKE_EDGE if product == "EMERALDS" else self.TOMATO_TAKE_EDGE
        buy_enabled = True
        sell_enabled = True
        if product == "TOMATOES":
            # Avoid repeatedly fading strong directional moves.
            if trend < -1.0:
                buy_enabled = False
            elif trend > 1.0:
                sell_enabled = False
            edge += min(1.5, abs(trend) * 0.35)

            # Cap one-iteration TOMATOES aggression to reduce runaway inventory.
            buy_capacity = min(buy_capacity, 8)
            sell_capacity = min(sell_capacity, 8)

        if buy_enabled:
            for ask_price in sorted(depth.sell_orders):
                if ask_price >= fair - edge:
                    break
                ask_volume = -depth.sell_orders[ask_price]
                qty = min(ask_volume, buy_capacity)
                if qty <= 0:
                    break
                orders.append(Order(product, ask_price, qty))
                buy_capacity -= qty

        if sell_enabled:
            for bid_price in sorted(depth.buy_orders, reverse=True):
                if bid_price <= fair + edge:
                    break
                bid_volume = depth.buy_orders[bid_price]
                qty = min(bid_volume, sell_capacity)
                if qty <= 0:
                    break
                orders.append(Order(product, bid_price, -qty))
                sell_capacity -= qty

        return orders, buy_capacity, sell_capacity

    def _passive_quotes(
        self,
        product: str,
        fair: float,
        position: int,
        limit: int,
        buy_capacity: int,
        sell_capacity: int,
        trend: float,
    ) -> List[Order]:
        orders: List[Order] = []
        skew = self._inventory_skew(position, limit)

        half_spread = 2 if product == "EMERALDS" else 3
        bid_px = int(round(fair - half_spread - 2.0 * skew))
        ask_px = int(round(fair + half_spread - 2.0 * skew))
        if bid_px >= ask_px:
            ask_px = bid_px + 1

        quote_size = 6 if abs(skew) < 0.5 else 3
        if product == "TOMATOES" and abs(position) >= self.TOMATO_SOFT_LIMIT:
            quote_size = 2

        if product == "TOMATOES":
            # Shift TOMATOES quotes with trend to reduce adverse selection.
            trend_shift = max(-2, min(2, int(round(trend))))
            bid_px += trend_shift
            ask_px += trend_shift
            if bid_px >= ask_px:
                ask_px = bid_px + 1

        if buy_capacity > 0:
            orders.append(Order(product, bid_px, min(quote_size, buy_capacity)))
        if sell_capacity > 0:
            orders.append(Order(product, ask_px, -min(quote_size, sell_capacity)))

        return orders

    def run(self, state: TradingState):
        try:
            saved: Dict[str, List[float]] = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            saved = {}

        tomato_mids: List[float] = saved.get("tomato_mids", [])
        tomato_fast_ema: Optional[float] = saved.get("tomato_fast_ema")
        tomato_slow_ema: Optional[float] = saved.get("tomato_slow_ema")
        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            limit = self.POSITION_LIMITS.get(product)
            if limit is None:
                result[product] = []
                continue

            position = state.position.get(product, 0)
            fair, tomato_fast_ema, tomato_slow_ema, trend = self._fair_value(
                product,
                depth,
                tomato_mids,
                tomato_fast_ema,
                tomato_slow_ema,
            )
            if fair is None:
                result[product] = []
                continue

            aggressive, buy_cap, sell_cap = self._aggressive_orders(product, depth, fair, position, limit, trend)
            passive = self._passive_quotes(product, fair, position, limit, buy_cap, sell_cap, trend)
            result[product] = aggressive + passive

        trader_data = json.dumps(
            {
                "tomato_mids": tomato_mids,
                "tomato_fast_ema": tomato_fast_ema,
                "tomato_slow_ema": tomato_slow_ema,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data
