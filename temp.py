import re

FILENAME = "console_handler.py"

# Methods to rename → add underscore prefix
methods_to_underscore = [
    "handle_command",
    "handle_inventory_command",
    "handle_surplus_command",
    "handle_solve",
    "handle_settings_command",
    "handle_exit",
    "apply_inventory_syntax",
    "fuzzy_match_ingredient",
    "load_inventory",
    "load_surplus",
    "load_user_state",
    "save_user_state",
    "load_settings",
    "save_settings",
    "display_reports",
    "display_inventory",
    "display_surplus",
    "display_unsolved_warning",
    "get_ingredient_stat",
    "set_ingredient_stat",
    "prompt_user_for_pair",
]

with open(FILENAME, "r", encoding="utf-8") as f:
    code = f.read()

# Rename function definitions and calls
for method in methods_to_underscore:
    # Rename function definitions: def method(
    code = re.sub(rf'(\bdef\s+){method}(\s*\()', rf'\1_{method}\2', code)
    # Rename calls: self.method(...)
    code = re.sub(rf'(\bself\.){method}(\s*\()', rf'\1_{method}\2', code)

with open(FILENAME, "w", encoding="utf-8") as f:
    f.write(code)

print(f"Done: underscored {len(methods_to_underscore)} internal methods in {FILENAME}")
