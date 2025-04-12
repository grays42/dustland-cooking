import json
import os

from ingredient_coder import IngredientCoder
from recipe_manager import RecipeManager
from cookjob_stats_cache import CookjobStatsCache
from cookjob_reporter import CookjobReporter
from console_handler import ConsoleHandler

STATE_PATH = "user_state.json"

def load_inventory() -> int:
    if not os.path.exists(STATE_PATH):
        return 0
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)
    ingredients = state.get("inventory", [])
    bitmask = 0
    for name in ingredients:
        if name in IngredientCoder.ingredient_to_index:
            bitmask |= IngredientCoder.ingredient_to_bit(name)
    return bitmask

def save_inventory(bitmask: int):
    ingredients = sorted(IngredientCoder.int_to_cookjob_tuple(bitmask))
    state = {"inventory": ingredients}
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def main():
    recipe_manager = RecipeManager()
    stats_cache = CookjobStatsCache(recipe_manager)
    stats_cache.load_or_build()
    reporter = CookjobReporter(recipe_manager, stats_cache)

    handler = ConsoleHandler(recipe_manager, reporter, stats_cache)

    while True:
        handler.run_loop()


if __name__ == "__main__":
    main()
