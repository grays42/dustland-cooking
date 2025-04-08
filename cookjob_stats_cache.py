import os
import json
import pandas as pd
from ingredient_coder import IngredientCoder
from recipe_manager import RecipeManager

"""
cookjob_stats_cache.py

Class CookjobStatsCache
Builds and maintains a cache of calculated statistics for each valid cookjob,
using known per-ingredient stat contributions. Intended to support fast filtering,
ranking, and reporting for crafting optimization.

Caches are saved to disk as JSON and can be loaded, rebuilt, or queried via
convenient accessors. Data is also exposed via a pandas DataFrame for flexible
analysis and reporting.

Initialization requires:
- A RecipeManager instance to retrieve cookjobs and resolve recipe names/IDs.
- An IngredientCoder to decode cookjob bitmasks into human-readable tuples.

Stat calculations are derived from per-ingredient values stored in data.json
under "ingredient_stats", including hunger, stress, and sell_value.

Computed fields include:
- hunger: total hunger value from all known ingredients
- stress: total stress value
- sell_value: total market value
- travel_score: sum of hunger + stress (for travel food ranking)
- missing_ingredients: list of any ingredients lacking stat data
- all_stats_known: True if all ingredient values are known
- profitability: (placeholder for future use)
- recipe_id / recipe_name / ingredients (for display)

Instance Methods:
- load_or_build()
    Loads cache from disk if present, otherwise builds and saves a new one.

- rebuild_and_save()
    Force rebuilds the entire cache from current recipe/ingredient data,
    then writes to disk.

- get_stats_for_cookjob(cookjob_int: int) -> dict
    Returns the cached stats dict for a specific cookjob.

- get_dataframe() -> pandas.DataFrame
    Returns the full cache as a pandas DataFrame (lazy-loaded).
    Useful for filtering, sorting, and tabular report generation.
"""

class CookjobStatsCache:
    def __init__(self, recipe_manager: RecipeManager, cache_dir="cache"):
        self.recipe_manager = recipe_manager
        self.cache_path = os.path.join(cache_dir, "cookjob_stats.json")
        self.cache = {}  # cookjob_int -> stat dict
        self.df = None  # pandas DataFrame version (lazy-loaded)

    def load_or_build(self):
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r") as f:
                self.cache = {int(k): v for k, v in json.load(f).items()}
        else:
            self.rebuild_and_save()

    def rebuild_and_save(self):
        print("Rebuilding cookjob stats cache...")

        with open("data.json", "r", encoding="utf-8") as f:
            full_data = json.load(f)
        ing_stats = full_data.get("ingredient_stats", {})

        result = {}

        for cookjob in self.recipe_manager.valid_cookjobs:
            ingredients = IngredientCoder.int_to_cookjob_tuple(cookjob)
            hunger = stress = sell = 0
            missing = []

            for ing in ingredients:
                stats = ing_stats.get(ing, {})
                h = stats.get("hunger", 0)
                s = stats.get("stress", 0)
                v = stats.get("sell_value", 0)

                if any(k not in stats for k in ["hunger", "stress", "sell_value"]):
                    missing.append(ing)

                hunger += h
                stress += s
                sell += v

            all_known = len(missing) == 0
            recipe_id = self.recipe_manager.get_recipe_id_for_cookjob(cookjob)
            recipe_name = self.recipe_manager.get_recipe_name_by_id(recipe_id)

            entry = {
                "ingredients": list(ingredients),
                "recipe_id": recipe_id,
                "recipe_name": recipe_name,
                "hunger": hunger,
                "stress": stress,
                "sell_value": sell,
                "missing_ingredients": missing,
                "all_stats_known": all_known,
                "travel_score": hunger + stress,
                "profitability": None
            }

            result[cookjob] = entry

        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in result.items()}, f, indent=2)

        self.cache = result
        self.df = None  # force refresh

    def get_stats_for_cookjob(self, cookjob_int: int) -> dict:
        return self.cache.get(cookjob_int)

    def get_dataframe(self) -> pd.DataFrame:
        if self.df is None:
            self.df = pd.DataFrame.from_dict(self.cache, orient="index")
        return self.df

    def get_ingredient_stat(self, name: str, stat: str):
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        stats = data.get("ingredient_stats", {})
        return stats.get(name, {}).get(stat)

if __name__ == "__main__":
    import time
    from main import load_inventory
    from recipe_manager import RecipeManager
    from ingredient_coder import IngredientCoder

    print("Initializing components...")
    start = time.perf_counter()

    manager = RecipeManager()
    cache = CookjobStatsCache(manager)

    cache.load_or_build()

    end = time.perf_counter()
    print(f"Cache ready in {end - start:.2f} seconds.")

    print("\nLoading inventory...")
    inv_mask = load_inventory()

    valid_jobs = set(manager.get_valid_cookjobs_from_inventory(inv_mask))
    df = cache.get_dataframe()

    known = df[df["all_stats_known"] & df.index.isin(valid_jobs)]
    if known.empty:
        print("No cookjobs available with known stats for current inventory.")
        exit()

    print(f"\nFound {len(known)} cookjobs you can currently make with full stat knowledge.\n")

    print("Top 10 travel food candidates (hunger + stress):\n")
    top_travel = known.sort_values("travel_score", ascending=False).head(10)
    for _, row in top_travel.iterrows():
        print(f"  {row['recipe_name']:30} | travel {row['travel_score']:3} | "
              f"ingredients: {', '.join(row['ingredients'])}")

    print("\nTop 10 market food candidates (sell value):\n")
    top_sell = known.sort_values("sell_value", ascending=False).head(10)
    for _, row in top_sell.iterrows():
        print(f"  {row['recipe_name']:30} | sell {row['sell_value']:3} | "
              f"ingredients: {', '.join(row['ingredients'])}")
