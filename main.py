import sys
import os
import difflib
import json
from ingredient_coder import IngredientCoder
from recipe_manager import RecipeManager
from report_manager import ReportManager
from cookjob_stats_cache import CookjobStatsCache

recipe_manager = RecipeManager()

STATE_PATH = "user_state.json"
DATA_PATH = "data.json"

with open(DATA_PATH, "r", encoding="utf-8") as f:
    _data = json.load(f)
VALID_INGREDIENTS = _data["valid_ingredients"]

# ---- MISC HELPERS ----

def fuzzy_match_ingredient(user_input: str) -> str | None:
    cleaned = user_input.strip().lower()

    # Try exact (case-insensitive) match
    for valid in VALID_INGREDIENTS:
        if valid.lower() == cleaned:
            return valid

    # Try normal fuzzy match
    matches = difflib.get_close_matches(cleaned, VALID_INGREDIENTS, n=1, cutoff=0.7)
    if matches:
        return matches[0]

    # If input is very short, try again with lower cutoff
    if len(cleaned) <= 4:
        matches = difflib.get_close_matches(cleaned, VALID_INGREDIENTS, n=1, cutoff=0.5)
        if matches:
            return matches[0]

    return None

# ---- USER STATE MANAGEMENT ----

def load_user_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"inventory": []}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_user_state(state: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def load_inventory() -> int:
    state = load_user_state()
    ingredients = state.get("inventory", [])
    bitmask = 0
    for name in ingredients:
        if name in IngredientCoder.ingredient_to_index:
            bitmask |= IngredientCoder.ingredient_to_bit(name)
    return bitmask

def save_inventory(bitmask: int):
    ingredients = sorted(IngredientCoder.int_to_cookjob_tuple(bitmask))
    state = load_user_state()
    state["inventory"] = ingredients
    save_user_state(state)

# ---- INGREDIENT MANAGEMENT ----

def get_ingredient_stat(name: str, stat: str):
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    stats = data.get("ingredient_stats", {})
    return stats.get(name, {}).get(stat)

def set_ingredient_stat(name: str, stat: str, value):
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "ingredient_stats" not in data:
        data["ingredient_stats"] = {}

    if name not in data["ingredient_stats"]:
        data["ingredient_stats"][name] = {}

    data["ingredient_stats"][name][stat] = value

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ---- COMMAND HANDLERS ----

def handle_inv(input_str: str):
    bitmask = load_inventory()
    changes = [item.strip() for item in input_str.split(",") if item.strip()]
    for token in changes:
        is_removal = token.startswith("-")
        raw = token[1:].strip() if is_removal else token.strip()

        matched = fuzzy_match_ingredient(raw)
        if not matched:
            print(f"Unrecognized ingredient: '{raw}'")
            continue

        mask = IngredientCoder.ingredient_to_bit(matched)

        if is_removal:
            if bitmask & mask:
                bitmask &= ~mask
                print(f"Removed {matched}")
            else:
                print(f"{matched} not in inventory")
        else:
            if bitmask & mask:
                print(f"{matched} already present")
            else:
                bitmask |= mask
                print(f"Added {matched}")

    save_inventory(bitmask)

def handle_clear() -> int:
    save_inventory(0)
    print("Inventory cleared.")

def handle_exit():
    print("Exiting.")
    sys.exit(0)

def handle_solve(ingredient_name: str, recipe_manager, inventory_bitmask: int):
    # First, fuzzy match the ingredient name to canonical form
    matched = fuzzy_match_ingredient(ingredient_name)
    if not matched:
        print(f"Unrecognized ingredient: '{ingredient_name}'")
        return

    print(f"Solving for: {matched}")
    ingredient_bit = IngredientCoder.ingredient_to_bit(matched)

    # ---------------------------------------------
    # Step 1: Cache known stress values in inventory
    # We use this to score which isolation pair will sell most easily
    # Recipes with total stress ≥ 34 tend to sell fast at the market stall
    # ---------------------------------------------
    inventory_ingredients = IngredientCoder.int_to_cookjob_tuple(inventory_bitmask)
    stress_cache = {}
    for ing in inventory_ingredients:
        val = get_ingredient_stat(ing, "stress")
        if val is not None:
            stress_cache[ing] = val

    # ---------------------------------------------
    # Step 2: Get all valid isolation pairs for this ingredient
    # Each pair is (without, with) where only the one bit for this ingredient changes
    # Search is limited to cookjobs possible with current inventory
    # ---------------------------------------------
    valid_jobs = recipe_manager.get_valid_cookjobs_from_inventory(inventory_bitmask)
    pairs = recipe_manager.find_isolation_pairs_for_ingredient(ingredient_bit, valid_jobs)
    if not pairs:
        print("No isolation pairs found with current inventory.")
        return

    # ---------------------------------------------
    # Step 3: Score each 'without' cookjob based on known stress values
    # We rank them by total stress of the 'without' cookjob to find high-stress recipes
    # This helps us avoid pick-and-refresh grinding when selling at the market
    # ---------------------------------------------
    scored_pairs = []
    for without, with_ in pairs:
        without_ings = IngredientCoder.int_to_cookjob_tuple(without)
        total_stress = sum(stress_cache.get(ing, 0) for ing in without_ings)
        scored_pairs.append((total_stress, without, with_))

    scored_pairs.sort(reverse=True)  # Highest stress first

    # ---------------------------------------------
    # Step 4: Pick which pair to use
    # If top stress is 34 or more, we auto-pick it (market stall shortcut)
    # Otherwise, user must choose the best candidate manually
    # ---------------------------------------------
    if scored_pairs[0][0] >= 34:
        chosen = scored_pairs[0]
    else:
        total = len(scored_pairs)
        for i, (stress_total, without, with_) in enumerate(reversed(scored_pairs)):
            names = IngredientCoder.int_to_cookjob_tuple(without)
            print(f"{total - i}: Stress={stress_total:2d} | {', '.join(names)}")

        print("\nMultiple isolation pairs found.")
        print("No clear high-stress recipe to ensure fast market sales.")
        print("Try to identify a candidate recipe with high total stress manually.")
        print("If none stand out, you can:")
        print(" - Choose a different ingredient to solve first, or")
        print(" - Use 'solve2' to derive this one's stats from known ingredients.")
        print("Type the number of the pair to select, or 'cancel' to return to the menu.")

        try:
            user_input = input("Choose pair #: ").strip().lower()
            if user_input == "cancel":
                print("Cancelled.")
                return
            sel = int(user_input) - 1
            chosen = scored_pairs[sel]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return


    stress_without, job_without, job_with = chosen
    tuple_without = IngredientCoder.int_to_cookjob_tuple(job_without)
    tuple_with = IngredientCoder.int_to_cookjob_tuple(job_with)

    # Lookup recipe names using helper methods for clarity in prompts
    id_without = recipe_manager.get_recipe_id_for_cookjob(job_without)
    id_with = recipe_manager.get_recipe_id_for_cookjob(job_with)
    name_without = recipe_manager.get_recipe_name_by_id(id_without)
    name_with = recipe_manager.get_recipe_name_by_id(id_with)

    # ---------------------------------------------
    # Step 5: Prompt user for real-world data
    # They craft each version of the food, check hunger/stress/sell_value,
    # and enter them into the system for analysis
    # ---------------------------------------------
    print("\n---")
    print("- Clear your inventory of cooked food and zero your food need at the restaraunt.")
    print("- Craft a NORMAL version of the cooked food. Drop any advanced/legendary.")
    print("- Read hunger, stress from the description.")
    print("- Sell at the market stall to get the sell_value. (Make sure it's ONLY the normal item that sold)")
    print("- Enter the hunger, stress, and sell values comma-delimited (e.g. '80, 32, 120').\n")

    print(f'Cook "{name_without}" with ingredients: {", ".join(tuple_without)}')
    raw_input = input("hunger, stress, sell_value> ").strip()
    try:
        hw, sw, vw = map(int, raw_input.split(","))
    except ValueError:
        print("Invalid input, requires three comma delimited integers. Cancelled.")
        return


    print(f'\nCook "{name_with}" with ingredients: {", ".join(tuple_with)}')
    raw_input = input("hunger, stress, sell_value> ").strip()
    try:
        hw2, sw2, vw2 = map(int, raw_input.split(","))
    except ValueError:
        print("Invalid input, requires three comma delimited integers. Cancelled.")
        return


    # ---------------------------------------------
    # Step 6: Calculate the difference between the two versions
    # This delta is assumed to be the contribution of the target ingredient
    # ---------------------------------------------
    dhunger = hw2 - hw
    dstress = sw2 - sw
    dsell = vw2 - vw

    # ---------------------------------------------
    # Step 7: Check existing stats for this ingredient
    # If different, we override. If same, confirm match.
    # If missing, we store a new value entirely.
    # ---------------------------------------------
    prev = {
        "hunger": get_ingredient_stat(matched, "hunger"),
        "stress": get_ingredient_stat(matched, "stress"),
        "sell_value": get_ingredient_stat(matched, "sell_value")
    }

    new_stats = {"hunger": dhunger, "stress": dstress, "sell_value": dsell}
    changed = False

    if all(v is None for v in prev.values()):
        print(f"\nNew ingredient entry: {matched} = {new_stats}")
    else:
        for k in ["hunger", "stress", "sell_value"]:
            if prev[k] != new_stats[k]:
                print(f"\nOverriding {k} for {matched}: {prev[k]} → {new_stats[k]}")
                changed = True
        if not changed:
            print(f"\nValues for {matched} confirmed: {new_stats}")

    # ---------------------------------------------
    # Step 8: Write back to ingredient_stats in data.json
    # These values persist and can be used in future solving logic
    # ---------------------------------------------
    for stat, val in new_stats.items():
        set_ingredient_stat(matched, stat, val)



def command_router(command_line: str):
    if not command_line.strip():
        return

    parts = command_line.strip().split(" ", 1)
    keyword = parts[0].lower()
    input_str = parts[1] if len(parts) > 1 else ""

    if keyword == "exit":
        handle_exit()
    elif keyword == "clear":
        handle_clear()
    elif keyword == "inv":
        handle_inv(input_str)
    elif keyword == "solve":
        inventory_bitmask = load_inventory()
        handle_solve(input_str, recipe_manager, inventory_bitmask)
    else:
        print(f"Unknown command: '{keyword}'")

def main():
    stats_cache = CookjobStatsCache(recipe_manager)
    stats_cache.load_or_build()
    report_manager = ReportManager(recipe_manager, stats_cache)


    while True:
        bitmask = load_inventory()

        # === Reports ===
        print("\n    ====== Best Road Food (Hunger + Stress) ======")
        print(report_manager.get_best_road_food(bitmask).to_string(index=False))

        print("\n    ====== Best Sale Food (Sell Value Only) ======")
        print(report_manager.get_best_sale_food(bitmask).to_string(index=False))


        current = IngredientCoder.int_to_cookjob_tuple(bitmask)
        print("\n    ====== Current Inventory ======")
        print("" + ", ".join(current))

        # Check for unsolved
        unsolved = [ing for ing in current if get_ingredient_stat(ing, "sell_value") is None]
        if unsolved:
            print("\n    ====== UNSOLVED INGREDIENT WARNING ======")
            print("\nYou have unsolved ingredients in your inventory.")
            print("Use 'solve [ingredient]' to concretely derive ingredient stats.")
            print("Unsolved ingredients: " + ", ".join(unsolved))

        print("\n    ====== Recipe Console ======")
        print("- 'inv ingredient1, ingredient2, -ingredient3' to modify inventory")
        print("- 'clear' to empty the inventory, 'exit' to quit.\n")

        try:
            command_line = input("> ")
        except (EOFError, KeyboardInterrupt):
            handle_exit()


        command_router(command_line)

if __name__ == "__main__":
    main()
