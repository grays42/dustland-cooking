import json
import os

"""
ingredient_coder.py:

Class IngredientCoder
Utility class for converting between human-readable ingredient names and
compressed integer representations using bitmask encoding.

Loads valid ingredients from 'data.json' under the 'valid_ingredients' key
at module load time. Ingredient list is static and version-locked
for the system.

Class Methods:
- ingredient_to_bit(ingredient: str) -> int
- bit_to_ingredient(bit: int) -> str
- cookjob_tuple_to_int(ingredients: tuple[str, ...]) -> int
- int_to_cookjob_tuple(compressed: int) -> tuple[str, ...]
- cookjob_contains(compressed: int, ingredient: str) -> bool
"""

# Load ingredients at module level
with open("data.json", "r") as f:
    _data = json.load(f)
    _ingredients = _data["valid_ingredients"]

class IngredientCoder:
    ingredients = _ingredients
    ingredient_to_index = {name: i for i, name in enumerate(ingredients)}
    index_to_ingredient = ingredients
    max_bits = len(ingredients)

    @classmethod
    def ingredient_to_bit(cls, ingredient: str) -> int:
        return 1 << cls.ingredient_to_index[ingredient]

    @classmethod
    def bit_to_ingredient(cls, bit: int) -> str:
        index = bit.bit_length() - 1
        return cls.index_to_ingredient[index]

    @classmethod
    def cookjob_tuple_to_int(cls, ingredients: tuple[str, ...]) -> int:
        result = 0
        for ing in ingredients:
            result |= 1 << cls.ingredient_to_index[ing]
        return result

    @classmethod
    def int_to_cookjob_tuple(cls, compressed: int) -> tuple[str, ...]:
        return tuple(
            cls.index_to_ingredient[i]
            for i in range(cls.max_bits)
            if compressed & (1 << i)
        )

    @classmethod
    def cookjob_contains(cls, cookjob: int, ingredient: str) -> bool:
        return bool(cookjob & (1 << cls.ingredient_to_index[ingredient]))


import unittest

class TestIngredientCoder(unittest.TestCase):

    def test_ingredient_to_bit(self):
        bit = IngredientCoder.ingredient_to_bit("Salt")
        #print(f"salt -> bit: {bit}")
        self.assertEqual(bit, 16384) 

    def test_bit_to_ingredient(self):
        ingredient = IngredientCoder.bit_to_ingredient(4)
        #print(f"bit 4 -> ingredient: {ingredient}")
        self.assertEqual(ingredient, "Liquor")

    def test_cookjob_tuple_to_int(self):
        cookjob = ("Salt", "Bread", "Water")
        encoded = IngredientCoder.cookjob_tuple_to_int(cookjob)
        #print(f"{cookjob} -> int: {encoded}")
        self.assertEqual(encoded, 281474976727041)

    def test_int_to_cookjob_tuple(self):
        compressed = 281474976727041
        ingredients = IngredientCoder.int_to_cookjob_tuple(compressed)
        #print(f"{compressed} -> tuple: {ingredients}")
        self.assertEqual(set(ingredients), {"Water", "Salt", "Bread"})

    def test_cookjob_contains(self):
        cookjob = IngredientCoder.cookjob_tuple_to_int(("Salt", "Eggs"))
        #print(f"cookjob int: {cookjob}, contains 'butter'? True, contains 'pepper'? False")
        self.assertTrue(IngredientCoder.cookjob_contains(cookjob, "Salt"))
        self.assertFalse(IngredientCoder.cookjob_contains(cookjob, "Bread"))

if __name__ == "__main__":
    unittest.main()
