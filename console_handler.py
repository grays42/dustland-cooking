import sys
import os
import json
import difflib
import pandas as pd
from ingredient_coder import IngredientCoder
from report_definition import ReportDefinition

"""
console_handler.py

Class ConsoleHandler
Manages all console interaction for the Dustland Delivery cooking optimizer CLI.
Responsible for displaying reports, reading and modifying inventory, directing user
commands, and solving ingredient stats via recipe isolation.

This class is the main user interface loop, coordinating display, input capture,
fuzzy ingredient matching, and command routing. It encapsulates all input/output
logic so that `main.py` only needs to initialize data and run the loop.

On initialization, loads user inventory from disk and reads `data.json` for valid
ingredients and ingredient stats.

Main Commands Handled:
- inv [list]          : Add/remove ingredients from inventory (e.g. 'inv salt, -cheese')
- inv clear           : Clears the current inventory
- inv all             : Adds all known ingredients to inventory
- surplus [list]      : Marks ingredients as surplus (same syntax as `inv`)
- surplus clear/all   : Clears or fills surplus list
- solve [ingredient]  : Guides the user through a stat isolation process
- settings            : Opens the settings menu to view or change user configuration options
- exit                : Quits the program

Tracks:
- Inventory bitmask (based on ingredient names and bit encoding)
- Surplus bitmask (for future use in recipe ranking)
- Ingredient stat definitions (loaded from data.json)
- User settings (e.g., Speech Skill, Cooking Skill, Scenario; loaded from user_state.json)

Displays:
- Top 10 road food and sale food cookjobs based on current inventory
- Current inventory and surplus lists
- Unsolved ingredients in inventory (those missing stat data)
- Editable user settings with descriptions and validation

Instance Methods:
- run_loop()
    Executes a single turn of the console, including input, command handling, and output.

- display_reports()
    Prints top 10 cookjobs for travel (hunger + stress) and sale (sell_value).

- display_inventory()
    Prints currently held ingredients in inventory.

- display_surplus()
    Prints currently marked surplus ingredients.

- display_unsolved_warning()
    Shows ingredients in inventory missing stat data.

- handle_command(command_line: str)
    Routes the user input to the appropriate command handler.

- handle_inventory_command(input_str: str)
    Applies syntax to modify the inventory bitmask. Supports adds, removes, 'all', and 'clear'.

- handle_surplus_command(input_str: str)
    Same logic as inventory, but applies to the surplus bitmask.

- apply_inventory_syntax(input_str: str, bitmask: int) -> int
    Parses a comma-delimited ingredient list for addition/removal, including 'clear' and 'all'.

- fuzzy_match_ingredient(user_input: str) -> str | None
    Returns the closest matching valid ingredient name (or None) for user input.

- get_ingredient_stat(name: str, stat: str)
    Retrieves the stat for a specific ingredient from memory.

- set_ingredient_stat(name: str, stat: str, value)
    Updates the ingredient stat and persists changes to data.json.

- handle_solve(ingredient_name: str)
    Prompts the user to isolate a target ingredient’s hunger/stress/sell_value using two recipes.

- prompt_user_for_pair(scored_pairs: list[tuple])
    Prompts the user to manually select a recipe pair when no automatic best option is found.

- handle_exit()
    Exits the program gracefully.
    
- handle_settings_command()
    Opens a numbered menu to view and modify user settings defined in `data.json > settings_info`

Internal Helpers:
- load_user_state() -> dict
    Loads user state from disk (currently just inventory list).

- save_user_state()
    Saves the current inventory bitmask back to disk in sorted name form.

- load_inventory() -> int
    Converts loaded inventory names to bitmask using IngredientCoder.
"""


pd.set_option("display.max_columns", None)
pd.set_option("display.expand_frame_repr", False)

DATA_PATH = "data.json"
STATE_PATH = "user_state.json"

