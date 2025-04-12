import pandas as pd
import json

"""
shop_pricing_handler.py

Class ShopPricingHandler
Loads item price and stock behavior from items_in_shops_stats.csv and filters
to relevant crafting ingredients based on data.json. Provides economic insights
for crafting optimization by computing stock and price behavior under several
common player strategies.

Used to support profitability calculations, pickup value assessment, and
cookjob economic planning by exposing expected shop pricing and availability
data across different gameplay scenarios.

Pricing calculations are status-specific, based on static scalars applied to
known pricing tiers (MinPrice, LowPrice, etc.), and rely on quantity thresholds
to determine when prices are capped or scale linearly.

Modes Supported (via `get_pricing_table(mode)`):
- "cheapest_only":
    Early-game strategy. Only buy from shops *at or above* the lowest-price
    quantity threshold, and always at the minimum unit price. This gives us much
    lower stock (and usually, for Normal shops, no stock at all), but dramatically
    reduced pricing.
  COLUMNS: 

- "buyout":
    Mid/late-game strategy. Buy the *entire stock* from shops. This means the entire
    transaction is executed at the highest possible price, although in-game players
    can optimize a little by fiddling with multiple transactions, but that will not
    be reflected here.

Instance Methods:
- get_pricing_table(mode: str) -> pandas.DataFrame
    Returns a report table based on the selected pricing strategy mode.
    Output is filtered to include only items listed under "valid_ingredients"
    in data.json, and rows are sorted to match that order.
    Columns in the output include:
      - Name
      - ProducesStockPerPickup: Amount of stock picked up, on average, for this item in Producing status.
      - ProducesPricePerItem: The per-item cost for the entire transaction in Producing status.
      - NumProduces: Number of producing shops on the selected map.
      - NormalStockPerPickup: Amount of stock picked up, on average, for this item in Normal status.
      - NormalPricePerItem: The per-item cost for the entire transaction in Normal status.
      - NumNormal: Number of normal shops on the selected map.
"""


DATA_PATH = "data.json"
CSV_PATH = "items_in_shops_stats.csv"
STATE_PATH = "user_state.json"

# These scalars were derived from game observation and reverse engineering.
# They are not contained in the spreadsheet data, so there's a presumption that
# during playtesting the three statuses needed some scalar tweaking across all items.
# These resulted in precisely accurate results across all tests.

# Note: the "Needed" scalar, when applied to the lowest possible price at highest stock,
# is wildly inconsistent for no known reason. However, the only time this would ever 
# come up is if you artificially inflate the stock of a Needed item by selling to them,
# which no one would reasonably do, so there's no need to isolate the problem and fix it.
PRODUCES_SCALAR = 0.88
NORMAL_SCALAR = 1.10
NEEDED_SCALAR = 1.375


