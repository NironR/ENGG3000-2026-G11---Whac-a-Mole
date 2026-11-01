"""
ENGG3000 G11 Whac-a-Mole - sensor box enclosure (body + lid).

Run:  py -m pip install manifold3d trimesh
      py sensor_box.py
Writes sensor_box_body.stl and sensor_box_lid.stl next to this file.
Every size is in millimetres and lives in the PARAMETERS block, so a fit
problem is fixed by changing a number and re-running.

Coordinates: x = left/right (0 = centre), y = front (0 = outside of the
front wall) to back, z = up (0 = underside of the floor).

Layout, looking down with the front wall at the bottom:

    back  +--------------------------------+
          | battery |          |  ESP32   |   battery stands on end,
          | (pocket)|          | (upright)|   ESP32 stands upright, pins
          |---------+          +----------|   pointing forward
          |           breadboard          |   breadboard flat on floor
    front +===o=====o=====o=====o=========+   4 eye holes, sensors high
                                              on the inside of the wall

No glue anywhere: the sensors push into the holes from inside and the lid's
front bar pins them there; the ESP32 is held by floor ridges + a lid tine;
battery and breadboard sit in low fences. Lid lifts off, everything lifts out.
"""
from pathlib import Path
import manifold3d as m3d
import numpy as np
import trimesh

# ---------------- PARAMETERS ----------------
OUT_W, OUT_D, OUT_H = 100.0, 100.0, 80.0   # body outside (lid adds LID_T on top)
WALL = 2.4                                 # wall + floor thickness
FIT = 0.3                                  # general clearance for parts

# RCWL-1601 (measured: board 40 x 18, eye 15 dia, 10 gap between eyes)
SENSOR_W, SENSOR_H, PCB_T = 40.0, 18.0, 1.6
EYE_D = 15.0
EYE_PITCH = 25.0           # eye centre to eye centre on one board (10 gap + 15)
SENSOR_GAP = 10.0          # gap between the two boards
EYE_HOLE_D = 16.5          # 0.75 mm clearance around a 15 mm eye
PCB_TOP_BELOW_RIM = 4.0    # sensor board top sits this far below the body rim

# Breadboard (measured 84 x 55 x 9)
BB_W, BB_D = 84.0, 55.0
# Battery holder (measured 57 x 30 x 30), stood on end -> 30 x 30 footprint
BAT_W, BAT_D = 30.0, 30.0
# ESP32 (measured 26 x 50)
ESP_W, ESP_LEN = 26.0, 50.0
ESP_BACK_CLEAR = 7.0       # room behind the board for the module + antenna plug

FENCE_T, FENCE_H = 1.6, 6.0
LID_T, LIP_T, LIP_DEPTH, LID_FIT = 2.4, 1.6, 6.0, 0.25
# --------------------------------------------

IX0, IX1 = -OUT_W / 2 + WALL, OUT_W / 2 - WALL     # interior x range
IY0, IY1 = WALL, OUT_D - WALL                      # interior y range
IZ0 = WALL                                         # interior floor height


def box(x0, x1, y0, y1, z0, z1):
    return m3d.Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def eye_centres_x():
    s = (SENSOR_W + SENSOR_GAP) / 2                # board centres at +-s
    return [c + e for c in (-s, s) for e in (-EYE_PITCH / 2, EYE_PITCH / 2)]


PCB_TOP_Z = OUT_H - PCB_TOP_BELOW_RIM
EYE_Z = PCB_TOP_Z - SENSOR_H / 2                   # eyes assumed centred on board

# ESP32 bay (back-right), board standing upright, components facing back wall
ESP_CX = IX1 - FENCE_T - 3.0 - (ESP_W / 2 + 1.0)
ESP_PCB_BACK_Y = IY1 - ESP_BACK_CLEAR
ESP_PCB_FRONT_Y = ESP_PCB_BACK_Y - PCB_T


