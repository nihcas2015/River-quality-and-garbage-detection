"""
Generate all figures for the river monitoring paper.
Run:  python generate_figures.py
Output: figures/*.png  (300 DPI, publication-quality)
"""

import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── output directory ────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__), "figures")
os.makedirs(OUT, exist_ok=True)

# ── colour palette (matches paper) ──────────────────────────────────
C_TEMP    = "#EF4444"
C_PH      = "#3B82F6"
C_TURB    = "#22C55E"
C_TRASH   = "#8B5CF6"
C_FED     = "#F97316"
C_PLASTIC = "#EF4444"
C_BOTTLE  = "#F97316"
C_METAL   = "#6366F1"
C_GLASS   = "#3B82F6"
C_BRANCH  = "#22C55E"
C_TEXTILE = "#8B5CF6"
C_ALGAE   = "#06B6D4"

DPI = 300
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "figure.dpi": DPI,
})


# ════════════════════════════════════════════════════════════════════
# 1. 24-hour sensor trace  (fig:sensor-trace)
# ════════════════════════════════════════════════════════════════════
def fig_sensor_trace():
    hours = list(range(25))
    temp = [18.2, 17.8, 17.3, 16.9, 16.5, 16.8, 17.4, 18.6, 19.8,
            21.2, 22.8, 24.1, 25.3, 26.0, 26.4, 26.1, 25.4, 24.5,
            23.2, 22.0, 21.1, 20.2, 19.4, 18.8, 18.3]
    ph   = [7.32, 7.30, 7.28, 7.26, 7.25, 7.24, 7.22, 7.20, 7.18,
            7.15, 7.12, 7.08, 7.05, 7.02, 7.00, 7.03, 7.08, 7.14,
            7.20, 7.25, 7.28, 7.30, 7.32, 7.33, 7.32]
    turb = [28, 25, 22, 24, 21, 23, 26, 30, 32, 35, 33, 37, 42, 45,
            41, 38, 34, 31, 29, 27, 25, 24, 23, 26, 27]

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    ax.plot(hours, temp, color=C_TEMP, linewidth=1.8, label="Temperature (°C)")
    ax.plot(hours, ph, color=C_PH, linewidth=1.8, linestyle="--", label="pH")
    ax.plot(hours, turb, color=C_TURB, linewidth=1.8, linestyle=":", label="Turbidity (NTU)")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Value")
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 50)
    ax.set_xticks([0, 4, 8, 12, 16, 20, 24])
    ax.legend(loc="upper left", fontsize=8, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "sensor_trace.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  sensor_trace.png")


# ════════════════════════════════════════════════════════════════════
# 2. Anomaly detection by method  (fig:anomaly-bar)
# ════════════════════════════════════════════════════════════════════
def fig_anomaly_bar():
    methods = ["Threshold", "Spike", "Z-score", "EWMA Drift"]
    temp_vals = [2, 3, 4, 3]
    ph_vals   = [1, 2, 5, 3]
    turb_vals = [5, 6, 8, 5]

    x = np.arange(len(methods))
    w = 0.25
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    ax.bar(x - w, temp_vals, w, color=C_TEMP, alpha=0.8, label="Temperature")
    ax.bar(x,     ph_vals,   w, color=C_PH,   alpha=0.8, label="pH")
    ax.bar(x + w, turb_vals, w, color=C_TURB,  alpha=0.8, label="Turbidity")

    for bars, vals in [(x - w, temp_vals), (x, ph_vals), (x + w, turb_vals)]:
        for xi, v in zip(bars, vals):
            ax.text(xi, v + 0.3, str(v), ha="center", va="bottom", fontsize=7)

    ax.set_xlabel("Detection Method")
    ax.set_ylabel("Count")
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.set_ylim(0, 12)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "anomaly_bar.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  anomaly_bar.png")


