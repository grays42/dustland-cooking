import json
from enum import Enum
from pathlib import Path

"""
report_definition.py

Class ReportDefinition
Handles configuration, validation, and interactive creation of scoring strategies
for cookjob reports in Dustland Delivery. Each report defines how cookjobs are
evaluated, scored, and ranked, incorporating value metrics, cost analysis,
shop behavior, inventory limits, and surplus handling.

Supports:
- Initialization from a saved dictionary of settings
- Interactive wizard for CLI-based report creation
- Validation of all input fields
- Human-readable description of report attributes for UI/CLI display

Loads relevant player state (skills, surplus, bonuses) from 'user_state.json'
under the keys:
- user_settings.cooking_skill
- user_settings.speech_skill
- user_settings.surplus_bonus
- surplus

Used to drive cookjob recommendation engines, profitability calculators,
and strategic planning tools.

Stored Fields:
- name (str)
    Human-readable name for the report (e.g. "Best Road Food from Inventory")

- inventory_only (bool)
    Whether to only consider cookjobs the player can currently make from inventory.
    If False, considers all valid cookjobs using available ingredients on the map.

- hunger_weight (float)
    How much to weight the hunger value of food in scoring (0–1).

- stress_weight (float)
    How much to weight the stress-relief value of food in scoring (0–1).

- sell_weight (float)
    How much to weight the market sell value of the food (0–1).

- cost_evaluation_mode (str)
    How ingredient cost should influence scoring:
    - 'none': Cost is ignored.
    - 'subtract': Ingredient cost is subtracted from value.
    - 'ratio': Value is divided by cost, representing “value per scrap.”

- ingredient_source_mode (str)
    How ingredient costs are estimated (only applicable if cost is used):
    - 'cheapest_producing': Assumes buying at lowest price from producing shops.
    - 'buyout_producing': Assumes buying out full producing stock at max price.
    - 'buyout_producing_and_normal': Includes normal-price shops, weighted by shop count.
    Set to None.

- production_mode (str)
    Whether the report scores cookjobs for single-use value or bulk production:
    - 'individual': Per-craft value only.
    - 'bulk': Score is multiplied by the availability of the rarest ingredient,
      based on shop stock × sqrt(shop count), normalized to a 0.5–1.5 scale.

Instance Methods:
- to_dict() -> dict
    Returns the report definition as a serializable dictionary for saving.

- validate() -> None
    Raises ValueError with detailed messages if any fields are invalid.

- describe_attributes() -> list[str]
    Returns a list of human-readable summary points describing the report logic,
    suitable for display in menus, tooltips, or summaries.

Class Methods:
- from_wizard() -> ReportDefinition | None
    Starts an interactive CLI wizard to configure a report.
    Returns a validated ReportDefinition instance, or None if canceled.

Sample non-wizard construction:
    report_def = ReportDefinition(
        name="Test Manual Report",
        inventory_only=True,                # Only consider cookjobs available from current inventory.
        hunger_weight=0.5,                  # Weight for hunger value.
        stress_weight=0.3,                  # Weight for stress value.
        sell_weight=0.2,                    # Weight for sell value.
        cost_evaluation_mode="subtract",    # Options: 'none', 'subtract', or 'ratio'
        ingredient_source_mode="cheapest_producing", # Pricing mode options: "cheapest_producing", "buyout_producing", "buyout_producing_and_normal"
        production_mode="individual"        # Options: "individual" for per-craft, "bulk" for production-based multiplier.
    )
Note: can also construct with a dict called "config" with these keys.
"""


STATE_PATH = "user_state.json"

