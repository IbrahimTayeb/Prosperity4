import csv
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from datamodel import Listing, Observation, OrderDepth, TradingState
from trader1 import Trader


PRICE_FILES = [
    "prices_round_0_day_-2.csv",
    "prices_round_0_day_-1.csv",
]

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}


@dataclass
class BookRow:
    day: int
    timestamp: int
    product: str
    buy_orders: Dict[int, int]
    sell_orders: Dict[int, int]
    mid: float


def parse_price_file(path: str) -> Dict[int, Dict[str, BookRow]]:
    grouped: Dict[int, Dict[str, BookRow]] = defaultdict(dict)

    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ts = int(row["timestamp"])
            product = row["product"]

            bids: Dict[int, int] = {}
            asks: Dict[int, int] = {}

            for i in (1, 2, 3):
                bp = row.get(f"bid_price_{i}", "")
                bv = row.get(f"bid_volume_{i}", "")
                ap = row.get(f"ask_price_{i}", "")
                av = row.get(f"ask_volume_{i}", "")

                if bp and bv:
                    bids[int(float(bp))] = int(float(bv))
                if ap and av:
                    asks[int(float(ap))] = -abs(int(float(av)))

            grouped[ts][product] = BookRow(
                day=int(row["day"]),
                timestamp=ts,
                product=product,
                buy_orders=bids,
                sell_orders=asks,
                mid=float(row["mid_price"]),
            )

    return grouped


def build_depth(row: BookRow) -> OrderDepth:
    depth = OrderDepth()
    depth.buy_orders = dict(row.buy_orders)
    depth.sell_orders = dict(row.sell_orders)
    return depth


def simulate_cross(order_price: int, qty: int, depth: OrderDepth) -> List[Tuple[int, int]]:
    fills: List[Tuple[int, int]] = []

    if qty > 0:
        remaining = qty
        for ask_px in sorted(depth.sell_orders):
            if ask_px > order_price:
                break
            available = -depth.sell_orders[ask_px]
            traded = min(remaining, available)
            if traded > 0:
                fills.append((ask_px, traded))
                remaining -= traded
            if remaining == 0:
                break

    elif qty < 0:
        remaining = -qty
        for bid_px in sorted(depth.buy_orders, reverse=True):
            if bid_px < order_price:
                break
            available = depth.buy_orders[bid_px]
            traded = min(remaining, available)
            if traded > 0:
                fills.append((bid_px, -traded))
                remaining -= traded
            if remaining == 0:
                break

    return fills


def mark_to_market(cash: float, positions: Dict[str, int], books: Dict[str, BookRow]) -> float:
    value = cash
    for product, pos in positions.items():
        mid = books[product].mid if product in books else 0.0
        value += pos * mid
    return value


def run_backtest_for_file(path: str) -> None:
    grouped = parse_price_file(path)
    trader = Trader()

    trader_data = ""
    cash = 0.0
    positions: Dict[str, int] = {"EMERALDS": 0, "TOMATOES": 0}
    max_abs_pos: Dict[str, int] = {"EMERALDS": 0, "TOMATOES": 0}

    for ts in sorted(grouped):
        books = grouped[ts]
        order_depths = {product: build_depth(row) for product, row in books.items()}

        state = TradingState(
            traderData=trader_data,
            timestamp=ts,
            listings={
                p: Listing(symbol=p, product=p, denomination="XIRECS")
                for p in books.keys()
            },
            order_depths=order_depths,
            own_trades={p: [] for p in books.keys()},
            market_trades={p: [] for p in books.keys()},
            position=dict(positions),
            observations=Observation({}, {}),
        )

        run_result = trader.run(state)
        if isinstance(run_result, tuple):
            result, _, trader_data = run_result
        else:
            result = run_result
            trader_data = ""

        for product, orders in result.items():
            depth = order_depths.get(product)
            if depth is None:
                continue

            for order in orders:
                fills = simulate_cross(order.price, order.quantity, depth)
                for px, q in fills:
                    positions[product] += q
                    cash -= px * q

            max_abs_pos[product] = max(max_abs_pos[product], abs(positions[product]))
            if max_abs_pos[product] > POSITION_LIMITS[product]:
                raise AssertionError(
                    f"Position limit exceeded for {product}: {max_abs_pos[product]} > {POSITION_LIMITS[product]}"
                )

    final_value = mark_to_market(cash, positions, grouped[max(grouped)].copy())

    print()
    print(f"=== {path} ===")
    print(f"Final marked PnL: {final_value:.2f}")
    print(f"Final cash: {cash:.2f}")
    print(f"Final positions: {positions}")
    print(f"Max abs positions: {max_abs_pos}")


def main() -> None:
    for file_name in PRICE_FILES:
        run_backtest_for_file(file_name)


if __name__ == "__main__":
    main()

