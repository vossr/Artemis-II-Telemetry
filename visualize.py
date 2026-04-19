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
    t, x, y, z, vx, vy, vz = [], [], [], [], [], [], []
    with SRC.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t.append(float(row["unixtime"]))
            x.append(float(row["posx"]))
            y.append(float(row["posy"]))
            z.append(float(row["posz"]))
            vx.append(float(row["velx"]))
            vy.append(float(row["vely"]))
            vz.append(float(row["velz"]))
    return (np.array(t), np.array(x), np.array(y), np.array(z),
            np.array(vx), np.array(vy), np.array(vz))


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


def main():
    t, x, y, z, vx, vy, vz = load()
    hours = (t - t[0]) / 3600.0
    speed = np.sqrt(vx * vx + vy * vy + vz * vz)
    seg_speed = 0.5 * (speed[:-1] + speed[1:])

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
    norm = plt.Normalize(seg_speed.min(), seg_speed.max())
    lc = Line3DCollection(segs, cmap=INFERNO_TRIM, norm=norm, linewidth=1.5)
    lc.set_array(seg_speed)
    ax.add_collection3d(lc)

    ax.scatter(x[0], y[0], z[0], color="#2ecc71", s=50, label=f"start (t+0.0h)")
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
    ax.set_title(f"Artemis II trajectory, From TLI to Reentry, {len(t)} samples, {hours[-1]:.1f} h")
    leg = ax.legend(loc="upper left", facecolor="black", edgecolor="none", labelcolor="white")
    for text in leg.get_texts():
        text.set_color("white")

    cb = fig.colorbar(lc, ax=ax, shrink=0.6, pad=0.1)
    cb.set_label("velocity (m/s)", color="white")
    cb.ax.yaxis.set_tick_params(color="white", labelcolor="white")
    cb.outline.set_edgecolor("white")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
