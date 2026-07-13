"""
Render the Orion flight path coloured by how fast it is rotating.

At every time step the angular velocity (rotation rate) is derived from the
change between consecutive attitude quaternions:

    theta = 2 * arccos(|<q_i, q_i+1>|)     # relative rotation angle
    omega = theta / dt                      # rad/s

The per-step intensity is normalised to its maximum and mapped with the same
INFERNO_TRIM colormap used for speed in visualize.py, so bright segments are
where the spacecraft is slewing hardest and dark segments are near-inertial.

Rotation is bursty (mostly near-inertial with brief slews), so raw max
normalisation leaves almost the whole path dark. --smooth N widens each burst
with a Gaussian window of N samples so it is easier to see where the changes
happen; the result is re-normalised to its own max, keeping the peak at 1.0.
"""

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.mplot3d.art3d import Line3DCollection

SRC = Path(__file__).parent / "telemetry_recording.csv"
EARTH_RADIUS_M = 6_378_137.0
INFERNO_TRIM = LinearSegmentedColormap.from_list(
    "inferno_trim", plt.get_cmap("inferno")(np.linspace(0.2, 1.0, 256))
)


def load():
    t, x, y, z = [], [], [], []
    q = []
    with SRC.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t.append(float(row["unixtime"]))
            x.append(float(row["posx"]))
            y.append(float(row["posy"]))
            z.append(float(row["posz"]))
            q.append([float(row["q1"]), float(row["q2"]),
                      float(row["q3"]), float(row["q4"])])
    return np.array(t), np.array(x), np.array(y), np.array(z), np.array(q)


def angular_velocity(t, q):
    """Per-step rotation rate (rad/s) between consecutive quaternions."""
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    dot = np.sum(q[:-1] * q[1:], axis=1)            # 4-vector dot product
    theta = 2.0 * np.arccos(np.clip(np.abs(dot), 0.0, 1.0))
    dt = np.diff(t)
    omega = np.zeros_like(theta)
    good = dt > 0
    omega[good] = theta[good] / dt[good]
    return omega


def smooth(a, window):
    """Gaussian smoothing over `window` samples, edge-padded. window<=1 is a no-op."""
    window = int(window)
    if window <= 1:
        return a
    if window % 2 == 0:
        window += 1
    x = np.arange(window) - (window - 1) / 2.0
    kernel = np.exp(-0.5 * (x / (window / 4.0)) ** 2)
    kernel /= kernel.sum()
    pad = window // 2
    padded = np.pad(a, pad, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def plot_earth(ax):
    u = np.linspace(0, 2 * np.pi, 90)
    v = np.linspace(0, np.pi, 45)
    ex = EARTH_RADIUS_M * np.outer(np.cos(u), np.sin(v))
    ey = EARTH_RADIUS_M * np.outer(np.sin(u), np.sin(v))
    ez = EARTH_RADIUS_M * np.outer(np.ones_like(u), np.cos(v))
    ax.plot_surface(ex, ey, ez, color="#1f6feb", alpha=0.9, linewidth=0,
                    antialiased=False, shade=True, zorder=0)


def trajectory_segments(x, y, z):
    pts = np.column_stack([x, y, z]).reshape(-1, 1, 3)
    return np.concatenate([pts[:-1], pts[1:]], axis=1)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--smooth", type=int, default=1, metavar="N",
                   help="Gaussian smoothing window in samples to widen rotation "
                        "bursts for visibility; peak intensity is preserved. 1 = off.")
    p.add_argument("--clamp-normalize-max", type=float, default=1.0, metavar="F",
                   help="re-normalise the [0,1] intensity by dividing by F and "
                        "clamping back to 1.0; F=0.8 saturates the top 20%% and "
                        "brightens everything below it. 1.0 = off.")
    return p.parse_args()


def main():
    args = parse_args()
    t, x, y, z, q = load()
    hours = (t - t[0]) / 3600.0

    omega = angular_velocity(t, q)                  # rad/s, one per segment
    peak = omega.max()                              # true instantaneous peak (deg/s in title)
    intensity = smooth(omega, args.smooth)          # widen bursts if requested
    imax = intensity.max()
    intensity = intensity / imax if imax > 0 else intensity  # re-normalise, keeps peak at 1.0
    if args.clamp_normalize_max != 1.0:                       # brighten by dividing again, then clamp
        intensity = np.clip(intensity / args.clamp_normalize_max, 0.0, 1.0)

    fig = plt.figure(figsize=(11, 9), facecolor="black")
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("black")
    for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
        pane.set_pane_color((0, 0, 0, 1))
        pane.line.set_color((1, 1, 1, 0.3))
        pane.label.set_color("white")
        for tick in pane.get_major_ticks():
            tick.label1.set_color("white")
        pane._axinfo["grid"]["color"] = (1, 1, 1, 0.15)
    ax.tick_params(colors="white")
    ax.title.set_color("white")

    plot_earth(ax)

    segs = trajectory_segments(x, y, z)
    norm = plt.Normalize(0.0, 1.0)
    lc = Line3DCollection(segs, cmap=INFERNO_TRIM, norm=norm, linewidth=1.5)
    lc.set_array(intensity)
    ax.add_collection3d(lc)

    ax.scatter(x[0], y[0], z[0], color="#2ecc71", s=50, label="start (t+0.0h)")
    ax.scatter(x[-1], y[-1], z[-1], color="#e74c3c", s=50, label=f"end (t+{hours[-1]:.1f}h)")

    cx, cy, cz = 0.5 * (x.max() + x.min()), 0.5 * (y.max() + y.min()), 0.5 * (z.max() + z.min())
    half = 0.55 * max(x.max() - x.min(), y.max() - y.min(), z.max() - z.min(), 2 * EARTH_RADIUS_M)
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)
    ax.set_zlim(cz - half, cz + half)
    ax.set_box_aspect((1, 1, 1))

    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    smooth_txt = f", smooth {args.smooth}" if args.smooth > 1 else ""
    ax.set_title(f"Artemis II rotation rate, normalized to peak "
                 f"{np.degrees(peak):.2f} deg/s{smooth_txt}, {hours[-1]:.1f} h")
    leg = ax.legend(loc="upper left", facecolor="black", edgecolor="none", labelcolor="white")
    for text in leg.get_texts():
        text.set_color("white")

    cb = fig.colorbar(lc, ax=ax, shrink=0.6, pad=0.1)
    cb.set_label("rotation intensity (normalized to max)", color="white")
    cb.ax.yaxis.set_tick_params(color="white", labelcolor="white")
    cb.outline.set_edgecolor("white")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
