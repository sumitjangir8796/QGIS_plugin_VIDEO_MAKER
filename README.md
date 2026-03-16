# Corridor Video Maker – QGIS Plugin

A QGIS 3.x plugin that generates a fly-through **MP4 video** along a polyline centerline (corridor mapping). The map canvas **pans and rotates automatically** at every frame so the travel direction always points straight up — giving the viewer a clean forward-facing corridor perspective.

---

## Features

| Feature | Detail |
|---|---|
| Centerline input | Any line / polyline vector layer |
| Start point | Click on the map to pick the nearest endpoint (green = first vertex, red = last) |
| Auto-rotation | Bearing is computed at each frame; map rotates so travel direction faces up |
| Configurable buffer | Controls how much corridor is visible on each side |
| Speed & FPS | Independent control of travel speed (m/s) and video frame rate |
| Output | MP4 (H.264 via OpenCV) |
| Non-destructive | Uses off-screen rendering — the live QGIS canvas is never touched |

---

## Requirements

- **QGIS 3.20+** (tested with QGIS 3.40.5)
- **Python packages**: `opencv-python`, `numpy`

### Install Python dependencies (once)

Run the included batch file **as Administrator** (or from a normal Command Prompt — admin is not required if QGIS was installed for the current user):

```bat
install_deps.bat
```

This uses the QGIS bundled Python at  
`C:\Program Files\QGIS 3.40.5\bin\python3.exe`

---

## Installation

### Option A — Batch script (easiest)

```bat
install_plugin.bat
```

This copies `corridor_video_maker\` to  
`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`

Then restart QGIS and enable the plugin in **Plugins → Manage and Install Plugins**.

### Option B — Manual copy

Copy the `corridor_video_maker` folder to your QGIS plugins directory:

```
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\corridor_video_maker\
```

### Option C — QGIS "Install from ZIP"

Zip the `corridor_video_maker` folder and use  
**Plugins → Manage and Install Plugins → Install from ZIP**.

---

## Usage

1. Open QGIS and load your **centerline layer** (a line / polyline).  
   Make sure the layer CRS is a **projected CRS** (metres) for accurate distances.

2. Launch the plugin via **Vector → Corridor Video Maker → Generate Corridor Video …**  
   or the toolbar button.

3. **Select the centerline layer** in the dropdown.

4. Click **"Pick Start Point from Map"** and then **click on the map** near the vertex you want to start from.  
   - Green dot = first vertex  
   - Red dot = last vertex  
   
   The plugin automatically selects the nearest endpoint.

5. Configure settings:

   | Parameter | Description | Default |
   |---|---|---|
   | Travel speed (m/s) | How fast the virtual camera moves along the line | 10 m/s |
   | FPS | Frames per second in the output video | 25 |
   | Corridor buffer (m) | Half-width of the view on each side | 100 m |
   | Video width/height | Output resolution in pixels | 1920 × 1080 |

6. Choose an **output .mp4 file** path.

7. Click **Generate Video** and wait.  
   A progress bar shows the rendering progress (this can take a few minutes for long corridors at high resolution).

8. When done, the video opens in a confirmation dialog showing the save path.

---

## How it works

```
For each frame:
  distance_per_frame = speed_m_s / fps
  point = line.interpolate(distance)
  bearing = look_ahead_bearing(line, distance)
  extent = rectangle(center=point, half_width=buffer)
  map_rotation = -bearing          ← makes travel direction face UP
  frame = off_screen_render(extent, rotation)
  video_writer.write(frame)
```

The rotation trick: QGIS `QgsMapSettings.setRotation(θ)` rotates the map clockwise by θ degrees. Setting `θ = -bearing` effectively "un-rotates" the map so the travel bearing always points to the top of the frame.

---

## File structure

```
corridor_video_maker/           ← QGIS plugin folder
├── __init__.py
├── metadata.txt
├── corridor_video_maker.py     ← plugin class (menu / toolbar)
├── corridor_video_maker_dialog.py  ← main UI dialog
├── map_tools.py                ← endpoint picker map tool
├── video_exporter.py           ← off-screen renderer + OpenCV writer
├── utils.py                    ← geometry interpolation & bearing
└── icon.png                    ← 32×32 toolbar icon

install_deps.bat                ← installs opencv-python into QGIS Python
install_plugin.bat              ← copies plugin to QGIS plugins folder
README.md
```

---

## Tips

- Use a **projected CRS** (e.g. UTM) for accurate metre-based distances. For geographic CRS (degrees), the plugin applies an approximation (~111 320 m per degree).
- Reduce **buffer** and **resolution** for a faster preview export, then increase for the final video.
- The plugin renders **all active map layers** that are visible in the current canvas — style your map before generating.
- For very long lines (> 50 km at 10 m/s, 25 fps) the export will take many minutes. Use a faster speed or lower FPS for quicker results.

---

## License

MIT License – free to use, modify, and distribute.

## Author

Sumit Jangir — [github.com/sumitjangir8796](https://github.com/sumitjangir8796)