# ════════════════════════════════════════════════════════════════════
# 3. EWMA spike response  (fig:ewma-spike)
# ════════════════════════════════════════════════════════════════════
def fig_ewma_spike():
    t = list(range(1, 31))
    raw = [21.3, 21.5, 21.4, 21.6, 21.8, 21.7, 22.0, 21.9, 22.1,
           22.3, 22.2, 22.5, 22.4, 22.6, 28.9, 23.0, 22.8, 22.6,
           22.5, 22.3, 22.1, 22.0, 21.8, 21.7, 21.5, 21.4, 21.3,
           21.2, 21.1, 21.0]
    ewma = [21.30, 21.36, 21.37, 21.44, 21.55, 21.60, 21.72, 21.77,
            21.87, 22.00, 22.06, 22.19, 22.26, 22.36, 24.32, 23.93,
            23.59, 23.29, 23.05, 22.83, 22.61, 22.43, 22.24, 22.08,
            21.91, 21.76, 21.62, 21.50, 21.38, 21.26]

    fig, ax = plt.subplots(figsize=(6.5, 3.1))
    ax.plot(t, raw, color=C_TEMP, marker="o", markersize=3, linewidth=0.9,
            label=r"Raw reading $x_t$")
    ax.plot(t, ewma, color=C_PH, linewidth=2.0, label=r"EWMA ($\alpha=0.3$)")
    ax.annotate("Spike", xy=(15, 28.9), xytext=(15, 31.2),
                arrowprops=dict(arrowstyle="->", color="red", lw=1.5),
                fontsize=9, color="red", ha="center")
    ax.set_xlabel(r"Reading index ($t$)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_xlim(0, 31)
    ax.set_ylim(18, 32)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "ewma_spike.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  ewma_spike.png")


# ════════════════════════════════════════════════════════════════════
# 4. YOLOv8 per-class metrics  (fig:yolo-perclass)
# ════════════════════════════════════════════════════════════════════
def fig_yolo_perclass():
    classes = ["Plastic", "Bottle", "Metal", "Glass", "Branch", "Textile", "Algae"]
    prec   = [0.82, 0.76, 0.79, 0.71, 0.65, 0.73, 0.62]
    recall = [0.78, 0.71, 0.72, 0.64, 0.58, 0.66, 0.55]
    ap50   = [0.79, 0.70, 0.73, 0.63, 0.57, 0.65, 0.53]
    colors_p = [C_PLASTIC, C_BOTTLE, C_METAL, C_GLASS, C_BRANCH, C_TEXTILE, C_ALGAE]

    x = np.arange(len(classes))
    w = 0.25
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    ax.bar(x - w, prec,   w, color=[c + "90" for c in colors_p], edgecolor=colors_p, label="Precision")
    ax.bar(x,     recall, w, color=[C_PH + "80"] * 7, label="Recall")
    ax.bar(x + w, ap50,   w, color=[C_TURB + "80"] * 7, label="AP$_{50}$")
    ax.set_xlabel("Trash Class")
    ax.set_ylabel("Score")
    ax.set_xticks(x)
    ax.set_xticklabels(classes, rotation=25, ha="right")
    ax.set_ylim(0, 1.0)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "yolo_perclass.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  yolo_perclass.png")


# ════════════════════════════════════════════════════════════════════
# 5. Latency breakdown (horizontal bar)  (fig:latency-bar)
# ════════════════════════════════════════════════════════════════════
def fig_latency_bar():
    stages = ["WebSocket", "HTTP POST", "Anomaly det.", "YOLO inference",
              "MQTT", "Sensor read"]
    values = [8, 23, 0.4, 287, 12, 620]

    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    bars = ax.barh(stages, values, color=C_PH, alpha=0.65, edgecolor=C_PH)
    for bar, v in zip(bars, values):
        ax.text(bar.get_width() + 8, bar.get_y() + bar.get_height() / 2,
                f"{v}", va="center", fontsize=8)
    ax.set_xlabel("Latency (ms)")
    ax.set_xlim(0, 720)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "latency_bar.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  latency_bar.png")


# ════════════════════════════════════════════════════════════════════
# 6. Trash class distribution (horizontal bar)  (fig:trash-pie)
# ════════════════════════════════════════════════════════════════════
def fig_trash_distribution():
    classes = ["Plastic", "Bottle", "Branch", "Metal", "Algae", "Glass", "Textile"]
    counts  = [58, 34, 27, 19, 18, 15, 12]
    colors  = [C_PLASTIC, C_BOTTLE, C_BRANCH, C_METAL, C_ALGAE, C_GLASS, C_TEXTILE]

    fig, ax = plt.subplots(figsize=(5.0, 3.5))
    bars = ax.barh(classes, counts, color=colors, alpha=0.75, edgecolor=[c for c in colors])
    for bar, v in zip(bars, counts):
        ax.text(bar.get_width() + 0.8, bar.get_y() + bar.get_height() / 2,
                str(v), va="center", fontsize=8)
    ax.set_xlabel("Detections")
    ax.set_xlim(0, 68)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "trash_distribution.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  trash_distribution.png")


