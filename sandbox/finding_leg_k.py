import numpy as np
import matplotlib.pyplot as plt

# === CONSTANTS ===
K_ADV = 0.000261441631347055  # Advanced still uses exponential curve

# Linear fit for Legendary
LEG_SLOPE = 0.011024217514
LEG_INTERCEPT = -0.102421751380

# Colors
COLOR_NORM = "#D3D3D3"   # Light grey
COLOR_ADV = "#4af1ff"    # Updated blue
COLOR_LEG = "#ff4adf"    # Updated pink
COLOR_ADV_OBS = "#1E90FF"  # Blue for scatter
COLOR_LEG_OBS = "#FF1493"  # Deep pink for scatter

# === OBSERVED DATA (skills 10 to 51) ===
observed_data = {
    10: (0, 0),
    11: (0, 0.215671807),
    12: (0, 0.2400234283),
    13: (0, 0.2575763141),
    14: (0, 0.2798410458),
    15: (0, 0.3045607163),
    16: (0, 0.3234694595),
    17: (0, 0.3351558229),
    18: (0, 0.3627399375),
    19: (0, 0.382231405),
    20: (0, 0.4031770577),
    21: (0.1213929984, 0.3661564377),
    22: (0.1350641048, 0.3801896509),
    23: (0.144984326, 0.396337988),
    24: (0.1549669776, 0.4046435623),
    25: (0.1674750357, 0.420042796),
    26: (0.177002539, 0.4289937741),
    27: (0.1919991556, 0.437548378),
    28: (0.1995541468, 0.450067923),
    29: (0.2128221157, 0.4541571161),
    30: (0.2239441655, 0.4699644178),
    31: (0.2347034177, 0.4726617958),
    32: (0.251636137, 0.4753627203),
    33: (0.2562310658, 0.4930459928),
    34: (0.2690020726, 0.4971288777),
    35: (0.2755067568, 0.5078378378),
    36: (0.2911898717, 0.508330145),
    37: (0.2988141484, 0.5195938118),
    38: (0.3080261033, 0.526742465),
    39: (0.3223107437, 0.5296509884),
    40: (0.3346111537, 0.5323177439),
    41: (0.3427780926, 0.5386512884),
    42: (0.3555451848, 0.5407180239),
    43: (0.3675455849, 0.5442848095),
    44: (0.374379146, 0.5505850195),
    45: (0.3955798527, 0.5458181939),
    46: (0.3955465182, 0.5573852462),
    47: (0.4153471782, 0.5502183406),
    48: (0.419680656, 0.5577852595),
    49: (0.4321144038, 0.5555851862),
    50: (0.4442140468, 0.5557859532),
    51: (0.4567485583, 0.5432514417),
}

# === MODEL FUNCTIONS ===

def pct_leg(skill):
    if skill < 21:
        return 0.0
    return max(0.0, min(1.0, LEG_SLOPE * skill + LEG_INTERCEPT))

def pct_adv(skill):
    if skill <= 10:
        return 0.0
    base_adv = (1 - np.exp(-K_ADV * skill)) / (1 - np.exp(-50 * K_ADV))
    if skill <= 20:
        return base_adv
    else:
        leg = pct_leg(skill)
        return (1 - leg) * base_adv

def pct_norm(skill):
    leg = pct_leg(skill)
    adv = pct_adv(skill)
    return max(0.0, 1.0 - leg - adv)

# === GENERATE DATA FOR PLOTTING ===

skills = np.arange(0, 101)
leg_vals = np.array([pct_leg(s) for s in skills])
adv_vals = np.array([pct_adv(s) for s in skills])
norm_vals = np.array([pct_norm(s) for s in skills])

# === PLOT STACKED BAR CHART ===

fig, ax = plt.subplots(figsize=(14, 6))
bar_width = 1.0

# Draw in order: legendary bottom, advanced, then normal
ax.bar(skills, leg_vals, color=COLOR_LEG, width=bar_width, label='Legendary (model)')
ax.bar(skills, adv_vals, bottom=leg_vals, color=COLOR_ADV, width=bar_width, label='Advanced (model)')
ax.bar(skills, norm_vals, bottom=leg_vals + adv_vals, color=COLOR_NORM, width=bar_width, label='Normal')

# === OVERLAY OBSERVED DATA ===

obs_skills = list(observed_data.keys())
obs_leg = [observed_data[s][0] for s in obs_skills]
obs_adv = [observed_data[s][1] for s in obs_skills]
obs_adv_adjusted = [observed_data[s][0] + observed_data[s][1] for s in obs_skills]

# Scatter points for observed values
ax.scatter(obs_skills, obs_leg, color=COLOR_LEG_OBS, edgecolors='black', zorder=5, label='Legendary (observed)')
ax.scatter(obs_skills, obs_adv_adjusted, color=COLOR_ADV_OBS, edgecolors='black', zorder=5, label='Advanced (observed)')

# === FINAL TOUCHES ===

ax.set_title("Cookjob Quality Distribution by Skill Level")
ax.set_xlabel("Skill Level")
ax.set_ylabel("Probability")
ax.set_xlim(0, 100)
ax.set_ylim(0, 1)
ax.grid(True, linestyle='--', alpha=0.5)
ax.legend()
plt.tight_layout()
plt.show()
