from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping

# Minimum match score for auto-selecting an account. Below this the preview
# leaves the account unselected so the user picks it explicitly.
ACCOUNT_MATCH_THRESHOLD = 0.5

VALID_SIDES = {"BUY", "SELL"}
VALID_OPTION_TYPES = {"CALL", "PUT"}


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def match_account(label: str, accounts: Iterable[Mapping[str, Any]]) -> int | None:
    """Return the id of the account whose full_name best matches ``label``.

    Compares against each account's full_name using a fuzzy ratio and returns the best
    match above ACCOUNT_MATCH_THRESHOLD, else None.
    """
    target = _normalize(label)
    if not target:
        return None

    target_tokens = set(target.split())
    best_id: int | None = None
    best_score = 0.0
    for account in accounts:
        full_name = _normalize(account["full_name"])
        name_tokens = set(full_name.split())
        # Primary signal: fraction of the account's name words present in the label
        # (e.g. "rollover ira *5675" contains both words of "rollover ira" -> 1.0).
        if name_tokens and target_tokens:
            score = len(target_tokens & name_tokens) / len(name_tokens)
        else:
            score = 0.0
        # Only when there is no token overlap, fall back to a discounted character ratio
        # so near-identical-but-untokenizable labels can still match weakly.
        if score == 0.0:
            score = SequenceMatcher(None, target, full_name).ratio() * 0.5
        if score > best_score:
            best_score = score
            best_id = int(account["id"])

    return best_id if best_score >= ACCOUNT_MATCH_THRESHOLD else None


def _coerce_fill(raw: Mapping[str, Any]) -> dict | None:
    """Validate and normalize a single fill from the LLM. Returns None if unusable."""
    side = str(raw.get("side", "")).strip().upper()
    option_type = str(raw.get("option_type", "")).strip().upper()
    underlying = str(raw.get("underlying", "")).strip().upper()
    if side not in VALID_SIDES or option_type not in VALID_OPTION_TYPES or not underlying:
        return None

    try:
        contracts = int(raw.get("contracts"))
        price_per_share = float(raw.get("price_per_share"))
    except (TypeError, ValueError):
        return None
    if contracts <= 0 or price_per_share <= 0:
        return None

    strike = raw.get("strike")
    if strike is not None:
        try:
            strike = float(strike)
        except (TypeError, ValueError):
            strike = None

    return {
        "underlying": underlying,
        "option_type": option_type,
        "expiration": (str(raw.get("expiration")).strip() or None) if raw.get("expiration") else None,
        "strike": strike,
        "side": side,
        "contracts": contracts,
        # Fidelity shows per-share prices; entries.price is per-contract (x100).
        "price": round(price_per_share * 100, 2),
        "timestamp": (str(raw.get("timestamp")).strip() or None) if raw.get("timestamp") else None,
        "account_label": str(raw.get("account_label", "")).strip(),
    }


def build_preview(
    fills: Iterable[Mapping[str, Any]],
    accounts: Iterable[Mapping[str, Any]],
) -> list[dict]:
    """Group validated fills into trade dicts ready for review and commit.

    Each trade groups fills sharing (account, underlying, option_type, expiration, strike).
    Returns a list of trade dicts with an ``entries`` list, a matched ``account_id``, the
    earliest fill time as ``created_at``, and a computed OPEN/CLOSED ``status``.
    """
    accounts = list(accounts)
    account_short_by_id = {int(a["id"]): a["short_name"] for a in accounts}

    grouped: dict[tuple, dict] = {}
    order: list[tuple] = []
    for raw in fills:
        fill = _coerce_fill(raw)
        if fill is None:
            continue

        account_id = match_account(fill["account_label"], accounts)
        key = (
            account_id,
            fill["underlying"],
            fill["option_type"],
            fill["expiration"],
            fill["strike"],
        )
        if key not in grouped:
            grouped[key] = {
                "symbol": fill["underlying"],
                "option_type": fill["option_type"],
                "expiration": fill["expiration"],
                "strike": fill["strike"],
                "account_id": account_id,
                "account_short": account_short_by_id.get(account_id),
                "account_label": fill["account_label"],
                "created_at": fill["timestamp"],
                "entries": [],
            }
            order.append(key)

        trade = grouped[key]
        # Keep the earliest fill timestamp as the trade's created_at.
        if fill["timestamp"] and (trade["created_at"] is None or fill["timestamp"] < trade["created_at"]):
            trade["created_at"] = fill["timestamp"]
        trade["entries"].append(
            {
                "side": fill["side"],
                "contracts": fill["contracts"],
                "price": fill["price"],
                "created_at": fill["timestamp"],
            }
        )

    trades = []
    for key in order:
        trade = grouped[key]
        net = sum(
            e["contracts"] if e["side"] == "BUY" else -e["contracts"] for e in trade["entries"]
        )
        trade["status"] = "OPEN" if net != 0 else "CLOSED"
        trades.append(trade)

    return trades
