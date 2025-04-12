import pandas as pd
from cookjob_stats_cache import CookjobStatsCache
from recipe_manager import RecipeManager
from ingredient_coder import IngredientCoder
from report_definition import ReportDefinition
import math
import os
import json

SURPLUS_MULTIPLIER = 0.5

class CookjobReporter:
    # Constants used in the formulas to predict Advanced and Legendary cook percentage from skill level
    LEGENDARY_SLOPE = 0.011024217514
    LEGENDARY_INTERCEPT = -0.102421751380
    ADVANCED_K = 0.000261441631347055
    ADVANCED_DENOMINATOR = 1 - math.exp(-50 * ADVANCED_K)

    # Multiplier constants declared at the class level:
    BASE_MULTIPLIER = 1.0
    ADV_STRESS_MULTIPLIER = 1.25
    ADV_SELL_MULTIPLIER = 1.20
    LEG_STRESS_MULTIPLIER = 1.5
    LEG_SELL_MULTIPLIER = 1.4

    def __init__(self, recipe_manager: RecipeManager, stats_cache: CookjobStatsCache):
        self.recipe_manager = recipe_manager
        self.stats_cache = stats_cache
        self.multiplier_cache = {}  # For caching computed quality multipliers by skill level.
        
        # Instantiate the shop pricing handler at the instance level.
        from shop_pricing_handler import ShopPricingHandler
        self.shop_pricing_handler = ShopPricingHandler()
        
        # Load pricing data from cache or build it if not found.
        cache_dir = "cache"
        cache_file = os.path.join(cache_dir, "pricing_data.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                self.cached_pricing_data = json.load(f)
        else:
            print("Cache not found. Building pricing data...")
            # Build pricing data for both supported modes.
            self.cached_pricing_data = {}
            for mode in ["cheapest_only", "buyout"]:
                df = self.shop_pricing_handler.get_pricing_table(mode)
                # Convert the DataFrame to a dict keyed by ingredient name.
                self.cached_pricing_data[mode] = df.set_index("Name").to_dict("index")
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_file, "w") as f:
                json.dump(self.cached_pricing_data, f)
            print("Pricing data built and saved to cache.")

    def build_report(
        self,
        report_def: "ReportDefinition",
        inventory_bitmask: int,
        surplus_bitmask: int | None = None,
        cooking_skill: int = 0
    ) -> pd.DataFrame:
        """
        Build a modular cookjob report based on the provided ReportDefinition.
        
        Workflow:
          1. Obtain the list of valid cookjob keys:
             - If report_def.inventory_only is True, use the inventory-filtered list.
             - Otherwise, use all valid cookjobs from the recipe manager.
          2. Build a DataFrame (from stats cache) keyed by cookjob keys, retaining the
             hunger, stress, and sell_value columns.
          
          --- Value Side ---
          3. Retrieve quality multipliers for the given cooking_skill using get_multiplier_tuple.
          4. Compute a preliminary 'ValueScore' per cookjob as the weighted sum of:
               hunger * hunger_multiplier,
               stress * stress_multiplier, and
               sell_value * sell_multiplier,
             using report_def.hunger_weight, stress_weight, and sell_weight.
          
          --- Cost Side ---
          5. If report_def.cost_evaluation_mode is not 'none':
               - Map the report_def.ingredient_source_mode to a pricing mode and retrieve the cached pricing data.
               - Disqualify any cookjob that contains ingredients not sold in a store using a bitmask filter.
               - For each cookjob, compute an average cost per ingredient.
               - Depending on cost_evaluation_mode ('subtract' or 'ratio'), adjust the ValueScore.
          
          --- Production Bonus ---
          6. If report_def.production_mode is 'bulk':
               - Retrieve a pricing DataFrame for production bonus calculations.
               - Compute and normalize an availability value for each ingredient.
               - For each cookjob, use the minimum availability among its ingredients as a multiplier.
          
          --- Surplus Bonus ---
          7. For each cookjob, compute a surplus bonus (each matching ingredient adds report_def.surplus_modifier)
             and multiply the cookjob's score accordingly.
          
          8. Expand the ingredients bitmap into a comma-separated string.
          9. Return a DataFrame with columns: Name, Hunger, Stress, Sell Value, Score, Ingredients.
          
          :param report_def: The ReportDefinition instance with report configuration.
          :param inventory_bitmask: Bitmask representing available inventory.
          :param surplus_bitmask: Bitmask representing surplus ingredients (if any).
          :param cooking_skill: The player's cooking skill level.
          :return: A pandas DataFrame containing the final report.
        """
        # (1) Get list of cookjobs based on inventory_only setting.
        if report_def.inventory_only:
            job_keys = self.recipe_manager.get_valid_cookjobs_from_inventory(inventory_bitmask)
        else:
            job_keys = self.recipe_manager.valid_cookjobs.copy()
        
        # (2) Build the base DataFrame using the stats cache.
        df = self.stats_cache.get_dataframe()
        df = df[df.index.isin(job_keys)].copy()
        
        # (3) Get quality multipliers based on the user's cooking skill.
        hunger_mult, stress_mult, sell_mult = self.get_multiplier_tuple(cooking_skill)
        
        # (4) Compute preliminary ValueScore applying report weights.
        df["ValueScore"] = (
            report_def.hunger_weight * df["hunger"] * hunger_mult +
            report_def.stress_weight * df["stress"] * stress_mult +
            report_def.sell_weight * df["sell_value"] * sell_mult
        )
        
        # (5) Cost evaluation: adjust ValueScore based on ingredient cost.
        if report_def.cost_evaluation_mode != "none":
            # Map the user's ingredient_source_mode to the pricing mode key for cached data.
            if report_def.ingredient_source_mode == "cheapest_producing":
                pricing_mode = "cheapest_only"
            elif report_def.ingredient_source_mode in ["buyout_producing", "buyout_producing_and_normal"]:
                pricing_mode = "buyout"
            else:
                pricing_mode = report_def.ingredient_source_mode  # Fallback

            # Retrieve the pricing data from our cached pricing data dictionary.
            pricing_data = self.cached_pricing_data.get(pricing_mode)
            if pricing_data is None:
                pricing_df = self.shop_pricing_handler.get_pricing_table(pricing_mode)
                pricing_data = pricing_df.set_index("Name").to_dict("index")
            
            # Precompute a bitmask for store-available ingredients.
            store_mask = 0
            for ing in pricing_data.keys():
                store_mask |= IngredientCoder.ingredient_to_bit(ing)
            
            # Filter out cookjobs that include any ingredient not sold in a store.
            mask = df.index.to_series().apply(lambda x: (x & store_mask) == x)
            df = df[mask]
            
            # Define function to compute average cost for a cookjob.
            def compute_cost(ings: list[str]) -> float:
                total_cost = 0.0
                count = 0
                for ing in ings:
                    info = pricing_data.get(ing)
                    if info is None:
                        continue
                    if report_def.ingredient_source_mode == "buyout_producing_and_normal":
                        num_prod = info.get("NumProduces", 0)
                        num_norm = info.get("NumNormal", 0)
                        total_shops = num_prod + num_norm
                        if total_shops == 0:
                            cost = info.get("ProducesPricePerItem", 0)
                        else:
                            cost = (
                                info.get("ProducesPricePerItem", 0) * (num_prod / total_shops) +
                                info.get("NormalPricePerItem", 0) * (num_norm / total_shops)
                            )
                    else:
                        cost = info.get("ProducesPricePerItem", 0)
                    total_cost += cost
                    count += 1
                return total_cost / count if count > 0 else 0.0
            
            # Also, compute the total (summed) ingredient cost for the "IngBuy" column.
            def compute_total_cost(ings: list[str]) -> float:
                total_cost = 0.0
                for ing in ings:
                    info = pricing_data.get(ing)
                    if info is None:
                        continue
                    if report_def.ingredient_source_mode == "buyout_producing_and_normal":
                        num_prod = info.get("NumProduces", 0)
                        num_norm = info.get("NumNormal", 0)
                        total_shops = num_prod + num_norm
                        if total_shops == 0:
                            cost = info.get("ProducesPricePerItem", 0)
                        else:
                            cost = (
                                info.get("ProducesPricePerItem", 0) * (num_prod / total_shops) +
                                info.get("NormalPricePerItem", 0) * (num_norm / total_shops)
                            )
                    else:
                        cost = info.get("ProducesPricePerItem", 0)
                    total_cost += cost
                return total_cost

            # Compute average cost (to adjust ValueScore)...
            df["Cost"] = df["ingredients"].apply(compute_cost)
            # ...and total cost for the new "IngBuy" column.
            df["IngBuy"] = df["ingredients"].apply(compute_total_cost)
            
            # Adjust ValueScore based on cost.
            if report_def.cost_evaluation_mode == "subtract":
                df["ValueScore"] = df["ValueScore"] - df["Cost"]
            elif report_def.cost_evaluation_mode == "ratio":
                # Normalize cost to the range [0.8, 1.2].
                min_cost = df["Cost"].min()
                max_cost = df["Cost"].max()
                def normalize_cost(cost):
                    if max_cost == min_cost:
                        return 1.0
                    return 0.8 + ((cost - min_cost) / (max_cost - min_cost)) * 0.4  # because 1.2-0.8=0.4
                df["NormalizedCost"] = df["Cost"].apply(normalize_cost)
                df["ValueScore"] = df.apply(
                    lambda row: row["ValueScore"] / row["NormalizedCost"] if row["Cost"] != 0 else row["ValueScore"],
                    axis=1,
                )
                df.drop("NormalizedCost", axis=1, inplace=True)

        
        # (6) Production Bonus: apply availability multiplier if production_mode is 'bulk'.
        if report_def.production_mode == "bulk":
            if report_def.ingredient_source_mode == "cheapest_producing":
                bulk_mode = "cheapest_only"
            elif report_def.ingredient_source_mode in ["buyout_producing", "buyout_producing_and_normal"]:
                bulk_mode = "buyout"
            else:
                bulk_mode = report_def.ingredient_source_mode
            pricing_df_bulk = self.shop_pricing_handler.get_pricing_table(bulk_mode).copy()
            
            def compute_availability(row):
                if report_def.ingredient_source_mode != "buyout_producing_and_normal":
                    num_shops = row["NumProduces"]
                else:
                    num_shops = row["NumProduces"] + row["NumNormal"]
                num_shops = max(num_shops, 0)
                return row["ProducesStockPerPickup"] * (num_shops ** 0.5)
            
            pricing_df_bulk["Availability"] = pricing_df_bulk.apply(compute_availability, axis=1)
            min_avail = pricing_df_bulk["Availability"].min()
            max_avail = pricing_df_bulk["Availability"].max()
            def normalize(avail: float) -> float:
                if max_avail == min_avail:
                    return 1.0
                return 0.5 + ((avail - min_avail) / (max_avail - min_avail))
            pricing_df_bulk["NormAvailability"] = pricing_df_bulk["Availability"].apply(normalize)
            availability_dict = pricing_df_bulk.set_index("Name")["NormAvailability"].to_dict()
            
            def min_availability_for_cookjob(ings: list[str]) -> float:
                values = []
                for ing in ings:
                    value = availability_dict.get(ing)
                    if value is not None:
                        values.append(value)
                return min(values) if values else 1.0
            
            df["AvailMultiplier"] = df["ingredients"].apply(min_availability_for_cookjob)
            df["ValueScore"] *= df["AvailMultiplier"]
        
        # (7) Surplus Bonus: adjust ValueScore for surplus ingredients.
        if surplus_bitmask is not None:
            def compute_surplus_bonus(ings: list[str]) -> float:
                bonus = 0.0
                for ing in ings:
                    if IngredientCoder.ingredient_to_bit(ing) & surplus_bitmask:
                        bonus += report_def.surplus_modifier
                return bonus
            df["SurplusBonus"] = df["ingredients"].apply(compute_surplus_bonus)
            df["ValueScore"] *= (1 + df["SurplusBonus"])
        
        # (8) Finalize the report: convert ingredient lists to a comma-separated string.
        df["Ingredients"] = df["ingredients"].apply(lambda ings: ", ".join(ings))
        df.rename(
            columns={
                "recipe_name": "Name",
                "hunger": "Hunger",
                "stress": "Stress",
                "sell_value": "Sell Value",
            },
            inplace=True,
        )
        
        # (9) Return only the report columns, with Ingredients, Score, and optionally IngBuy first, then sort by Score descending.
        output_cols = ["Name", "Ingredients", "ValueScore"]
        if "IngBuy" in df.columns:
            output_cols.append("IngBuy")
        output_cols.extend(["Hunger", "Stress", "Sell Value"])

        report_df = df[output_cols].copy()
        report_df.rename(columns={"ValueScore": "Score"}, inplace=True)

        final_order = ["Name", "Ingredients", "Score"]
        if "IngBuy" in report_df.columns:
            final_order.append("IngBuy")
        final_order.extend(["Hunger", "Stress", "Sell Value"])

        report_df = report_df[final_order]
        report_df.sort_values(by="Score", ascending=False, inplace=True)

        report_df["Score"] = report_df["Score"].round(1)
        if "IngBuy" in report_df.columns:
            report_df["IngBuy"] = report_df["IngBuy"].round(1)

        return report_df




    ### --- For Advanced and Legendary considerations if skill is >11)

    def get_quality_distribution(self, skill_level: int) -> tuple[float, float, float]:
        """
        Returns a tuple of (normal_pct, advanced_pct, legendary_pct) for a given skill level.
        All values are floats in [0, 1], and sum to 1.
        """
        if skill_level <= 10:
            return 1.0, 0.0, 0.0

        elif skill_level <= 20:
            # No legendary chance in this range
            adv_numerator = 1 - math.exp(-self.ADVANCED_K * skill_level)
            pct_advanced = adv_numerator / self.ADVANCED_DENOMINATOR
            pct_advanced = min(max(pct_advanced, 0.0), 1.0)
            pct_normal = 1.0 - pct_advanced
            return pct_normal, pct_advanced, 0.0

        else:
            # Skill 21 and above
            pct_legendary = self.LEGENDARY_SLOPE * skill_level + self.LEGENDARY_INTERCEPT
            pct_legendary = min(max(pct_legendary, 0.0), 1.0)

            adv_numerator = 1 - math.exp(-self.ADVANCED_K * skill_level)
            pct_advanced_raw = adv_numerator / self.ADVANCED_DENOMINATOR
            pct_advanced_raw = min(max(pct_advanced_raw, 0.0), 1.0)

            pct_advanced = (1.0 - pct_legendary) * pct_advanced_raw
            pct_advanced = min(max(pct_advanced, 0.0), 1.0)

            pct_normal = 1.0 - pct_legendary - pct_advanced
            pct_normal = min(max(pct_normal, 0.0), 1.0)

            return pct_normal, pct_advanced, pct_legendary

    def get_multiplier_tuple(self, skill_level: int) -> tuple[float, float, float]:
        """
        Returns a multiplier tuple (hunger_multiplier, stress_multiplier, sell_multiplier) that
        adjusts the respective values based on the quality distribution for the given skill level.
        
        - Hunger is not affected (multiplier is 1.0).
        - Advanced items multiply stress by 1.25 and sell value by 1.20.
        - Legendary items multiply stress by 1.5 and sell value by 1.4.
        
        The returned tuple represents the weighted average multipliers based on the chance of producing
        normal, advanced, and legendary items. Results are cached at the instance level.
        """
        # Return from cache if available
        if skill_level in self.multiplier_cache:
            return self.multiplier_cache[skill_level]

        # Retrieve quality percentages for the skill level.
        norm_pct, adv_pct, leg_pct = self.get_quality_distribution(skill_level)

        # For hunger, there's no change regardless of quality.
        hunger_multiplier = self.BASE_MULTIPLIER  # i.e., 1.0

        # Calculate stress and sell multipliers as the weighted sums.
        stress_multiplier = (
            norm_pct * self.BASE_MULTIPLIER +
            adv_pct * self.ADV_STRESS_MULTIPLIER +
            leg_pct * self.LEG_STRESS_MULTIPLIER
        )
        sell_multiplier = (
            norm_pct * self.BASE_MULTIPLIER +
            adv_pct * self.ADV_SELL_MULTIPLIER +
            leg_pct * self.LEG_SELL_MULTIPLIER
        )

        # Form the multiplier tuple.
        multipliers = (hunger_multiplier, stress_multiplier, sell_multiplier)
        # Cache the computed tuple.
        self.multiplier_cache[skill_level] = multipliers
        return multipliers

    def _filter_inventory_jobs(self, inventory_bitmask: int) -> pd.DataFrame:
        valid_jobs = self.recipe_manager.get_valid_cookjobs_from_inventory(inventory_bitmask)
        df = self.stats_cache.get_dataframe()
        return df[df.index.isin(valid_jobs)]

    def _apply_surplus_bonus(self, df: pd.DataFrame, surplus_bitmask: int | None, base_expr: str) -> pd.DataFrame:
        """
        Computes a weighted score for sorting purposes and stores it in a 'Score' column.
        Applies a multiplier bonus based on how many surplus ingredients are used.
        Rounds final score to nearest integer.
        """
        df["Score"] = df.eval(base_expr)

        if surplus_bitmask:
            df["surplus_count"] = df["ingredients"].apply(
                lambda ings: sum(IngredientCoder.ingredient_to_bit(ing) & surplus_bitmask > 0 for ing in ings)
            )
            df["Score"] = df["Score"] * (1 + df["surplus_count"] * SURPLUS_MULTIPLIER)

        df["Score"] = df["Score"].round(0).astype(int)
        return df

    def get_best_road_food(self, inventory_bitmask: int, surplus_bitmask: int | None = None) -> pd.DataFrame:
        df = self._filter_inventory_jobs(inventory_bitmask).copy()
        df = self._apply_surplus_bonus(df, surplus_bitmask, base_expr="hunger + stress")

        result = df.sort_values(by="Score", ascending=False).head(10)[
            [col for col in ["recipe_name", "ingredients", "hunger", "stress", "sell_value", "Score"] if col in df.columns]
        ].reset_index(drop=True)

        result["ingredients"] = result["ingredients"].apply(lambda x: ", ".join(x))
        rename_map = {
            "recipe_name": "Recipe",
            "ingredients": "Ingredients",
            "hunger": "Hunger",
            "stress": "Stress",
            "sell_value": "Sell"
        }
        result.rename(columns={k: v for k, v in rename_map.items() if k in result.columns}, inplace=True)

        # Ensure Score is last if it exists
        if "Score" in result.columns:
            cols = [col for col in result.columns if col != "Score"] + ["Score"]
            result = result[cols]

        return result

    def get_best_sale_food(self, inventory_bitmask: int, surplus_bitmask: int | None = None) -> pd.DataFrame:
        df = self._filter_inventory_jobs(inventory_bitmask).copy()
        df = self._apply_surplus_bonus(df, surplus_bitmask, base_expr="sell_value")

        result = df.sort_values(by="Score", ascending=False).head(10)[
            [col for col in ["recipe_name", "ingredients", "hunger", "stress", "sell_value", "Score"] if col in df.columns]
        ].reset_index(drop=True)

        result["ingredients"] = result["ingredients"].apply(lambda x: ", ".join(x))
        rename_map = {
            "recipe_name": "Recipe",
            "ingredients": "Ingredients",
            "hunger": "Hunger",
            "stress": "Stress",
            "sell_value": "Sell"
        }
        result.rename(columns={k: v for k, v in rename_map.items() if k in result.columns}, inplace=True)

        # Ensure Score is last if it exists
        if "Score" in result.columns:
            cols = [col for col in result.columns if col != "Score"] + ["Score"]
            result = result[cols]

        return result



