from acme.pricing import with_tax


class Order:
    def __init__(self, items): self.items = items

    def subtotal(self):
        return sum(price * qty for price, qty in self.items)


def order_total(order: Order) -> float:
    "Total for `order`, tax included."
    return with_tax(order.subtotal())
