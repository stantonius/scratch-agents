class Account:
    "A balance that can be read and set."
    def __init__(self): self._balance = 0

    @property
    def balance(self):
        return self._balance

    @balance.setter
    def balance(self, value):
        self._balance = value
