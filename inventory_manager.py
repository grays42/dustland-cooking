import os
from ingredient_coder import IngredientCoder

class InventoryManager:
    def __init__(self, coder: IngredientCoder, path: str = "inventory.txt"):
        self.coder = coder
        self.path = path
        self.bitmask = self._load_inventory()

    def _load_inventory(self) -> int:
        if not os.path.exists(self.path):
            return 0

        bitmask = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name in self.coder.ingredient_to_index:
                    bitmask |= self.coder.ingredient_to_bit(name)
        return bitmask

    def _save_inventory(self):
        ingredients = self.coder.int_to_cookjob_tuple(self.bitmask)
        with open(self.path, "w", encoding="utf-8") as f:
            for ing in sorted(ingredients):
                f.write(ing + "\n")

    def add(self, name: str) -> str:
        mask = self.coder.ingredient_to_bit(name)
        if self.bitmask & mask:
            return f"{name} already present"
        self.bitmask |= mask
        self._save_inventory()
        return f"Added {name}"

    def remove(self, name: str) -> str:
        mask = self.coder.ingredient_to_bit(name)
        if not self.bitmask & mask:
            return f"{name} not in inventory"
        self.bitmask &= ~mask
        self._save_inventory()
        return f"Removed {name}"

    def clear(self) -> str:
        self.bitmask = 0
        self._save_inventory()
        return "Inventory cleared."

    def get_current(self) -> list[str]:
        return sorted(self.coder.int_to_cookjob_tuple(self.bitmask))
