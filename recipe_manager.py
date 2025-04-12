import json
import os
import csv
import math
from collections import defaultdict
from itertools import product
from bisect import bisect_left
from ingredient_coder import IngredientCoder

"""
recipe_manager.py:

Class RecipeManager
Handles recipe expansion, cookjob indexing, and cache management for
ingredient-based crafting logic.

On initialization, loads or builds three caches:
- master_recipes.json: maps recipe IDs to recipe name and all valid cookjobs
- cookjob_to_recipes.json: reverse index from cookjob to list of matching recipes
- valid_cookjobs.json: deduplicated, sorted list of all known valid cookjob bitmasks

Caches are created in the specified cache directory and automatically reused
across runs. Ingredient resolution is performed through IngredientCoder.

Instance Methods:
- expand_recipe_string(recipe_str: str) -> set[int]
  Expands a recipe string (e.g. "Game|BaseSalt?|Water") into all valid
  cookjob bitmasks that satisfy the structure. Uses category and optional
  slot logic, and ensures ingredient uniqueness and 1–5 count.

- is_valid_cookjob(cookjob: int) -> bool
  Returns True if the cookjob bitmask is in the known valid cookjob list.

- get_valid_cookjobs_from_inventory(inventory: int) -> list[int]
  Returns a list of valid cookjobs that can be crafted using only the
  provided inventory bitmask (subset match).

- get_valid_cookjobs_from_inventory_and_surplus(
    inventory: int, surplus: int, min_surplus_ratio: float = 0.5) -> list[int]
  Returns a list of valid cookjobs that can be crafted using only the
  provided inventory bitmask (subset match), AND at least [min_surplus_ratio] percent
  of those ingredients must come from the surplus list.

- find_isolation_pairs_for_ingredient(ingredient_bit: int, cookjobs: list[int]) -> list[tuple[int, int]]
  Given a one-hot ingredient bit and a sorted list of cookjobs, returns all
  (without, with) pairs where the only difference is the presence of that bit.
  Used to isolate an ingredient’s contribution by comparing similar recipes.
"""

