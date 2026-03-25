from datamodel import TradingState
from trader1 import Trader as CoreTrader


class Trader:
    def __init__(self):
        self._core = CoreTrader()

    def bid(self):
        return self._core.bid()

    def run(self, state: TradingState):
        return self._core.run(state)