class ReportDefinition:
    def __init__(self,
                 name=None,
                 inventory_only=None,
                 hunger_weight=None,
                 stress_weight=None,
                 sell_weight=None,
                 surplus_modifier=0.0,
                 cost_evaluation_mode=None,
                 ingredient_source_mode=None,
                 production_mode=None,
                 config: dict = None):
        self._load_player_state_defaults()
        self.validation_errors = []

        if config:
            # Use values from config dict
            self.name = config.get("name")
            self.inventory_only = config.get("inventory_only")
            self.hunger_weight = config.get("hunger_weight")
            self.stress_weight = config.get("stress_weight")
            self.sell_weight = config.get("sell_weight")
            self.surplus_modifier = config.get("surplus_modifier", 0.0)
            self.cost_evaluation_mode = config.get("cost_evaluation_mode")
            self.ingredient_source_mode = config.get("ingredient_source_mode")
            self.production_mode = config.get("production_mode")
        else:
            # Use explicit keyword arguments
            self.name = name
            self.inventory_only = inventory_only
            self.hunger_weight = hunger_weight
            self.stress_weight = stress_weight
            self.sell_weight = sell_weight
            self.surplus_modifier = surplus_modifier
            self.cost_evaluation_mode = cost_evaluation_mode
            self.ingredient_source_mode = ingredient_source_mode
            self.production_mode = production_mode

    def _load_player_state_defaults(self):
        try:
            with open(STATE_PATH, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}

        self.cooking_skill = int(data.get("user_settings", {}).get("cooking_skill", 0))
        self.speech_skill = int(data.get("user_settings", {}).get("speech_skill", 0))
        self.surplus_bonus = int(data.get("user_settings", {}).get("surplus_bonus", 0))
        self.surplus = set(data.get("surplus", []))

    def to_dict(self):
        return {
            "name": self.name,
            "inventory_only": self.inventory_only,
            "hunger_weight": self.hunger_weight,
            "stress_weight": self.stress_weight,
            "sell_weight": self.sell_weight,
            "surplus_modifier": self.surplus_modifier,
            "cost_evaluation_mode": self.cost_evaluation_mode,
            "ingredient_source_mode": self.ingredient_source_mode,
            "production_mode": self.production_mode,
        }

    def validate(self):
        errors = []

        def in_range(val, name, min_val, max_val):
            if not isinstance(val, (int, float)) or not (min_val <= val <= max_val):
                errors.append(f"{name} must be between {min_val} and {max_val}.")

        if self.inventory_only not in [True, False]:
            errors.append("inventory_only must be True or False.")

        for attr_name in ["hunger_weight", "stress_weight", "sell_weight"]:
            val = getattr(self, attr_name)
            in_range(val, attr_name, 0, 1)

        if self.surplus_modifier is not None:
            if not isinstance(self.surplus_modifier, (int, float)) or self.surplus_modifier < 0:
                errors.append("surplus_modifier must be a non-negative number.")

        if self.cost_evaluation_mode not in ("none", "subtract", "ratio"):
            errors.append("cost_evaluation_mode must be one of: none, subtract, ratio.")

        if self.ingredient_source_mode not in (None, "cheapest_producing", "buyout_producing", "buyout_producing_and_normal"):
            errors.append("ingredient_source_mode must be one of: cheapest_producing, buyout_producing, buyout_producing_and_normal, or None.")

        if self.production_mode not in ("individual", "bulk"):
            errors.append("production_mode must be either 'individual' or 'bulk'.")

        if not self.name:
            errors.append("Report must have a name.")

        self.validation_errors = errors
        if errors:
            raise ValueError("Report definition validation failed:\n- " + "\n- ".join(errors))


    def describe_attributes(self) -> list[str]:
        """
        Returns a human-readable list of report attribute descriptions,
        excluding the report name.
        """
        desc = []

        if self.inventory_only:
            desc.append("Current inventory only")
        else:
            desc.append("All ingredients")

        if (self.hunger_weight or 0) > 0:
            desc.append(f"Hunger {int(self.hunger_weight * 100)}%")
        if (self.stress_weight or 0) > 0:
            desc.append(f"Stress {int(self.stress_weight * 100)}%")
        if (self.sell_weight or 0) > 0:
            desc.append(f"Sell Value {int(self.sell_weight * 100)}%")

        if self.cost_evaluation_mode == "subtract":
            desc.append("Subtracts ingredient cost from value")
        elif self.cost_evaluation_mode == "ratio":
            desc.append("Divides value by ingredient cost")
        else:
            desc.append("Ignores ingredient cost")

        source_desc = {
            "cheapest_producing": "Buys at cheapest prices, Producing stores only",
            "buyout_producing": "Buys out all, Producing stores only",
            "buyout_producing_and_normal": "Buys out all, Producing and Normal stores"
        }
        if self.ingredient_source_mode in source_desc:
            desc.append(source_desc[self.ingredient_source_mode])

        mode_desc = {
            "individual": "Individual recipe scoring",
            "bulk": "Bulk processing scoring (based on shop availability and stock)"
        }
        desc.append(mode_desc.get(self.production_mode, "Unknown scoring mode"))

        return desc



    @classmethod
    def from_wizard(cls):
        print("\n=== Cookjob Report Setup ===")

        self = cls()
        config = {}

        self._load_player_state_defaults()

        # System notes
        print(f"\nNotes:")
        if self.cooking_skill > 10:
            print(f"- You have specified a Cooking skill of {self.cooking_skill}. All reports will amplify the Stress and Sell Value of the dishes according to the chance of making an Advanced or Legendary dish with that cooking skill.")
        if self.speech_skill > 0:
            print(f"- You have specified a Speech skill of {self.speech_skill}. All reports will decrease the ingredient cost according to the probability that you can bargain a 10% discount when purchasing.")
        if self.surplus_bonus > 0:
            print(f"- You have a surplus bonus specified of +{self.surplus_bonus}%. All reports will amplify the final score of a cookjob by this percentage for each item in your surplus list that is also in the cookjob.")

        # Inventory choice
        while True:
            choice = input("\nShould this report only consider cookjobs you can make right now with your current inventory, or include all recipes based on what’s available on the map?\n"
                "  1. INVENTORY ONLY. This is best for “what can I craft now” reports.\n"
                "  2. ALL INGREDIENTS. This is best for planning bulk planning reports.\n"
                "1 or 2 > ").strip()
            if choice in ("1", "2"):
                config["inventory_only"] = choice == "1"
                break
            elif choice.lower() == "c":
                return None
            print("\nInvalid input. Enter 1 or 2, or 'c' to cancel report setup.")

        # Value weights
        value_fields = {
            "Hunger": "hunger_weight",
            "Stress": "stress_weight",
            "Sell Value": "sell_weight"
        }
        for label, key in value_fields.items():
            while True:
                val = input(f"\nHow much do you want to value {label} in this report?\nEnter a percentage (e.g., 100) or 0 to disable > ").strip()
                if val.lower() == "c":
                    return None
                try:
                    val = float(val)
                    if 0 <= val <= 100:
                        config[key] = val/100
                        break
                except Exception:
                    pass
                print("\nInvalid input. Enter a number between 0 and 100 or 'c' to cancel.")


        # Cost Evaluation Mode
        options = {
            "1": "none",
            "2": "subtract",
            "3": "ratio"
        }
        while True:
            val = input("\nHow do you want to consider a cost factor?\n"
                        "1. NONE. This doesn’t consider a cost at all, and is best if you don’t care how the ingredients ended up in your inventory (for example you did some hunting and fishing), you just want to know what the best dish is that you can make for road food or to sell on the market, right now.\n"
                        "2. SUBTRACT. This subtracts the cost factors from the value factors. This is best for sell value profitability analysis, when you want to know what cookjobs give you the greatest flat return on your investment, but is not well suited to weightings involving hunger and stress.\n"
                        "3. RATIO. This is good for relative evaluation of a “bang for your buck” format. You would use this if you want to know what the best road food is per scrap paid on the constituent ingredients.\n1, 2, or 3 > ").strip()
            if val in options:
                config["cost_evaluation_mode"] = options[val]
                break
            elif val.lower() == "c":
                return None
            print("Invalid input. Enter 1, 2, or 3 or 'c' to cancel.")

        # Ingredient Source Mode — only if cost is considered
        if config["cost_evaluation_mode"] != "none":
            options = {
                "1": "cheapest_producing",
                "2": "buyout_producing",
                "3": "buyout_producing_and_normal"
            }
            while True:
                val = input("\nDo you only want to buy goods at the cheapest possible price at producing shops only, or do you want to buyout the entire stock?\n"
                            "1. CHEAPEST AT PRODUCING. Ideal for early game when resources are tight and you need the best bang for your buck. You’ll only purchase items from producing shops and only up to the point where the price starts increasing. This yields low-cost but low-volume ingredient stock, making it great for producing a small number of highly efficient meals.\n"
                            "2. BUYOUT AT PRODUCING. Best if you have cash to spend and want to mass-produce food. You’ll buy out the full stock of each ingredient at all producing shops, accepting higher average prices in exchange for volume.\n"
                            "3. BUYOUT AT PRODUCING + NORMAL. Useful for completeness, but generally poor return on investment. You’ll buy out stock from both producing and normal-price shops. The per-item cost will be weighted based on how many producing vs. normal shops exist on your current map. Good for modeling worst-case acquisition cost.\n"
                            "1, 2, or 3 > ").strip()
                if val in options:
                    config["ingredient_source_mode"] = options[val]
                    break
                elif val.lower() == "c":
                    return None
                print("Invalid input. Enter 1, 2, or 3 or 'c' to cancel.")
        else:
            config["ingredient_source_mode"] = None

        # Bulk vs Individual
        options = {
            "1": "individual",
            "2": "bulk"
        }
        while True:
            val = input("\nIs this an individual recipe value report or a bulk processing value report?\n"
                        "1. INDIVIDUAL. Each cookjob is scored purely on its per-craft value or profitability, without considering how easy it would be to repeat the recipe in bulk.\n"
                        "2. BULK. Each cookjob is scored based on how easy it is to mass-produce. We estimate this by combining two factors for each ingredient: how many units you can buy from shops, times the square root of how many shops carry it on your map. The “availability” score for the least available ingredient is normalized and multiplied against the overall cookjob score. Recipes with rare or low-quantity ingredients will score lower, while recipes that are easy to restock in volume will score higher.\n"
                        "1 or 2 > ").strip()
            if val in options:
                config["production_mode"] = options[val]
                break
            elif val.lower() == "c":
                return None
            print("Invalid input. Enter 1 or 2 or 'c' to cancel.")

        temp = cls()
        temp.config = config
        print("\nHere’s a summary of your report settings:")
        for line in temp.describe_attributes():
            print(f"- {line}")
            
        # Final: name
        while True:
            name = input("\nWhat do you want to name this report? (e.g. 'Road Food from Inventory')\n> ").strip()
            if name:
                config["name"] = name
                break
            elif name.lower() == "c":
                return None
            print("Report name cannot be blank. Or enter 'c' to cancel.")

        # Return fully initialized and validated report
        report = cls(config=config)
        report.validate()
        return report


def main():
    try:
        report = ReportDefinition.from_wizard()
        if report is None:
            print("\nReport setup was cancelled.")
            return

        print("\n=== Report Setup Complete ===")
        print("Here are your report attributes:\n")
        for key, value in report.to_dict().items():
            print(f"  {key}: {value}")

    except ValueError as e:
        print("\n❌ Validation failed:")
        print(e)




if __name__ == "__main__":
    main()
