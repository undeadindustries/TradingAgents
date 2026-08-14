import logging
from typing import Dict, Any

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError

logger = logging.getLogger(__name__)

class AlpacaExecutor:
    """Executes Portfolio Manager decisions against the Alpaca API using a fixed position sizing strategy."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("alpaca_api_key")
        self.secret_key = config.get("alpaca_secret_key")
        self.paper = config.get("alpaca_paper", True)
        self.execute_trades = config.get("execute_trades", False)

        self.client = None
        if self.execute_trades:
            if not self.api_key or not self.secret_key:
                logger.error("EXECUTE_TRADES is True, but Alpaca credentials are missing in config.")
                self.execute_trades = False
            else:
                try:
                    self.client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
                    account = self.client.get_account()
                    logger.info(f"Connected to Alpaca. Paper mode: {self.paper}. Buying Power: ${account.buying_power}")
                except Exception as e:
                    logger.error(f"Failed to connect to Alpaca API: {e}")
                    self.execute_trades = False

    def execute_rating(self, ticker: str, rating: str) -> None:
        """Translates the 5-tier rating into a fixed-sizing trade and executes it."""
        if not self.execute_trades or not self.client:
            logger.info(f"Execution disabled. Would have executed rating '{rating}' for {ticker}.")
            return

        try:
            account = self.client.get_account()
            buying_power = float(account.buying_power)

            # Check if we currently hold a position
            position = None
            try:
                position = self.client.get_open_position(ticker)
            except APIError as e:
                if e.status_code != 404:
                    raise e
            
            # Implementation of the Risk-Managed Fixed Allocation strategy
            if rating == "Buy":
                # Buy 5% of total buying power
                notional_amount = buying_power * 0.05
                self._place_notional_buy(ticker, notional_amount)
                
            elif rating == "Overweight":
                # Buy 2.5% of total buying power
                notional_amount = buying_power * 0.025
                self._place_notional_buy(ticker, notional_amount)
                
            elif rating == "Underweight":
                # Sell 50% of the existing position
                if position:
                    current_qty = float(position.qty)
                    sell_qty = current_qty / 2.0
                    self._place_qty_sell(ticker, sell_qty)
                else:
                    logger.warning(f"Rating is Underweight for {ticker}, but no open position exists. Ignoring.")
                    
            elif rating == "Sell":
                # Liquidate entire position
                if position:
                    logger.info(f"Liquidating entire position for {ticker}.")
                    self.client.close_position(ticker)
                else:
                    logger.warning(f"Rating is Sell for {ticker}, but no open position exists. Ignoring.")
                    
            elif rating == "Hold":
                logger.info(f"Rating is Hold for {ticker}. No action taken.")
            else:
                logger.warning(f"Unknown rating '{rating}' received for {ticker}. No execution performed.")

        except Exception as e:
            logger.error(f"Error executing trade for {ticker} with rating {rating}: {e}")

    def _place_notional_buy(self, ticker: str, notional_amount: float) -> None:
        """Helper to place a notional (fractional dollar) buy order."""
        # Alpaca requires notional amounts to be rounded to 2 decimal places usually
        notional_amount = round(notional_amount, 2)
        if notional_amount < 1.0:
             logger.warning(f"Calculated notional amount ${notional_amount} for {ticker} is too small to trade.")
             return
             
        logger.info(f"Placing BUY order for {ticker} at notional value ${notional_amount}")
        request = MarketOrderRequest(
            symbol=ticker,
            notional=notional_amount,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        self.client.submit_order(order_data=request)

    def _place_qty_sell(self, ticker: str, qty: float) -> None:
        """Helper to place a quantity-based sell order."""
        # Ensure precision limits for fractional shares (typically up to 9 decimal places in Alpaca, let's round to 5 to be safe)
        qty = round(qty, 5)
        if qty <= 0:
            logger.warning(f"Calculated sell quantity {qty} for {ticker} is invalid.")
            return

        logger.info(f"Placing SELL order for {ticker} for {qty} shares")
        request = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
        self.client.submit_order(order_data=request)
