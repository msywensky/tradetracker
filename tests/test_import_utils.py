from __future__ import annotations

import unittest

from tracker.services.import_utils import (
    infer_symbol_from_notes,
    normalize_header,
    parse_datetime,
    parse_int,
    parse_money,
)


class ImportUtilsTests(unittest.TestCase):
    def test_infer_symbol_from_notes_matches_supported_tickers(self) -> None:
        self.assertEqual(infer_symbol_from_notes("Opened spy calls"), "SPY")
        self.assertEqual(infer_symbol_from_notes("Sold TSLA puts"), "TSLA")
        self.assertEqual(infer_symbol_from_notes("msft scalp"), "MSFT")
        self.assertEqual(infer_symbol_from_notes("NBIS lotto"), "NBIS")

    def test_infer_symbol_from_notes_defaults_to_unk(self) -> None:
        self.assertEqual(infer_symbol_from_notes("No ticker here"), "UNK")
        self.assertEqual(infer_symbol_from_notes(""), "UNK")

    def test_parse_money_supports_currency_and_parentheses(self) -> None:
        self.assertEqual(parse_money("$1,234.56"), 1234.56)
        self.assertEqual(parse_money("(123.45)"), -123.45)
        self.assertIsNone(parse_money(""))

    def test_parse_int_and_header_normalization(self) -> None:
        self.assertEqual(parse_int("1,234"), 1234)
        self.assertIsNone(parse_int(""))
        self.assertEqual(normalize_header("  Avg   Buy  "), "avg buy")

    def test_parse_datetime_with_and_without_year(self) -> None:
        dt_full = parse_datetime("2026-02-15 14:35", default_year=None)
        self.assertIsNotNone(dt_full)
        self.assertEqual(dt_full.year, 2026)

        dt_partial = parse_datetime("02/15 10:59 AM", default_year=2026)
        self.assertIsNotNone(dt_partial)
        self.assertEqual(dt_partial.year, 2026)


if __name__ == "__main__":
    unittest.main()