class RecipeManager:
    def __init__(self, data_path="data.json", cache_dir="cache", recipe_csv_path="recipes.csv"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

        self.categories = self._load_categories(data_path)
        self.valid_ingredients = set(IngredientCoder.ingredients)

        self.master_recipes = self._load_or_build_master_recipes(recipe_csv_path)
        self.valid_cookjobs = self._load_or_build_valid_cookjobs()
        self.cookjob_to_recipes = self._load_or_build_cookjob_to_recipes()

    def _load_categories(self, data_path):
        with open(data_path, "r") as f:
            data = json.load(f)
        return data["categories"]

    def _load_or_build_master_recipes(self, csv_path):
        cache_file = os.path.join(self.cache_dir, "master_recipes.json")

        # If cache exists, load it and return
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                return {int(k): v for k, v in json.load(f).items()}

        print("Building master recipes...")

        master = {}
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    recipe_id = int(row["Recipe"])
                    recipe_str = row["Ingredient"].strip()
                    recipe_name = row["Name"].strip()

                    # Expand this recipe into all valid cookjob bitmasks
                    cookjob_bitmasks = self.expand_recipe_string(recipe_str)

                    # --- Parse the recipe structure ---
                    # We don't keep the full parsed structure (which would include the slot list),
                    # Instead we count only what we need for cookjob scoring later.
                    #
                    # For each token in the recipe string, we determine:
                    # - Is it required or optional?
                    # - Is it a specific ingredient or a category?
                    # Then we increment the appropriate counter.

                    required_exact = 0
                    required_category = 0
                    optional_exact = 0
                    optional_category = 0

                    for token in recipe_str.strip().split("|"):
                        is_optional = token.endswith("?")
                        key = token[:-1] if is_optional else token

                        if key in self.categories:
                            is_category = True
                        elif key in self.valid_ingredients:
                            is_category = False
                        else:
                            raise ValueError(f"Unrecognized ingredient or category: '{key}'")

                        if is_optional:
                            if is_category:
                                optional_category += 1
                            else:
                                optional_exact += 1
                        else:
                            if is_category:
                                required_category += 1
                            else:
                                required_exact += 1

                    # Construct the recipe entry
                    master[recipe_id] = {
                        "name": recipe_name,
                        "cookjobs": list(cookjob_bitmasks),
                        "slot_profile": {
                            "required_exact": required_exact,
                            "required_category": required_category,
                            "optional_exact": optional_exact,
                            "optional_category": optional_category
                        }
                    }

                except (KeyError, ValueError) as e:
                    print(f"Skipping invalid row: {row} ({e})")

        # Cache the compiled recipe data to disk
        with open(cache_file, "w") as f:
            json.dump(master, f, indent=2)

        return master

    def _load_or_build_cookjob_to_recipes(self):
        cache_file = os.path.join(self.cache_dir, "cookjob_to_recipes.json")

        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                raw = json.load(f)
                return {int(k): v for k, v in raw.items()}

        print("Building cookjob-to-recipe mapping...")

        # ----------------------------------------
        # Step 1: Build a reverse mapping of all recipes by their cookjobs
        # For most cookjobs, this will only map to one recipe.
        # In ambiguous cases (multiple recipes accept the same cookjob),
        # we will use scoring logic to determine the "best match".
        # ----------------------------------------
        reverse_index = {}
        for recipe_id, info in self.master_recipes.items():
            for cookjob in info["cookjobs"]:
                reverse_index.setdefault(cookjob, []).append(recipe_id)

        mapping = {}

        # We'll need to recover original recipe strings for slot logic
        # We'll rebuild this map directly from the CSV to avoid bloating cache unnecessarily
        # (Alternatively, you could store this during _load_or_build_master_recipes if desired)
        recipe_strings = {}
        with open("recipes.csv", newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rid = int(row["Recipe"])
                    recipe_strings[rid] = row["Ingredient"].strip()
                except Exception:
                    continue

        # ----------------------------------------
        # Step 2: For each cookjob, assign the single best-matching recipe
        # This is done by scoring each candidate recipe against the cookjob
        #
        # Game logic (and our logic) prefers:
        #   1. More required exact matches
        #   2. More required category matches
        #   3. More optional matches (exact or category)
        #   4. Fewer total required ingredients (simpler recipe)
        #   5. Lower recipe ID as final tiebreaker
        # ----------------------------------------
        for cookjob in self.valid_cookjobs:
            candidates = reverse_index.get(cookjob)

            if not candidates:
                continue  # shouldn't happen

            if len(candidates) == 1:
                # No ambiguity, assign directly
                mapping[cookjob] = candidates[0]
                continue

            # Convert cookjob bitmask to set of ingredient names
            cookjob_ingredients = set(IngredientCoder.int_to_cookjob_tuple(cookjob))

            best_score = None
            best_recipe_id = None

            for recipe_id in candidates:
                recipe_str = recipe_strings.get(recipe_id)
                if not recipe_str:
                    continue  # malformed or missing

                remaining_ings = set(cookjob_ingredients)
                req_exact = req_cat = opt_match = 0
                total_required = 0

                for token in recipe_str.strip().split("|"):
                    is_optional = token.endswith("?")
                    key = token[:-1] if is_optional else token

                    # Skip if we already exhausted ingredients
                    if not remaining_ings:
                        continue

                    # Try exact match
                    if key in self.valid_ingredients:
                        if key in remaining_ings:
                            if is_optional:
                                opt_match += 1
                            else:
                                req_exact += 1
                                total_required += 1
                            remaining_ings.remove(key)
                        elif not is_optional:
                            # Required slot not satisfied
                            break

                    # Try category match
                    elif key in self.categories:
                        match = None
                        for ing in remaining_ings:
                            if ing in self.categories[key]:
                                match = ing
                                break
                        if match:
                            if is_optional:
                                opt_match += 1
                            else:
                                req_cat += 1
                                total_required += 1
                            remaining_ings.remove(match)
                        elif not is_optional:
                            break  # required slot not filled
                    else:
                        break  # invalid token

                else:
                    # If we didn’t break out of the loop, this recipe is valid
                    score = (
                        req_exact,                # primary: exact required matches
                        req_cat,                  # secondary: category required matches
                        opt_match,                # tie-breaker: optional matches
                        -total_required,          # fewer required = better
                        -recipe_id                # final tiebreak: lower ID wins
                    )

                    if best_score is None or score > best_score:
                        best_score = score
                        best_recipe_id = recipe_id

            if best_recipe_id is not None:
                mapping[cookjob] = best_recipe_id

        # ----------------------------------------
        # Save final mapping: cookjob → best recipe ID
        # ----------------------------------------
        with open(cache_file, "w") as f:
            json.dump({str(k): v for k, v in mapping.items()}, f, indent=2)

        return mapping

    def _load_or_build_valid_cookjobs(self):
        cache_file = os.path.join(self.cache_dir, "valid_cookjobs.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                return sorted(json.load(f))

        print("Building flat valid cookjob list...")
        all_cookjobs = set()
        for recipe in self.master_recipes.values():
            all_cookjobs.update(recipe["cookjobs"])
        sorted_jobs = sorted(all_cookjobs)

        with open(cache_file, "w") as f:
            json.dump(sorted_jobs, f, indent=2)
        return sorted_jobs

    def expand_recipe_string(self, recipe_str: str) -> set[int]:
        slots = []

        for token in recipe_str.strip().split("|"):
            is_optional = token.endswith("?")
            key = token[:-1] if is_optional else token

            if key in self.categories:
                choices = self.categories[key]
            elif key in self.valid_ingredients:
                choices = [key]
            else:
                raise ValueError(f"Unrecognized category or ingredient in recipe: '{key}'")

            if not choices and not is_optional:
                return set()

            slots.append({
                "is_optional": is_optional,
                "choices": choices
            })

        option_lists = []
        for slot in slots:
            options = slot["choices"]
            if slot["is_optional"]:
                option_lists.append(options + [None])
            else:
                option_lists.append(options)

        all_jobs: set[int] = set()
        for combo in product(*option_lists):
            filled = [ing for ing in combo if ing is not None]
            if not (1 <= len(filled) <= 5):
                continue
            if len(set(filled)) != len(filled):
                continue
            bitmask = IngredientCoder.cookjob_tuple_to_int(tuple(filled))
            all_jobs.add(bitmask)

        return all_jobs

    def is_valid_cookjob(self, cookjob: int) -> bool:
        from bisect import bisect_left
        idx = bisect_left(self.valid_cookjobs, cookjob)
        return idx < len(self.valid_cookjobs) and self.valid_cookjobs[idx] == cookjob

    def get_valid_cookjobs_from_inventory(self, inventory: int) -> list[int]:
        """
        Given an inventory bitmask, return all valid cookjobs that
        can be made using only the available ingredients.
        """
        return [job for job in self.valid_cookjobs if job & inventory == job]

    '''  DEPRECATED -- we shifted from filtering to weighting for surplus.
        def get_valid_cookjobs_from_inventory_and_surplus(self, inventory: int, surplus: int, min_surplus_ratio: float = 0.5) -> list[int]:
            """
            Returns valid cookjobs that can be made from the inventory and contain
            a minimum ratio of surplus ingredients (default 50%).

            Surplus is a bitmask representing the "overflow" ingredients you'd like to burn.

            A cookjob is included if at least half of its ingredients are in the surplus list.
            """
            valid_jobs = self.get_valid_cookjobs_from_inventory(inventory)

            # Precompute thresholds for ingredient counts 1–5
            thresholds = {n: math.ceil(n * min_surplus_ratio) for n in range(1, 6)}
            filtered = []

            for job in valid_jobs:
                ingredients = IngredientCoder.int_to_cookjob_tuple(job)
                total = len(ingredients)
                surplus_count = sum(
                    1 for ing in ingredients
                    if IngredientCoder.ingredient_to_bit(ing) & surplus
                )

                if surplus_count >= thresholds[total]:
                    filtered.append(job)

            return filtered
    '''

    def find_isolation_pairs_for_ingredient(self, ingredient_bit: int, cookjobs: list[int]) -> list[tuple[int, int]]:
        """
        Returns all (without, with) pairs of cookjobs where the only difference is the presence of the ingredient_bit.
        Assumes cookjobs is sorted and well-formed.
        """
        pairs = []
        for job in cookjobs:
            if job & ingredient_bit:
                paired = job ^ ingredient_bit
                i = bisect_left(cookjobs, paired)
                if i < len(cookjobs) and cookjobs[i] == paired:
                    pairs.append((paired, job))
        return pairs

    def get_recipe_name_by_id(self, recipe_id: int) -> str:
        return self.master_recipes.get(recipe_id, {}).get("name", "<unknown recipe>")

    def get_recipe_id_for_cookjob(self, cookjob: int) -> int:
        """
        Returns the best-matching recipe ID for cookjob, based on scoring logic during cache construction.
        """
        return self.cookjob_to_recipes.get(cookjob)

import time

if __name__ == "__main__":
    manager = RecipeManager()

    print(f"\nLoaded {len(manager.master_recipes)} recipes.")
    print(f"Found {len(manager.valid_cookjobs)} unique valid cookjobs.\n")

    sample = manager.valid_cookjobs[21979]
    ingredients = IngredientCoder.int_to_cookjob_tuple(sample)
    print("Example valid cookjob:")
    print("  ", ", ".join(ingredients))
    print("  Recipes:", manager.cookjob_to_recipes.get(sample, []))

    # Performance test
    test_ingredients = ("Spices", "Tea", "Vegetables", "Venison", "Water")
    test_bitmask = IngredientCoder.cookjob_tuple_to_int(test_ingredients)

    print("\nStarting 100,000 validity checks...")
    start = time.perf_counter()
    for _ in range(100_000):
        manager.is_valid_cookjob(test_bitmask)
    end = time.perf_counter()

    print(f"Time taken: {end - start:.6f} seconds")

    # Inventory performance test
    from time import perf_counter

    inventory_ingredients = ("Agaric", "Bacon")
    inventory_mask = 0
    for ing in inventory_ingredients:
        inventory_mask |= IngredientCoder.ingredient_to_bit(ing)

    print(f"\nTesting inventory-based filtering using: {', '.join(inventory_ingredients)}")

    # Warm-up and show example
    matching_jobs = manager.get_valid_cookjobs_from_inventory(inventory_mask)
    print(f"Found {len(matching_jobs)} matching cookjobs for inventory.")

    print("\nTiming 1,000 inventory lookups...")
    start = perf_counter()
    for _ in range(1_000):
        _ = manager.get_valid_cookjobs_from_inventory(inventory_mask)
    end = perf_counter()

    print(f"Time taken: {end - start:.6f} seconds")

    rations_bit = IngredientCoder.ingredient_to_bit("Rations")

    print("\nFinding isolation pairs for 'Rations'...")
    start = perf_counter()
    pairs = manager.find_isolation_pairs_for_ingredient(rations_bit, manager.valid_cookjobs)
    end = perf_counter()

    print(f"\nFound {len(pairs)} isolation pairs for 'Rations' in {end - start:.6f} seconds:\n")
    for without, with_ in pairs:
        without_names = IngredientCoder.int_to_cookjob_tuple(without)
        with_names = IngredientCoder.int_to_cookjob_tuple(with_)
        print(f"Without: {', '.join(without_names)}")
        print(f"With   : {', '.join(with_names)}")
        print("---")