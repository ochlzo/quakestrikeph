import pandas as pd
import matplotlib.pyplot as plt

b0 = pd.read_csv("nn_log_eta_b0_only.csv")["nn_log_eta_b0"].dropna()

# fig, ax = plt.subplots(figsize=(10, 5))
# ax.hist(b0, bins=120, edgecolor="black", alpha=0.7)
# ax.set_xlabel("log10(eta) with b=0")
# ax.set_ylabel("count")
# ax.set_title("b=0 nearest-neighbor proximity (Step 1 diagnostic)")
# plt.show()

# fig, ax = plt.subplots(figsize=(10, 5))
# ax.hist(b0, bins=120, edgecolor="black", alpha=0.7)
# ax.set_yscale("log")
# ax.set_xlabel("log10(eta) with b=0")
# ax.set_ylabel("count (log scale)")
# ax.set_title("b=0 nearest-neighbor proximity (Step 1 diagnostic, log-y)")
# plt.axvline(-1, color='red', linestyle='--', alpha=0.5, label='η₀ = -1')
# plt.axvline(-2, color='orange', linestyle='--', alpha=0.5, label='η₀ = -2')
# plt.legend()
# plt.show()

fig, ax = plt.subplots(figsize=(10, 5))
ax.hist(b0, bins=120, edgecolor="black", alpha=0.7)

ax.set_yscale("log")
ax.set_xlabel("log10(eta) with b=0")
ax.set_ylabel("count (log scale)")
ax.set_title("b=0 nearest-neighbor proximity (Step 1 diagnostic, log-y)")

plt.axvline(0.0, color="red", linestyle="--", alpha=0.6, label="eta0 = 0.0")
plt.axvline(0.5, color="orange", linestyle="--", alpha=0.8, label="eta0 = 0.5")
plt.axvline(0.8, color="green", linestyle="--", alpha=0.6, label="eta0 = 0.8")

plt.legend()
plt.show()