from __future__ import annotations

import json
import os

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Anthropic vision accepts these image media types.
SUPPORTED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

EXTRACTION_PROMPT = """You are reading a screenshot of a Fidelity options order/activity table.

The columns are: Symbol, Action, Amou (Amount), Status, Order Type, Filled, Last, Bid, Mid, Ask, \
Order Time, Account.

Extract every qualifying fill into JSON. Apply these rules exactly:

1. Action: include ONLY rows whose action is "Buy to Open Call", "Buy to Open Put",
   "Sell to Close Call", or "Sell to Close Put". Map "Buy to Open ..." to side "BUY" and
   "Sell to Close ..." to side "SELL". IGNORE "Sell to Open" and "Buy to Close" rows entirely.

2. Status: include ONLY rows whose Status is "Filled at $x.xx". The "$x.xx" is the per-share fill
   price -> put it in "price_per_share". IGNORE rows whose status is "Verified Canceled", "Open",
   or anything that is not a filled price.

3. Symbol: the Symbol cell (e.g. "-QQQ260617C734") encodes the contract. Parse it into:
   - "underlying": the ticker letters. Common tickers include "SPY", "QQQ", "MSFT", "NBIS", "TSLA".
   - "expiration": the 6-digit YYMMDD as an ISO date "YYYY-MM-DD" (e.g. 260617 -> "2026-06-17")
   - "option_type": "CALL" if the letter after the date is C, "PUT" if P
   - "strike": the trailing number as a number (e.g. 734, 400)

4. Amou: the number of contracts -> "contracts" (an integer). Ignore the "Filled" column (e.g. "10/10").

5. Order Time: e.g. "1:51:44 PM ET Jun-16-2026" -> "timestamp" as "YYYY-MM-DD HH:MM:SS" in 24-hour
   time (e.g. "2026-06-16 13:51:44"). Drop the timezone.

6. Account: the Account cell (e.g. "Rollover IRA *5675") -> "account_label" verbatim.

Return ONLY a JSON object, no prose and no code fences, of this exact shape:
{"fills": [
  {"underlying": "QQQ", "option_type": "CALL", "expiration": "2026-06-17", "strike": 734,
   "side": "SELL", "contracts": 10, "price_per_share": 4.82,
   "timestamp": "2026-06-16 13:51:44", "account_label": "Rollover IRA *5675"}
]}
If there are no qualifying rows, return {"fills": []}."""


class AnthropicConfigError(RuntimeError):
    """Raised when the API key is missing or the client cannot be created."""


class AnthropicExtractionError(RuntimeError):
    """Raised when the API call fails or the response is not parseable JSON."""


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence (optionally with a language tag) and the closing fence.
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -3]
    return stripped.strip()


def extract_fills_from_image(
    image_b64: str,
    media_type: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Send a base64 image to Claude (Haiku) and return the parsed extraction dict.

    The returned dict has the shape {"fills": [ ... ]}. Raises AnthropicConfigError if the
    API key is missing, or AnthropicExtractionError if the request or JSON parse fails.
    """
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise AnthropicExtractionError(f"Unsupported image type: {media_type}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AnthropicConfigError(
            "ANTHROPIC_API_KEY is not set. Set it in your environment and restart the app."
        )

    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise AnthropicConfigError(
            "The 'anthropic' package is not installed. Run: pip install -r requirements.txt"
        ) from exc

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001 - surface any SDK/transport error uniformly
        raise AnthropicExtractionError(f"Claude API request failed: {exc}") from exc

    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    try:
        parsed = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, TypeError) as exc:
        raise AnthropicExtractionError("Claude did not return valid JSON.") from exc

    if not isinstance(parsed, dict) or not isinstance(parsed.get("fills"), list):
        raise AnthropicExtractionError("Claude response was missing a 'fills' list.")

    return parsed