def body():
    b = box(-OUT_W / 2, OUT_W / 2, 0, OUT_D, 0, OUT_H)
    b = b - box(IX0, IX1, IY0, IY1, IZ0, OUT_H + 1)

    # four eye holes through the front wall
    for x in eye_centres_x():
        cyl = m3d.Manifold.cylinder(WALL + 2, EYE_HOLE_D / 2, EYE_HOLE_D / 2, 96)
        cyl = cyl.rotate([-90, 0, 0]).translate([x, -1, EYE_Z])
        b = b - cyl

    # breadboard fence (sides + back; front is the front wall)
    bx, by1 = BB_W / 2 + FIT, IY0 + BB_D + FIT
    for x0, x1 in ((-bx - FENCE_T, -bx), (bx, bx + FENCE_T)):
        b = b + box(x0, x1, IY0, by1, IZ0, IZ0 + 4)
    b = b + box(-bx - FENCE_T, bx + FENCE_T, by1, by1 + FENCE_T, IZ0, IZ0 + 4)

    # battery pocket, back-left corner
    bat_x1 = IX0 + BAT_W + 2 * FIT
    bat_y0 = IY1 - BAT_D - 2 * FIT
    b = b + box(bat_x1, bat_x1 + FENCE_T, bat_y0 - FENCE_T, IY1, IZ0, IZ0 + FENCE_H + 4)
    b = b + box(IX0, bat_x1 + FENCE_T, bat_y0 - FENCE_T, bat_y0, IZ0, IZ0 + FENCE_H + 4)

    # ESP32 bay: side guides + floor ridges that stop the bottom edge sliding
    gx = ESP_W / 2 + 1.0
    for x0, x1 in ((ESP_CX - gx - FENCE_T, ESP_CX - gx), (ESP_CX + gx, ESP_CX + gx + FENCE_T)):
        b = b + box(x0, x1, ESP_PCB_FRONT_Y - 4, IY1, IZ0, IZ0 + 20)
    ridge_h = 1.5   # low enough to pass under the bottom pin's connector
    b = b + box(ESP_CX - gx, ESP_CX + gx, ESP_PCB_FRONT_Y - FIT - 1.2, ESP_PCB_FRONT_Y - FIT, IZ0, IZ0 + ridge_h)
    for x0, x1 in ((ESP_CX - gx, ESP_CX - gx + 4), (ESP_CX + gx - 4, ESP_CX + gx)):  # corners only: miss the module/USB
        b = b + box(x0, x1, ESP_PCB_BACK_Y + FIT, ESP_PCB_BACK_Y + FIT + 1.2, IZ0, IZ0 + ridge_h)

    # antenna channel on the left wall, between breadboard and battery pocket
    ay = (by1 + FENCE_T + bat_y0 - FENCE_T) / 2
    gap = 2.0
    for y0 in (ay - gap / 2 - 1.2, ay + gap / 2):
        b = b + box(IX0, IX0 + 3, y0, y0 + 1.2, IZ0, OUT_H - LIP_DEPTH - 2)
    return b


def lid():
    # modelled the right way up (plate on top); print it upside down
    top = OUT_H
    l = box(-OUT_W / 2, OUT_W / 2, 0, OUT_D, top, top + LID_T)
    lo = top - LIP_DEPTH
    lx0, lx1 = IX0 + LID_FIT, IX1 - LID_FIT
    ly1 = IY1 - LID_FIT
    l = l + box(lx0, lx0 + LIP_T, IY0 + LID_FIT, ly1, lo, top)        # left lip
    l = l + box(lx1 - LIP_T, lx1, IY0 + LID_FIT, ly1, lo, top)        # right lip
    l = l + box(lx0, lx1, ly1 - LIP_T, ly1, lo, top)                  # back lip
    # front bar: sits just behind the sensor boards and pins them to the wall
    fy0 = IY0 + PCB_T + 0.4
    l = l + box(lx0, lx1, fy0, fy0 + 2.0, PCB_TOP_Z - 3.0, top)
    # ESP32 tine: presses on the pin side of the upright board, near its top
    l = l + box(ESP_CX - 4, ESP_CX + 4, ESP_PCB_FRONT_Y - 0.4 - 2.0, ESP_PCB_FRONT_Y - 0.4,
                IZ0 + ESP_LEN - 7.0, top)
    return l


def to_trimesh(m):
    mesh = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3],
                           faces=np.asarray(mesh.tri_verts), process=True)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    b, l = to_trimesh(body()), to_trimesh(lid())
    # lid flipped so its flat top is on the print bed
    l_print = l.copy()
    l_print.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    l_print.apply_translation(-l_print.bounds[0] + [0, 0, 0])
    b.export(here / "sensor_box_body.stl")
    l_print.export(here / "sensor_box_lid.stl")
    for name, mesh in (("body", b), ("lid", l_print)):
        print(f"{name}: watertight={mesh.is_watertight} size={np.round(mesh.extents, 1)} mm "
              f"volume={mesh.volume / 1000:.1f} cm3")
    print("eye centres x:", eye_centres_x(), " eye centre height:", EYE_Z)