class ConsoleHandler:
    def __init__(self, recipe_manager, reporter, stats_cache):
        self.recipe_manager = recipe_manager
        self.reporter = reporter
        self.stats_cache = stats_cache

        with open(DATA_PATH, "r", encoding="utf-8") as f:
            self._data = json.load(f)

        self.valid_ingredients = self._data["valid_ingredients"]
        self.inventory_bitmask = self._load_inventory()
        self.surplus_bitmask = self._load_surplus()

        self.settings_info = self._data.get("settings_info", {})
        self.settings = self._load_settings()

        self.prebuilt_reports = self._data.get("prebuilt_reports", {})

        user_state = self._load_user_state()
        self.settings = user_state.get("settings", {})
        self.custom_reports = user_state.get("custom_reports", {})

        # Deserialize selected reports (ordered)
        self.selected_report_keys = []
        for entry in user_state.get("selected_reports", []):
            if entry.startswith("custom:{"):
                config = json.loads(entry[7:])
                name_key = f"custom:{config['name'].lower().replace(' ', '_')}"
                self.custom_reports[name_key] = config
                self.selected_report_keys.append(name_key)
            else:
                self.selected_report_keys.append(entry)


    def run_loop(self):
        self._display_reports()
        self._display_inventory()
        self._display_surplus()
        self._display_unsolved_warning()

        print("\n    ====== Recipe Console ======")
        print("- 'inv cheese, -water', 'inv all', or 'inv clear' to modify inventory")
        print("- 'surplus cheese, -salt', 'surplus all', or 'surplus clear'")
        print("- 'solve [ingredient]' to isolate stats")
        print("- 'settings' to change user settings (important, do this if you haven't)")
        print("- 'reports' to select which reports you want to see or make your own")
        print("- 'exit' to quit.\n")

        try:
            command_line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            self._handle_exit()

        self._handle_command(command_line)

    # -----------------------------
    # Inventory Persistence
    # -----------------------------

    def _load_user_state(self) -> dict:
        if not os.path.exists(STATE_PATH):
            return {}
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_user_state(self):
        inventory = sorted(IngredientCoder.int_to_cookjob_tuple(self.inventory_bitmask))
        surplus = sorted(IngredientCoder.int_to_cookjob_tuple(self.surplus_bitmask))
        state = {
            "inventory": inventory,
            "surplus": surplus
        }

        serialized = []
        for key in self.selected_report_keys:
            if key in self.prebuilt_reports:
                serialized.append(key)
            elif key in self.custom_reports:
                config_str = json.dumps(self.custom_reports[key], sort_keys=True)
                serialized.append(f"custom:{config_str}")

        state = {
            "inventory": inventory,
            "surplus": surplus,
            "settings": self.settings,
            "selected_reports": serialized,
            "custom_reports": self.custom_reports
        }

        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def _load_surplus(self) -> int:
        state = self._load_user_state()
        ingredients = state.get("surplus", [])
        bitmask = 0
        for name in ingredients:
            if name in IngredientCoder.ingredient_to_index:
                bitmask |= IngredientCoder.ingredient_to_bit(name)
        return bitmask

    def _load_inventory(self) -> int:
        state = self._load_user_state()
        ingredients = state.get("inventory", [])
        bitmask = 0
        for name in ingredients:
            if name in IngredientCoder.ingredient_to_index:
                bitmask |= IngredientCoder.ingredient_to_bit(name)
        return bitmask

    # -----------------------------
    # Display
    # -----------------------------

    def _display_reports(self):
        # Safely extract cooking skill, default to 0
        cooking_skill = 0
        try:
            user_state = self._load_user_state()
            cooking_skill = user_state.get("user_settings", {}).get("cooking_skill", 0)
        except Exception:
            pass

        for key in self.selected_report_keys:
            config = self.prebuilt_reports.get(key) or self.custom_reports.get(key)
            if not config:
                continue
            try:
                report_def = ReportDefinition(config=config)
                #print(self.surplus_bitmask)
                df = self.reporter.build_report(report_def, self.inventory_bitmask, self.surplus_bitmask, cooking_skill)
                print(f"\n=== {config['name']} ===")
                print(df.head(10).to_string(index=False))
            except Exception as e:
                print(f"\n[Error loading report '{config.get('name', key)}']: {e}")


    def _display_inventory(self):
        current = IngredientCoder.int_to_cookjob_tuple(self.inventory_bitmask)
        print("\n    ====== Current Inventory ======")
        print(", ".join(current) if current else "[empty]")

    def _display_surplus(self):
        if self.surplus_bitmask:
            surplus = IngredientCoder.int_to_cookjob_tuple(self.surplus_bitmask)
            print("\n    ====== Surplus Ingredients ======")
            print("    (Cookjobs are given a +50% ranking weight for every surplus ingredient they include)")
            print(", ".join(surplus))

    def _display_unsolved_warning(self):
        current = IngredientCoder.int_to_cookjob_tuple(self.inventory_bitmask)
        unsolved = [
            ing for ing in current
            if self._get_ingredient_stat(ing, "sell_value") is None
        ]
        if unsolved:
            print("\n    ====== UNSOLVED INGREDIENT WARNING ======")
            print("You have unsolved ingredients in your inventory.")
            print("Use 'solve [ingredient]' to concretely derive ingredient stats.")
            print("Unsolved ingredients: " + ", ".join(unsolved))

    # -----------------------------
    # Command Routing
    # -----------------------------

    def _handle_command(self, command_line: str):
        if not command_line:
            return

        parts = command_line.split(" ", 1)
        keyword = parts[0].lower()
        input_str = parts[1] if len(parts) > 1 else ""

        if keyword == "exit":
            self._handle_exit()
        elif keyword == "inv":
            self._handle_inventory_command(input_str)
        elif keyword == "surplus":
            self._handle_surplus_command(input_str)
        elif keyword == "solve":
            self._handle_solve(input_str)
        elif keyword == "settings":
            self._handle_settings_command()
        elif keyword == "reports":
            self._handle_reports_command()
        else:
            print(f"Unknown command: '{keyword}'")

    # -----------------------------
    # Inventory + Surplus Commands
    # -----------------------------

    def _handle_inventory_command(self, input_str: str):
        self.inventory_bitmask = self._apply_inventory_syntax(input_str, self.inventory_bitmask)
        self._save_user_state()

    def _handle_surplus_command(self, input_str: str):
        self.surplus_bitmask = self._apply_inventory_syntax(input_str, self.surplus_bitmask)
        self._save_user_state()

    def _apply_inventory_syntax(self, input_str: str, bitmask: int) -> int:
        if input_str.strip().lower() == "clear":
            print("Inventory cleared.")
            return 0
        elif input_str.strip().lower() == "all":
            print("All ingredients added.")
            return IngredientCoder.cookjob_tuple_to_int(tuple(self.valid_ingredients))

        changes = [item.strip() for item in input_str.split(",") if item.strip()]
        for token in changes:
            is_removal = token.startswith("-")
            raw = token[1:].strip() if is_removal else token.strip()

            matched = self._fuzzy_match_ingredient(raw)
            if not matched:
                print(f"Unrecognized ingredient: '{raw}'")
                continue

            mask = IngredientCoder.ingredient_to_bit(matched)

            if is_removal:
                if bitmask & mask:
                    bitmask &= ~mask
                    print(f"Removed {matched}")
                else:
                    print(f"{matched} not present")
            else:
                if bitmask & mask:
                    print(f"{matched} already present")
                else:
                    bitmask |= mask
                    print(f"Added {matched}")

        return bitmask

    # -----------------------------
    # Reports
    # -----------------------------

    def _handle_reports_command(self):
        while True:
            print("\n    ====== Report Selection Menu ======")

            print("\n-- Selected Reports --")
            if not self.selected_report_keys:
                print("  [none selected]")
            else:
                for i, key in enumerate(self.selected_report_keys, 1):
                    if key in self.prebuilt_reports:
                        config = self.prebuilt_reports[key]
                    else:
                        config = self.custom_reports.get(key)
                    if config:
                        report = ReportDefinition(config=config)
                        desc = ", ".join(report.describe_attributes())
                        print(f"  {i}. {config['name']} — {desc}")

            print("\nOptions:")
            print("  [1] Add a prebuilt report")
            print("  [2] Remove a selected report")
            print("  [3] Create a custom report")
            print("  [Enter] Return to main menu")

            choice = input("> ").strip()
            if choice == "":
                return

            if choice == "1":
                self._handle_add_prebuilt_report()
            elif choice == "2":
                self._handle_remove_report()
            elif choice == "3":
                self._handle_create_custom_report()
            else:
                print("Invalid input.")

    def _handle_add_prebuilt_report(self):
        print("\n-- Available Prebuilt Reports --")
        keys = list(self.prebuilt_reports.keys())
        for i, key in enumerate(keys, 1):
            config = self.prebuilt_reports[key]
            report = ReportDefinition(config=config)
            desc = ", ".join(report.describe_attributes())
            print(f"  {i}. {config['name']} — {desc}")

        choice = input("Select report to add (number): ").strip()
        if not choice.isdigit():
            return
        index = int(choice) - 1
        if 0 <= index < len(keys):
            selected_key = keys[index]
            if selected_key in self.selected_report_keys:
                print("Report already selected.")
            else:
                self.selected_report_keys.append(selected_key)
                self._save_user_state()
                print(f"Added report: {self.prebuilt_reports[selected_key]['name']}")
        else:
            print("Invalid selection.")

    def _handle_remove_report(self):
        if not self.selected_report_keys:
            print("No reports to remove.")
            return

        for i, key in enumerate(self.selected_report_keys, 1):
            name = self._get_report_name(key)
            print(f"  {i}. {name}")

        choice = input("Select report to remove (number): ").strip()
        if not choice.isdigit():
            return
        index = int(choice) - 1
        if 0 <= index < len(self.selected_report_keys):
            removed = self.selected_report_keys.pop(index)
            self._save_user_state()
            print(f"Removed: {self._get_report_name(removed)}")
        else:
            print("Invalid selection.")

    def _get_report_name(self, key: str) -> str:
        if key in self.prebuilt_reports:
            return self.prebuilt_reports[key]["name"]
        if key in self.custom_reports:
            return self.custom_reports[key]["name"]
        return f"[Unknown: {key}]"

    def _handle_create_custom_report(self):
        print("\nLaunching custom report wizard...")
        report = ReportDefinition.from_wizard()
        if not report:
            print("Wizard canceled.")
            return

        config = report.to_dict()
        name = config["name"]
        key = f"custom:{name.lower().replace(' ', '_')}"

        if key in self.custom_reports or key in self.prebuilt_reports:
            print("A report with that name already exists.")
            return

        self.custom_reports[key] = config
        self.selected_report_keys.append(key)
        self._save_user_state()
        print(f"Custom report '{name}' created and selected.")

    # -----------------------------
    # Helpers
    # -----------------------------

    def _fuzzy_match_ingredient(self, user_input: str) -> str | None:
        cleaned = user_input.strip().lower()
        for valid in self.valid_ingredients:
            if valid.lower() == cleaned:
                return valid
        matches = difflib.get_close_matches(cleaned, self.valid_ingredients, n=1, cutoff=0.7)
        if matches:
            return matches[0]
        if len(cleaned) <= 4:
            matches = difflib.get_close_matches(cleaned, self.valid_ingredients, n=1, cutoff=0.5)
            if matches:
                return matches[0]
        return None

    def _get_ingredient_stat(self, name: str, stat: str):
        return self._data.get("ingredient_stats", {}).get(name, {}).get(stat)

    def _set_ingredient_stat(self, name: str, stat: str, value):
        if "ingredient_stats" not in self._data:
            self._data["ingredient_stats"] = {}
        if name not in self._data["ingredient_stats"]:
            self._data["ingredient_stats"][name] = {}
        self._data["ingredient_stats"][name][stat] = value
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    # -----------------------------
    # User State + Settings
    # -----------------------------

    def _load_settings(self) -> dict:
        state = self._load_user_state()
        current_settings = state.get("settings", {})
        # Fill in defaults from settings_info if missing
        for key, meta in self.settings_info.items():
            if key not in current_settings:
                current_settings[key] = meta.get("default")
        return current_settings

    def _save_settings(self):
        state = self._load_user_state()
        state["settings"] = self.settings
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def _handle_settings_command(self):
        while True:
            print("\n    ====== User Settings ======")
            keys = list(self.settings_info.keys())
            for i, key in enumerate(keys, start=1):
                info = self.settings_info[key]
                value = self.settings.get(key)
                print(f"{i}. {info['name']} = {value}")
                for line in info['description'].splitlines():
                    print(f"    {line}")

            print("\nEnter the number of a setting to edit it, or anything else to return to the main menu.")
            choice = input("> ").strip()

            if not choice.isdigit():
                return

            index = int(choice) - 1
            if not (0 <= index < len(keys)):
                print("Invalid selection.")
                continue

            selected_key = keys[index]
            info = self.settings_info[selected_key]
            current_value = self.settings[selected_key]

            print(f"\nEditing {info['name']} (current value: {current_value})")
            new_value = input("New value: ").strip()

            if not new_value:
                print("No input entered. Cancelling.")
                continue

            if "validation" in info:
                import re
                if not re.match(info["validation"], new_value, re.IGNORECASE):
                    print("Invalid input format.")
                    continue

            # Cast to bool or int based on type of default
            default_type = type(info["default"])
            try:
                if default_type == bool:
                    new_value_cast = new_value.lower() == "true"
                else:
                    new_value_cast = default_type(new_value)
            except ValueError:
                print(f"Invalid type. Expected {default_type.__name__}.")
                continue

            self.settings[selected_key] = new_value_cast
            self._save_settings()
            print(f"{info['name']} updated to {new_value_cast}.")


    # -----------------------------
    # Complex Handlers
    # -----------------------------

    def handle_inv(self, input_str: str, inventory: int) -> int:
        changes = [item.strip() for item in input_str.split(",") if item.strip()]
        for token in changes:
            is_removal = token.startswith("-")
            raw = token[1:].strip() if is_removal else token.strip()

            matched = self._fuzzy_match_ingredient(raw)
            if not matched:
                print(f"Unrecognized ingredient: '{raw}'")
                continue

            mask = IngredientCoder.ingredient_to_bit(matched)
            if is_removal:
                if inventory & mask:
                    inventory &= ~mask
                    print(f"Removed {matched}")
                else:
                    print(f"{matched} not in inventory")
            else:
                if inventory & mask:
                    print(f"{matched} already present")
                else:
                    inventory |= mask
                    print(f"Added {matched}")
        return inventory

    def _prompt_user_for_pair(self, scored_pairs):
        total = len(scored_pairs)
        for i, (stress_total, without, _) in enumerate(reversed(scored_pairs)):
            names = IngredientCoder.int_to_cookjob_tuple(without)
            print(f"{total - i}: Stress={stress_total:2d} | {', '.join(names)}")
        print("Enter pair number to use or 'cancel':")
        try:
            user_input = input("Choose pair #: ").strip().lower()
            if user_input == "cancel":
                return None
            sel = int(user_input) - 1
            return scored_pairs[sel]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return None


    def _handle_solve(self, ingredient_name: str):
        matched = self._fuzzy_match_ingredient(ingredient_name)
        if not matched:
            print(f"Unrecognized ingredient: '{ingredient_name}'")
            return

        print(f"Solving for: {matched}")
        ingredient_bit = IngredientCoder.ingredient_to_bit(matched)
        inventory_ingredients = IngredientCoder.int_to_cookjob_tuple(self.inventory_bitmask)
        stress_cache = {
            ing: self._get_ingredient_stat(ing, "stress")
            for ing in inventory_ingredients
            if self._get_ingredient_stat(ing, "stress") is not None
        }

        valid_jobs = self.recipe_manager.get_valid_cookjobs_from_inventory(self.inventory_bitmask)
        pairs = self.recipe_manager.find_isolation_pairs_for_ingredient(ingredient_bit, valid_jobs)
        if not pairs:
            print("No isolation pairs found with current inventory.")
            return

        scored_pairs = []
        for without, with_ in pairs:
            without_ings = IngredientCoder.int_to_cookjob_tuple(without)
            total_stress = sum(stress_cache.get(ing, 0) for ing in without_ings)
            scored_pairs.append((total_stress, without, with_))

        scored_pairs.sort(reverse=True)
        chosen = scored_pairs[0] if scored_pairs[0][0] >= 34 else self._prompt_user_for_pair(scored_pairs)
        if not chosen:
            return

        _, job_without, job_with = chosen
        tuple_without = IngredientCoder.int_to_cookjob_tuple(job_without)
        tuple_with = IngredientCoder.int_to_cookjob_tuple(job_with)

        name_without = self.recipe_manager.get_recipe_name_by_id(
            self.recipe_manager.get_recipe_id_for_cookjob(job_without))
        name_with = self.recipe_manager.get_recipe_name_by_id(
            self.recipe_manager.get_recipe_id_for_cookjob(job_with))

        print("\n---\nCraft and test both recipes as described.\n")
        print(f'Cook "{name_without}" with: {", ".join(tuple_without)}')
        raw_input = input("hunger, stress, sell_value> ").strip()
        try:
            hw, sw, vw = map(int, raw_input.split(","))
        except ValueError:
            print("Invalid input.")
            return

        print(f'\nCook "{name_with}" with: {", ".join(tuple_with)}')
        raw_input = input("hunger, stress, sell_value> ").strip()
        try:
            hw2, sw2, vw2 = map(int, raw_input.split(","))
        except ValueError:
            print("Invalid input.")
            return

        new_stats = {"hunger": hw2 - hw, "stress": sw2 - sw, "sell_value": vw2 - vw}
        prev = {k: self._get_ingredient_stat(matched, k) for k in new_stats}

        for k in new_stats:
            if prev[k] is None:
                print(f"New stat {k} = {new_stats[k]}")
            elif prev[k] != new_stats[k]:
                print(f"Overriding {k}: {prev[k]} → {new_stats[k]}")
            else:
                print(f"{k.title()} confirmed: {new_stats[k]}")

        for stat, val in new_stats.items():
            self._set_ingredient_stat(matched, stat, val)
            self.stats_cache.rebuild_and_save()


    def _handle_exit(self):
        print("Exiting.")
        sys.exit(0)
