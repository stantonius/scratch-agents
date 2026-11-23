TAX = 0.2


def with_tax(amount: float) -> float:
    "Add tax to `amount`."
    return round(amount * (1 + TAX), 2)