class ShopPricingHandler:
    def __init__(self, csv_path=CSV_PATH, data_path=DATA_PATH, state_path=STATE_PATH):
        self.df = pd.read_csv(csv_path)
        self.df.set_index("Name", inplace=True)

        with open(data_path, "r") as f:
            self.valid_ingredients = json.load(f)["valid_ingredients"]

        # Filter and retain only valid ingredients
        self.df = self.df[self.df.index.isin(self.valid_ingredients)]

        # Store order for later output sorting
        self.ingredient_order = {name: i for i, name in enumerate(self.valid_ingredients)}
        self.state_path = state_path

    def _get_current_map(self):
        """Attempt to read the current map from user_state.json.
           If any error occurs or the value is not 1, 2, or 3, default to map 1.
        """
        try:
            with open(self.state_path, "r") as f:
                state = json.load(f)
            current_map = state["user_settings"]["current_map"]
            if current_map not in {1, 2, 3}:
                current_map = 1
        except Exception:
            current_map = 1
        return current_map

    def _mean_stock(self, row, prefix):
        return (row[f"{prefix}StockMin"] + row[f"{prefix}StockMax"]) / 2

    def _lowest_price(self, row, status):
        if status == "Produces":
            return round(row["MinPrice"] * PRODUCES_SCALAR, 2)
        elif status == "Normal":
            return round(row["LowPrice"] * NORMAL_SCALAR, 2)
        elif status == "Needed":
            return round(row["LowPrice"] * NEEDED_SCALAR, 2)
        return None

    def _highest_price(self, row, status):
        if status == "Produces":
            return round(row["HighPrice"] * PRODUCES_SCALAR, 2)
        elif status == "Normal":
            return round(row["HighPrice"] * NORMAL_SCALAR, 2)
        elif status == "Needed":
            return round(row["MaxPrice"] * NEEDED_SCALAR, 2)
        return None

    def get_pricing_table(self, mode: str) -> pd.DataFrame:
        if mode not in {"cheapest_only", "buyout"}:
            raise ValueError(f"Unknown mode '{mode}'. Use 'cheapest_only' or 'buyout'.")

        # Determine which map's shop counts to use.
        current_map = self._get_current_map()
        has_col = f"NumHasMap{current_map}"
        needed_col = f"NumNeededMap{current_map}"
        producers_col = f"NumProducersMap{current_map}"

        rows = []

        for name, row in self.df.iterrows():
            entry = {"Name": name}

            # Produces calculations
            produces_mean_stock = self._mean_stock(row, "Produces")
            produces_lowest_qty = row["HighValue"]
            produces_lowest_price = self._lowest_price(row, "Produces")
            produces_highest_price = self._highest_price(row, "Produces")

            if mode == "cheapest_only":
                produces_qty = max(0, produces_mean_stock - produces_lowest_qty)
                produces_price = produces_lowest_price
            else:  # buyout
                produces_qty = produces_mean_stock
                produces_price = produces_highest_price

            entry["ProducesStockPerPickup"] = round(produces_qty, 2)
            entry["ProducesPricePerItem"] = produces_price

            # Append the map-specific "producers" count (unchanged from CSV)
            entry["NumProduces"] = row[producers_col]

            # Normal calculations
            normal_mean_stock = self._mean_stock(row, "Normal")
            normal_lowest_qty = row["HighValue"]
            normal_lowest_price = self._lowest_price(row, "Normal")
            normal_highest_price = self._highest_price(row, "Normal")

            if mode == "cheapest_only":
                normal_qty = max(0, normal_mean_stock - normal_lowest_qty)
                normal_price = normal_lowest_price
            else:  # buyout
                normal_qty = normal_mean_stock
                normal_price = normal_highest_price

            entry["NormalStockPerPickup"] = round(normal_qty, 2)
            entry["NormalPricePerItem"] = normal_price

            # Compute the number of NORMAL shops on this map using:
            # NumNormal = NumHasMapX - (NumProducersMapX + NumNeededMapX)
            entry["NumNormal"] = row[has_col] - (row[producers_col] + row[needed_col])

            rows.append(entry)

        df = pd.DataFrame(rows)

        # Sort rows based on the order defined in data.json
        df["SortOrder"] = df["Name"].map(self.ingredient_order)
        df.sort_values("SortOrder", inplace=True)
        df.drop(columns=["SortOrder"], inplace=True)

        # Reorder columns: we want NumProduces right after ProducesPricePerItem and
        # NumNormal right after NormalPricePerItem.
        desired_columns = [
            "Name",
            "ProducesStockPerPickup",
            "ProducesPricePerItem",
            "NumProduces",
            "NormalStockPerPickup",
            "NormalPricePerItem",
            "NumNormal"
        ]
        return df[desired_columns]



def main():
    handler = ShopPricingHandler()

    print("\n=== Early Game: Cheapest Only ===\n")
    df1 = handler.get_pricing_table("cheapest_only")
    print(df1.to_string(index=False))

    print("\n=== Mid/Late Game: Full Buyout ===\n")
    df2 = handler.get_pricing_table("buyout")
    print(df2.to_string(index=False))


if __name__ == "__main__":
    main()