# ════════════════════════════════════════════════════════════════════
# 7. WQI over seven days  (fig:wqi-week)
# ════════════════════════════════════════════════════════════════════
def fig_wqi_week():
    days = [1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75,
            3, 3.25, 3.5, 3.75, 4, 4.25, 4.5, 4.75,
            5, 5.25, 5.5, 5.75, 6, 6.25, 6.5, 6.75,
            7, 7.25, 7.5, 7.75]
    wqi  = [92, 94, 91, 93, 89, 87, 85, 88,
            72, 65, 58, 67, 78, 82, 85, 87,
            91, 93, 94, 92, 90, 88, 86, 89,
            91, 93, 92, 94]

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    ax.plot(days, wqi, color=C_TURB, linewidth=1.8, marker="s", markersize=3.5,
            label="WQI")
    ax.axhline(y=80, color="orange", linestyle="--", linewidth=0.8, alpha=0.7)
    ax.text(6.2, 77, "Moderate", fontsize=7, color="orange")
    ax.axhline(y=50, color="red", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.text(6.5, 47, "Poor", fontsize=7, color="red")
    ax.axvspan(2.8, 3.8, alpha=0.08, color="red")
    ax.text(2.85, 70, "Rain event", fontsize=7, color="darkred", rotation=90, va="center")
    ax.set_xlabel("Day")
    ax.set_ylabel("WQI (0 – 100)")
    ax.set_xlim(1, 8)
    ax.set_ylim(40, 105)
    ax.set_xticks(range(1, 8))
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "wqi_week.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  wqi_week.png")


# ════════════════════════════════════════════════════════════════════
# 8. CPU utilisation over 24 h  (fig:cpu-util)
# ════════════════════════════════════════════════════════════════════
def fig_cpu_util():
    hours = list(range(25))
    pi4 = [42, 44, 43, 41, 40, 42, 45, 48, 52, 55, 58, 53, 51,
           49, 47, 68, 54, 48, 45, 44, 43, 42, 41, 40, 42]
    pi5 = [9, 10, 9, 8, 8, 9, 10, 11, 13, 14, 15, 14, 13,
           12, 11, 19, 14, 12, 11, 10, 10, 9, 9, 9, 9]

    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    ax.plot(hours, pi4, color=C_TEMP, linewidth=1.8, label="Pi 4 (edge)")
    ax.plot(hours, pi5, color=C_PH, linewidth=1.8, linestyle="--", label="Pi 5 (central)")
    ax.set_xlabel("Time (hours)")
    ax.set_ylabel("CPU utilisation (%)")
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 100)
    ax.set_xticks([0, 4, 8, 12, 16, 20, 24])
    ax.legend(loc="upper left", fontsize=8, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "cpu_util.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  cpu_util.png")


# ════════════════════════════════════════════════════════════════════
# 9. FedAvg convergence  (fig:fedavg)
# ════════════════════════════════════════════════════════════════════
def fig_fedavg():
    rounds_local = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
    local_map    = [0.54, 0.55, 0.56, 0.565, 0.57, 0.575, 0.578,
                    0.58, 0.58, 0.58, 0.58]

    rounds_fed = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24,
                  26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50]
    fed_map    = [0.54, 0.56, 0.58, 0.60, 0.61, 0.610, 0.622, 0.632,
                  0.639, 0.644, 0.648, 0.651, 0.653, 0.654, 0.655,
                  0.656, 0.656, 0.657, 0.657, 0.657, 0.657, 0.657,
                  0.657, 0.657, 0.657, 0.657]

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    ax.plot(rounds_local, local_map, color="gray", linewidth=1.8,
            linestyle="--", label="Local only (no FedAvg)")
    ax.plot(rounds_fed, fed_map, color=C_FED, linewidth=1.8,
            marker=".", markersize=4, label="FedAvg global model")
    ax.set_xlabel("FedAvg Round")
    ax.set_ylabel(r"mAP$_{50}$")
    ax.set_xlim(0, 50)
    ax.set_ylim(0.45, 0.75)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fedavg.png"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("  fedavg.png")


# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Generating figures …")
    fig_sensor_trace()
    fig_anomaly_bar()
    fig_ewma_spike()
    fig_yolo_perclass()
    fig_latency_bar()
    fig_trash_distribution()
    fig_wqi_week()
    fig_cpu_util()
    fig_fedavg()
    print("Done — 9 figures saved to figures/")
