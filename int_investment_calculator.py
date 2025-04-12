# Hey, you found a bonus script to help you figure out whether investing in intellect early pays off.
# Spoiler: it doesn't. 2% per point of intellect is garbage. Only take intellect if you need the stats.

STARTING_INTELLECT = 10

NUM_EARLY_LEVELS_TO_PUT_POINTS_INTO_INTELLECT = 2

LEVEL_CAP_TO_CONSIDER = 100

def get_intellect_xp_multiplier(intellect):
    return 1 + 0.02 * intellect

def get_xp_to_next_level(level):
    return 1000 + 250 * level


def compute_final_intellect(starting_int, early_points):
    int_value = starting_int
    for _ in range(early_points):
        if int_value < 10:
            int_value += 4
        elif int_value < 13:
            int_value += 3
        elif int_value < 16:
            int_value += 3
        elif int_value < 18:
            int_value += 2
        elif int_value < 19:
            int_value += 1
        else:
            int_value += 1
    return int_value

def simulate_builds(pre_int, early_int_points, level_cap):
    final_int = compute_final_intellect(pre_int, early_int_points)
    base_multiplier = get_intellect_xp_multiplier(pre_int)
    boosted_multiplier = get_intellect_xp_multiplier(final_int)

    print(f"\n--- Dual Build Simulation ---")
    print(f"Pre-leveled Intellect: {pre_int}")
    print(f"Early Trait Points in Intellect: {early_int_points}")
    print(f"Final Intellect: {final_int}")
    print(f"Level Cap: {level_cap}")
    print(f"Base XP Multiplier: {base_multiplier:.2f}")
    print(f"Boosted XP Multiplier: {boosted_multiplier:.2f}\n")

    print(f"{'Level':>5} | {'Base XP':>8} | {'Non-Inv XP':>12} | {'Inv XP':>12} | {'Δ XP (Non - Inv)':>17}")
    print("-" * 65)

    sunk_investment_xp = sum(get_xp_to_next_level(i) for i in range(early_int_points))

    cumulative_noninv = 0
    cumulative_inv = sunk_investment_xp
    for level in range(level_cap):
        base_xp = get_xp_to_next_level(level)

        # Non-Investment build
        xp_noninv = base_xp / base_multiplier
        cumulative_noninv += xp_noninv

        # Investment build
        # Add 250 XP per early Int point to all levels after early investment
        penalty = early_int_points * 250 if level >= early_int_points else 0
        xp_inv = (base_xp + penalty) / boosted_multiplier
        cumulative_inv += xp_inv

        # Calculate sunk XP cost of early investment levels (0 to N-1)
        delta = cumulative_noninv - cumulative_inv

        print(f"{level:5} | {base_xp:8} | {cumulative_noninv:12.1f} | {cumulative_inv:12.1f} | {delta:17.1f}")


# ---- INPUT SECTION ----
if __name__ == "__main__":

    print("Dustland Intellect Investment Simulator")
    simulate_builds(STARTING_INTELLECT, NUM_EARLY_LEVELS_TO_PUT_POINTS_INTO_INTELLECT, LEVEL_CAP_TO_CONSIDER)
