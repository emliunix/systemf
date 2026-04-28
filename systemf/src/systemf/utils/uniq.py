class Uniq:
    def __init__(self, start: int | None = None):
        if start is not None:
            self.uniq = start
        else:
            self.uniq = 0

    def make_uniq(self) -> int:
        n = self.uniq
        self.uniq += 1
        return n

UNIQ = Uniq()
