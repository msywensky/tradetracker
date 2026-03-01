from __future__ import annotations

from typing import Any, Iterable, Mapping


def compute_trade_stats(entries: Iterable[Mapping[str, Any]], fee_per_contract: float) -> dict:
    buy_contracts = 0
    sell_contracts = 0
    buy_total = 0
    sell_total = 0

    for entry in entries:
        contracts = int(entry["contracts"])
        price = float(entry["price"])
        if entry["side"] == "BUY":
            buy_contracts += contracts
            buy_total += contracts * price
        else:
            sell_contracts += contracts
            sell_total += contracts * price

    total_contracts = buy_contracts + sell_contracts
    avg_buy = (buy_total / buy_contracts) if buy_contracts else 0
    avg_sell = (sell_total / sell_contracts) if sell_contracts else 0
    pnl_before = sell_total - buy_total
    fees = total_contracts * fee_per_contract
    pnl_after = pnl_before - fees
    # Use the larger of buy/sell total as denominator so percent is meaningful
    # for both debit (buy_total > sell_total) and credit (sell_total > buy_total) strategies.
    gross = max(buy_total, sell_total)
    percent = (pnl_before / gross * 100) if gross else 0

    return {
        "buy_contracts": buy_contracts,
        "sell_contracts": sell_contracts,
        "total_contracts": total_contracts,
        "avg_buy": avg_buy,
        "avg_sell": avg_sell,
        "pnl_before": pnl_before,
        "fees": fees,
        "pnl_after": pnl_after,
        "percent": percent,
    }
