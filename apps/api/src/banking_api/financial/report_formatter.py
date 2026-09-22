from decimal import ROUND_HALF_UP, Decimal


class ReportFormatter:
    """Formats display-only values without mutating their source Decimals."""

    _CURRENCY_SYMBOLS = {
        "CNY": "¥",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
    }
    _MONEY_QUANTUM = Decimal("0.01")
    _PERCENT_QUANTUM = Decimal("0.1")

    def money(self, value: Decimal, currency: str) -> str:
        amount = value.quantize(self._MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        symbol = self._CURRENCY_SYMBOLS.get(currency)
        rendered = f"{abs(amount):,.2f}"
        sign = "-" if amount < 0 else ""
        if symbol is not None:
            return f"{sign}{symbol}{rendered}"
        return f"{sign}{rendered} {currency}"

    def money_change(self, value: Decimal, currency: str) -> str:
        if value == 0:
            return self.money(value, currency)
        prefix = "+" if value > 0 else "-"
        return f"{prefix}{self.money(abs(value), currency)}"

    def percentage_change(self, value: Decimal | None) -> str:
        if value is None:
            return self.null()
        rounded = value.quantize(self._PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
        if rounded == 0:
            return "0.0%"
        prefix = "+" if rounded > 0 else ""
        return f"{prefix}{rounded:.1f}%"

    def ratio(self, value: Decimal) -> str:
        percent = (value * Decimal("100")).quantize(
            self._PERCENT_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        return f"{percent:.1f}%"

    @staticmethod
    def null() -> str:
        return "—"
