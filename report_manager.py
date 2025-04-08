import pandas as pd
from cookjob_stats_cache import CookjobStatsCache
from recipe_manager import RecipeManager

class ReportManager:
    def __init__(self, manager: RecipeManager, stats_cache: CookjobStatsCache):
        self.manager = manager
        self.stats_cache = stats_cache

    def _filter_inventory_jobs(self, inventory_bitmask: int) -> pd.DataFrame:
        valid_jobs = self.manager.get_valid_cookjobs_from_inventory(inventory_bitmask)
        df = self.stats_cache.get_dataframe()
        return df[df.index.isin(valid_jobs)]

    def get_best_road_food(self, inventory_bitmask: int) -> pd.DataFrame:
        df = self._filter_inventory_jobs(inventory_bitmask).copy()
        df["travel_score"] = df["hunger"] + df["stress"]
        result = df.sort_values(by="travel_score", ascending=False).head(10)[
            ["recipe_name", "ingredients", "hunger", "stress", "sell_value"]
        ].reset_index(drop=True)

        result["ingredients"] = result["ingredients"].apply(lambda x: ", ".join(x))
        result.columns = ["Recipe", "Ingredients", "Hunger", "Stress", "Sell"]
        return result

    def get_best_sale_food(self, inventory_bitmask: int) -> pd.DataFrame:
        df = self._filter_inventory_jobs(inventory_bitmask)
        result = df.sort_values(by="sell_value", ascending=False).head(10)[
            ["recipe_name", "ingredients", "hunger", "stress", "sell_value"]
        ].reset_index(drop=True)

        result["ingredients"] = result["ingredients"].apply(lambda x: ", ".join(x))
        result.columns = ["Recipe", "Ingredients", "Hunger", "Stress", "Sell"]
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
    manager = RecipeManager()
    stats_cache = CookjobStatsCache(manager)
    stats_cache.load_or_build()  # Ensures cache is available

    # Create the reporter
    reporter = CookjobReporter(manager, stats_cache)

    # Run both reports
    print("\n=== Best Road Food ===")
    print(reporter.get_best_road_food(inventory_bitmask).to_string(index=False))

    print("\n=== Best Sale Food ===")
    print(reporter.get_best_sale_food(inventory_bitmask).to_string(index=False))

if __name__ == "__main__":
    main()