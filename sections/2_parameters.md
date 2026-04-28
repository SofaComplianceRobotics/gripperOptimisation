:::: collapse Parameter Configuration

### Parameters

Edit values in `lab_config.jsonc` and save. Click **Generate** in the next section to rebuild the mesh.

#open-button("assets/labs/lab_shapeOPT/config/lab_config.jsonc")

---

#### Ring

| Parameter | Default | Description |
|---|---|---|
| `cylinder_radius` | 26.5 mm | Outer radius of the ring base |
| `cylinder_height` | 4.0 mm | Axial thickness of the ring |
| `cylinder_hole_thickness` | 3.0 mm | Wall thickness of the ring opening |

---

#### Leg attachment

| Parameter | Default | Description |
|---|---|---|
| `leg_attachement_tilt_angle` | −15° | Inward (negative) or outward (positive) lean of the legs |

---

#### Pincer cross-section

The pincer is a profile swept along a Bézier path. These parameters control the shape of that profile.

| Parameter | Default | Description |
|---|---|---|
| `pincer_profile_width` | 5.0 mm | Width of the cross-section |
| `pincer_profile_height` | 10.0 mm | Height of the cross-section |
| `pincer_path_scale` | 0.4 | Uniform scale applied to the sweep path |
| `pincer_tilt_y_deg` | 90° | Roll of the profile around the path tangent |
| `pincer_round_ends` | true | Round off the pincer tip |

---

#### Pincer path (Bézier spline)

The pincer shape follows a cubic Bézier curve with two anchor points. All lengths are in mm, all angles in degrees. Handles are expressed in polar coordinates so they stay intuitive when the path scale changes.

| Parameter | Default | Description |
|---|---|---|
| `p0_hout_dist` | 0.0 mm | Length of the **out-handle** from the first anchor (origin) |
| `p0_hout_angle_deg` | 0° | Angle of the out-handle from the first anchor |
| `p1_dist` | 80.0 mm | Distance of the **tip anchor** from the origin |
| `p1_angle_deg` | −40° | Angle of the tip anchor from the origin |
| `p1_hin_dist` | 0.0 mm | Length of the **in-handle** relative to the tip anchor |
| `p1_hin_angle_deg` | 0° | Angle of the in-handle relative to the tip anchor |

---

#### Mesh quality

These parameters control triangle density. Lower values produce finer meshes but increase generation time.

| Parameter | Default | Description |
|---|---|---|
| `mesh_size_max` | 9 mm | Maximum triangle edge length (simulation mesh) |
| `mesh_size_min` | 6 mm | Minimum triangle edge length (simulation mesh) |
| `mesh_collision_size` | 90.0 mm | Edge length of the coarse collision mesh |
| `mesh_angle_smooth` | 20° | Normal smoothing angle threshold |
| `mesh_size_from_curvature` | 12 | Refinement samples per curve segment |

#icon("info-circle") The fine mesh for 3D printing always uses 2.0 mm / 0.8 mm and ignores the `mesh_size_max` / `mesh_size_min` values above.

::::
