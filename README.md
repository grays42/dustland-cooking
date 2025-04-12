# Dustland Cooking Optimizer

A utility for optimizing cooking in **Dustland Delivery**, a game where food crafted from ingredients affects crew survival and economy. This tool:

- Evaluate the best food combinations for **reducing hunger and stress**
- Find the most **profitable cooked goods** to sell at market stalls
- Manage your **ingredient inventory** interactively
- Incrementally **solve unknown ingredient stats** through guided recipe experiments

The current version is function-complete and usable, but does not yet integrate ingredient rarity / pickup quantity economics or profit-per-item mechanics.

---

## Installation

1. Install Python (add to PATH)
2. Install pandas dataframes with this console command:
```cmd
pip install pandas
```
3. Download project files
4. Open a console in the project directory and run:
```cmd
python main.py
```

---

## How It Works

In *Dustland Delivery*, cooking requires 1–5 ingredients that form a recipe. Contrary to popular understanding of game mechanics, the **hunger**, **stress**, and **sell value** of the resulting cooked food item depend entirely on the *ingredients used*, not the recipe itself. The recipe only determines whether the result is edible, the values are a sum of some base values plus the individual ingredients' contributions. For example, **Salt** will contribute 6 to Hunger, 20 to Stress, and 63 to Sell Value regardless of what recipe it is added to.

This script evaluates every recipe-valid "cookjob" (combination of 1-5 ingredients) based on the ingredients you currently have, and recommends the best options for either:

- **Road Use** – recipes with the highest combined hunger + stress relief
- **Sale** – recipes with the highest sell value for markets

It also provides an interactive command-line interface where you can:

- Add/remove ingredients using the `inv` command
- Clear your inventory with `clear`
- Solve unknown ingredient stats with guided isolation recipes using `solve` -- currently I have not catalogued items that are in the DLC like Bats and Millipedes, but this function gives you a mechanism to do that until I get to it

---

## Sample Output

```
    ====== Best Road Food (Hunger + Stress) ======
                      Recipe                             Ingredients  Hunger  Stress  Sell
     Pineapple Meat Stir Fry Spices, Flour, Sugar, Canned Fruit, Ham     195     137   509
     Pineapple Meat Stir Fry   Flour, Sugar, Salt, Canned Fruit, Ham     201     121   464
           Cream of Ham Soup    Water, Vegetables, Spices, Milk, Ham     201     112   436
Seafood with Fried Mushrooms  Vegetables, Spices, Ham, Prawn, Agaric     211      98   399
Seafood with Fried Mushrooms    Vegetables, Spices, Ham, Fish, Morel     211      98   399
Seafood with Fried Mushrooms    Vegetables, Spices, Ham, Crab, Morel     211      98   399
Seafood with Fried Mushrooms   Vegetables, Spices, Ham, Fish, Agaric     211      98   399
Seafood with Fried Mushrooms   Vegetables, Spices, Ham, Prawn, Morel     211      98   399
Seafood with Fried Mushrooms   Vegetables, Spices, Ham, Crab, Agaric     211      98   399
           Cream of Ham Soup      Water, Vegetables, Milk, Salt, Ham     207      96   391

    ====== Best Sale Food (Sell Value Only) ======
                 Recipe                                     Ingredients  Hunger  Stress  Sell
Pineapple Meat Stir Fry         Spices, Flour, Sugar, Canned Fruit, Ham     195     137   509
Pineapple Meat Stir Fry           Flour, Sugar, Salt, Canned Fruit, Ham     201     121   464
      Cream of Ham Soup            Water, Vegetables, Spices, Milk, Ham     201     112   436
Pineapple Meat Stir Fry                Fruit, Spices, Flour, Sugar, Ham     150     120   436
   Ketchup Braised Meat           Vegetables, Spices, Flour, Sugar, Ham     150     120   435
      Cream of Ham Soup                   Vegetables, Spices, Milk, Ham     195     107   418
     Assorted Dumplings           Vegetables, Spices, Flour, Ham, Morel     181     105   405
     Assorted Dumplings          Vegetables, Spices, Flour, Ham, Agaric     181     105   405
     Assorted Dumplings Vegetables, Spices, Flour, Ham, Button Mushroom     170     105   400
     Assorted Dumplings Vegetables, Spices, Flour, Ham, Oyster Mushroom     170     105   400

    ====== Current Inventory ======
Water, Rations, Liquor, Coffee, Fruit, Vegetables, Spices, Medicinal Herbs, Honey, Milk, Flour, Sugar, Salt, Dried Vegetables, Canned Fruit, Beer, Tea, Fruit Wine, Seasoning, Cheese, Ham, Crab, Prawn, Fish, Venison, Agaric, Morel, Scallop, Shrimp, Squab, Pheasant, Button Mushroom, Oyster Mushroom, Salt Pork, Quail, Chicken, Bread

    ====== UNSOLVED INGREDIENT WARNING ======

You have unsolved ingredients in your inventory.
Use 'solve [ingredient]' to concretely derive ingredient stats.
Unsolved ingredients: Cheese, Salt Pork, Quail, Chicken, Bread
```

## Sample Output of the "Solve" interface

This interface allows you to solve a novel ingredient (such as the DLC agreements if I haven't done them by the time you use this).


Be sure to also edit data.json to define which items go into which categories, for a lot of the DLC stuff it wasn't entirely clear which categories everything went into, you'll need to do some trial and error.

```
    ====== UNSOLVED INGREDIENT WARNING ======

You have unsolved ingredients in your inventory.
Use 'solve [ingredient]' to concretely derive ingredient stats.
Unsolved ingredients: Chicken

    ====== Recipe Console ======
- 'inv ingredient1, ingredient2, -ingredient3' to modify inventory
- 'clear' to empty the inventory, 'exit' to quit.

> solve chicken
Solving for: Chicken

---
- Clear your inventory of cooked food and zero your food need at the restaraunt.
- Craft a NORMAL version of the cooked food. Drop any advanced/legendary.
- Read hunger, stress from the description.
- Sell at the market stall to get the sell_value. (Make sure it's ONLY the normal item that sold)
- Enter the hunger, stress, and sell values comma-delimited (e.g. '80, 32, 120').

Cook "Curry Sandwich" with ingredients: Vegetables, Spices, Bread, Cheese
hunger, stress, sell_value> 165, 107, 403

Cook "Chicken Sandwich" with ingredients: Vegetables, Spices, Bread, Cheese, Chicken
hunger, stress, sell_value> 270, 119, 492

New ingredient entry: Chicken = {'hunger': 105, 'stress': 12, 'sell_value': 89}
```

You may also want to slot items into proper "inventory order" in data.json. **IMPORTANT: DELETE THE CACHE DIRECTORY IF YOU MODIFY DATA.JSON.** The code depends on the *ordering* of the valid_ingredients, and all the cache indexes will be screwed up if you change the order.



---

## Roadmap

Planned features for future builds include:

- Ingredient value scaling based on pickup availability - currently I can report the highest value recipes, but a site might have 100 vegetables and only 10 liquor, so in that case vegetable gives me an overall better option. 
- Profit predictions based on selling conditions