def main():
    pd.set_option("display.max_columns", None)
    pd.set_option("display.expand_frame_repr", False)
    from ingredient_coder import IngredientCoder
    # Fixed inventory for testing
    test_ingredients = [
        "Water", "Salt", "Seasoning", "Eggs", "Rations",
        "Bread", "Cheese", "Ham", "Pork", "Vegetables"
    ]

    # Convert to bitmask using static method
    inventory_bitmask = IngredientCoder.cookjob_tuple_to_int(tuple(test_ingredients))

    # Initialize core systems
    recipe_manager = RecipeManager()
    stats_cache = CookjobStatsCache(recipe_manager)
    stats_cache.load_or_build()  # Ensures cache is available

    # Create the reporter
    reporter = CookjobReporter(recipe_manager, stats_cache)

    # Run both reports
    print("\n=== Best Road Food ===")
    print(reporter.get_best_road_food(inventory_bitmask).to_string(index=False))

    print("\n=== Best Sale Food ===")
    print(reporter.get_best_sale_food(inventory_bitmask).to_string(index=False))

    # Observed data for skills 10–51
    observed_data = [
        (10, 1, 0, 0), (11, 0.784328193, 0.215671807, 0), (12, 0.7599765717, 0.2400234283, 0),
        (13, 0.7424236859, 0.2575763141, 0), (14, 0.7201589542, 0.2798410458, 0),
        (15, 0.6954392837, 0.3045607163, 0), (16, 0.6765305405, 0.3234694595, 0),
        (17, 0.6648441771, 0.3351558229, 0), (18, 0.6372600625, 0.3627399375, 0),
        (19, 0.617768595, 0.382231405, 0), (20, 0.5968229423, 0.4031770577, 0),
        (21, 0.5124505639, 0.3661564377, 0.1213929984), (22, 0.4847462443, 0.3801896509, 0.1350641048),
        (23, 0.458677686, 0.396337988, 0.144984326), (24, 0.4403894601, 0.4046435623, 0.1549669776),
        (25, 0.4152633825, 0.4177478356, 0.1669887819), (26, 0.3940036868, 0.4289937741, 0.177002539),
        (27, 0.3704524664, 0.437548378, 0.1919991556), (28, 0.3503779303, 0.450067923, 0.1995541468),
        (29, 0.3330207682, 0.4541571161, 0.2128221157), (30, 0.3058675783, 0.4699644178, 0.2241680039),
        (31, 0.2926347865, 0.4726617958, 0.2347034177), (32, 0.2730011427, 0.4753627203, 0.251636137),
        (33, 0.2507229413, 0.4930459928, 0.2562310658), (34, 0.2338690496, 0.4971288777, 0.2690020726),
        (35, 0.2166554054, 0.5078378378, 0.2755067568), (36, 0.2004799833, 0.508330145, 0.2911898717),
        (37, 0.1815920398, 0.5195938118, 0.2988141484), (38, 0.1652314316, 0.526742465, 0.3080261033),
        (39, 0.1480382679, 0.5296509884, 0.3223107437), (40, 0.1330711024, 0.5323177439, 0.3346111537),
        (41, 0.118570619, 0.5386512884, 0.3427780926), (42, 0.1037367912, 0.5407180239, 0.3555451848),
        (43, 0.0881696057, 0.5442848095, 0.3675455849), (44, 0.0750358345, 0.5505850195, 0.374379146),
        (45, 0.0586019534, 0.5458181939, 0.3955798527), (46, 0.0470682356, 0.5573852462, 0.3955465182),
        (47, 0.0344344811, 0.5502183406, 0.4153471782), (48, 0.0225340845, 0.5577852595, 0.419680656),
        (49, 0.01230041, 0.5555851862, 0.4321144038), (50, 0, 0.5557859532, 0.4442140468),
        (51, 0, 0.5432514417, 0.4567485583)
    ]

    rows = []
    for skill, norm_obs, adv_obs, leg_obs in observed_data:
        norm_pred, adv_pred, leg_pred = reporter.get_quality_distribution(skill)
        row = {
            "Skill": skill,
            "Norm % Dev": 100 * (norm_pred - norm_obs) / norm_obs if norm_obs else float('inf'),
            "Adv % Dev": 100 * (adv_pred - adv_obs) / adv_obs if adv_obs else float('inf'),
            "Leg % Dev": 100 * (leg_pred - leg_obs) / leg_obs if leg_obs else float('inf'),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    print("\n=== Deviation from Observed Quality Probabilities (percent) ===")
    print(df.to_string(index=False, formatters={
        "Norm % Dev": "{:.2f}".format,
        "Adv % Dev": "{:.2f}".format,
        "Leg % Dev": "{:.2f}".format,
    }))

def test_manual_report():
    import pandas as pd
    from ingredient_coder import IngredientCoder
    from recipe_manager import RecipeManager
    from cookjob_stats_cache import CookjobStatsCache
    from cookjob_reporter import CookjobReporter
    from report_definition import ReportDefinition  # Assumes ReportDefinition is implemented per your description
    
    # Ensure DataFrame display settings are appropriate.
    pd.set_option("display.max_columns", None)
    pd.set_option("display.expand_frame_repr", False)
    
    # Manually create a ReportDefinition instance.
    # Adjust these parameters to experiment with different report behaviors.
    report_def = ReportDefinition(
        name="Test Manual Report",
        inventory_only=True,                # Only consider cookjobs available from current inventory.
        hunger_weight=0.5,                  # Weight for hunger value.
        stress_weight=0.3,                  # Weight for stress value.
        sell_weight=0.2,                    # Weight for sell value.
        surplus_modifier=0.5,               # Bonus per surplus ingredient.
        cost_evaluation_mode="subtract",    # Options: 'none', 'subtract', or 'ratio'
        ingredient_source_mode="cheapest_producing", # Pricing mode options: "cheapest_producing", "buyout_producing", "buyout_producing_and_normal"
        production_mode="individual"        # Options: "individual" for per-craft, "bulk" for production-based multiplier.
    )
    
    # Fixed test inventory.
    test_ingredients = [
        "Water", "Salt", "Seasoning", "Eggs", "Rations",
        "Bread", "Cheese", "Ham", "Pork", "Vegetables"
    ]
    
    # Convert test ingredients to a bitmask.
    inventory_bitmask = IngredientCoder.cookjob_tuple_to_int(tuple(test_ingredients))
    
    # For testing, we can also assume that every ingredient is surplus.
    surplus_bitmask = inventory_bitmask
    
    # Initialize core systems.
    recipe_manager = RecipeManager()
    stats_cache = CookjobStatsCache(recipe_manager)
    stats_cache.load_or_build()  # Build or load the cookjob stats cache.
    
    # Create the reporter.
    reporter = CookjobReporter(recipe_manager, stats_cache)
    
    # Set a sample cooking skill level (you can modify this to test different quality multipliers).
    cooking_skill = 30
    
    # Build the report using the new build_report method.
    report_df = reporter.build_report(report_def, inventory_bitmask, surplus_bitmask, cooking_skill)
    
    print("\n=== Manual Report for '{}' ===".format(report_def.name))
    print(report_df.to_string(index=False))

if __name__ == "__main__":
    test_manual_report()