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
        self.cache = {}
        self.df = None

        self._ingredient_stats = {}
        self._ingredient_to_categories = {}  # bit -> [categories]
        self._bit_to_name = {}

        self._load_category_and_stat_data()

    def _load_category_and_stat_data(self):
        with open("data.json", "r", encoding="utf-8") as f:
            full_data = json.load(f)

        self._ingredient_stats = full_data.get("ingredient_stats", {})
        category_definitions = full_data.get("categories", {})
        valid_ingredients = full_data.get("valid_ingredients", [])

        # Reverse map: ingredient name -> list of categories
        ingredient_to_catnames = {}
        for category, ingredients in category_definitions.items():
            for ing in ingredients:
                ingredient_to_catnames.setdefault(ing, []).append(category)

        # Map bit -> categories and bit -> name
        for ing in valid_ingredients:
            bit = IngredientCoder.ingredient_to_bit(ing)
            self._ingredient_to_categories[bit] = ingredient_to_catnames.get(ing, [])
            self._bit_to_name[bit] = ing


    def load_or_build(self):
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r") as f:
                self.cache = {int(k): v for k, v in json.load(f).items()}
        else:
            self.rebuild_and_save()


    #Game rule seems to be:
    # - base penalty of 0, -4, -12
    # - multiply that penalty by the number of ingredients in the same category used in a cookjob
    #For example:
    # - if a cookjob uses 2 mushrooms, it's 0, -8, -12
    # - if a cookjob uses 3 wines, it's 0, -12, -36
    #It is not clear what would happen if there were 2 categories of 2 or more ingredients,
    #there are no valid cookjobs in the game where that occurs.
    def _calculate_penalty(self, ingredient_bits: list[int]) -> tuple[int, int, int]:
        base_penalty = (0, -4, -12)
        category_counts = {}

        for bit in ingredient_bits:
            categories = self._ingredient_to_categories.get(bit, [])
            # Debug line: make sure categories are seen
            #print(f"{self._bit_to_name[bit]} categories: {categories}")
            for cat in categories:
                category_counts[cat] = category_counts.get(cat, 0) + 1

        # Compute penalties: stress and sell scaled per *ingredient* per category
        all_penalties = [base_penalty]
        for cat, count in category_counts.items():
            all_penalties.append((0, -4 * count, -12 * count))

        # Debug line: print final computed penalties
        #print(f"Category counts: {category_counts} → penalties: {all_penalties}")

        return (
            0,
            min(p[1] for p in all_penalties),
            min(p[2] for p in all_penalties)
        )



    def rebuild_and_save(self):
        print("Rebuilding cookjob stats cache...")

        result = {}

        for cookjob in self.recipe_manager.valid_cookjobs:
            ingredient_names = IngredientCoder.int_to_cookjob_tuple(cookjob)
            ingredient_bits = [IngredientCoder.ingredient_to_bit(name) for name in ingredient_names]


            hunger = 0
            stress = 0
            sell = 0
            missing = []

            for bit in ingredient_bits:
                name = self._bit_to_name[bit]
                stats = self._ingredient_stats.get(name, {})
                h = stats.get("hunger", 0)
                s = stats.get("stress", 0)
                v = stats.get("sell_value", 0)

                if any(k not in stats for k in ["hunger", "stress", "sell_value"]):
                    missing.append(name)

                hunger += h
                stress += s
                sell += v

            penalty = self._calculate_penalty(ingredient_bits)
            hunger += penalty[0]
            stress += penalty[1]
            sell += penalty[2]

            all_known = len(missing) == 0
            recipe_id = self.recipe_manager.get_recipe_id_for_cookjob(cookjob)
            recipe_name = self.recipe_manager.get_recipe_name_by_id(recipe_id)

            entry = {
                "ingredients": [self._bit_to_name[bit] for bit in ingredient_bits],
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
        self.df = None



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

    cache.rebuild_and_save()

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

    print("\nValidating observed data against calculated values:\n")

    observed_data = [
        (["Ham"], 100, 35, 155),
        (["Cheese"], 100, 35, 155),
        (["Ham", "Cheese"], 200, 74, 322),
        (["Dried Vegetables", "Ham"], 180, 63, 279),
        (["Dried Vegetables", "Cheese"], 180, 63, 279),
        (["Honey", "Beer", "Cheese"], 260, 179, 667),
        (["Liquor", "Beer", "Fruit Wine"], 240, 200, 720),
        (["Honey", "Fruit Wine", "Cheese"], 260, 179, 667),
        (["Liquor", "Honey", "Cheese"], 260, 139, 547),
        (["Water", "Eggs", "Salt", "Agaric", "Matsutake"], 154, 45, 212),
        (["Liquor", "Honey", "Beer", "Fruit Wine", "Cheese"], 420, 299, 1107),
    ]

    any_discrepancy = False

    for ingredients, obs_hunger, obs_stress, obs_sell in observed_data:
        bitmask = IngredientCoder.cookjob_tuple_to_int(tuple(sorted(ingredients)))
        stats = cache.get_stats_for_cookjob(bitmask)
        if not stats:
            print(f"  MISSING: {ingredients}")
            continue

        calc_hunger = stats["hunger"]
        calc_stress = stats["stress"]
        calc_sell = stats["sell_value"]

        diff_h = calc_hunger - obs_hunger
        diff_s = calc_stress - obs_stress
        diff_v = calc_sell - obs_sell

        status = "✓" if (diff_h, diff_s, diff_v) == (0, 0, 0) else "❌"
        if status == "❌":
            any_discrepancy = True

        print(f"{status} {' + '.join(ingredients):40} | "
              f"ΔHunger: {diff_h:3} | ΔStress: {diff_s:3} | ΔSell: {diff_v:3}")

    if not any_discrepancy:
        print("\n✅ All observed values match calculated results exactly.")
