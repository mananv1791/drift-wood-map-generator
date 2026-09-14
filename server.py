import io
import json
import math
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageColor, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8000
HEX_RADIUS = 25
HEX_WIDTH = math.sqrt(3) * HEX_RADIUS
HEX_VERTICAL_STEP = HEX_RADIUS * 1.5


class MapRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "":
            self.serve_file("index.html", "text/html; charset=utf-8")
            return

        if parsed.path in {"/style.css", "/app.js"}:
            content_type = "text/css; charset=utf-8" if parsed.path.endswith(".css") else "application/javascript; charset=utf-8"
            self.serve_file(parsed.path.lstrip("/"), content_type)
            return

        self.send_error(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/generate":
            self.send_error(404, "Not found")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            settings = json.loads(payload.decode("utf-8"))
            png = generate_map_png(settings)
        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Server error: {exc}".encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        self.end_headers()
        self.wfile.write(png)

    def log_message(self, format, *args):
        return

    def serve_file(self, name, content_type):
        path = ROOT / name
        if not path.exists():
            self.send_error(404, "Not found")
            return

        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def generate_map_png(settings):
    seed = int(settings.get("seed", random.randint(0, 10**9)))
    width = clamp(int(settings.get("outputWidth", 1400)), 640, 4096)
    height = clamp(int(settings.get("outputHeight", 900)), 480, 4096)
    tiles_x = clamp(int(settings.get("tilesX", 18)), 4, 120)
    tiles_y = clamp(int(settings.get("tilesY", 14)), 4, 120)
    base_scale = clamp(float(settings.get("scale", 1.0)), 0.2, 2.0)
    relief = clamp(float(settings.get("relief", 0.56)), 0.0, 1.0)
    height_bias = clamp(float(settings.get("height", 0.68)), 0.15, 1.2)
    max_height = clamp(float(settings.get("maxHeight", 1.0)), 0.35, 1.3)
    min_height = clamp(float(settings.get("minHeight", 0.08)), 0.0, 0.6)
    offset_x = clamp(float(settings.get("offsetX", 0.0)), -1.0, 1.0)
    offset_y = clamp(float(settings.get("offsetY", 0.0)), -1.0, 1.0)
    water_aspect = clamp(float(settings.get("waterAspect", 0.76)), 0.5, 1.0)
    reef_amount = clamp(float(settings.get("reefAmount", 0.44)), 0.0, 1.0)
    reef_size = clamp(float(settings.get("reefSize", 0.48)), 0.2, 1.0)
    river_placement = settings.get("riverPlacement", "top_to_bottom")
    planet_theme = settings.get("planetTheme", "earth")
    features = settings.get("features", {})
    colors = settings.get("colors", {})
    terrain_counts = normalize_terrain_counts(settings.get("terrainCounts", {}), tiles_x * tiles_y, features)

    rng = random.Random(seed)
    planet_rules = build_planet_rules(planet_theme)
    render_features = dict(features)
    if planet_rules["force_frozen_water"]:
        render_features["frozenWater"] = True

    palette = {
        "sand": ImageColor.getrgb(colors.get("sand", planet_rules["palette"]["sand"])),
        "plain": ImageColor.getrgb(colors.get("plain", planet_rules["palette"]["plain"])),
        "forest": ImageColor.getrgb(colors.get("forest", planet_rules["palette"]["forest"])),
        "deep_forest": ImageColor.getrgb(colors.get("deepForest", planet_rules["palette"]["deepForest"])),
        "stone": ImageColor.getrgb(colors.get("stone", planet_rules["palette"]["stone"])),
        "rock": ImageColor.getrgb(colors.get("rock", planet_rules["palette"]["rock"])),
        "deep_water": ImageColor.getrgb(colors.get("deepWater", planet_rules["palette"]["deepWater"])),
        "foam": ImageColor.getrgb(colors.get("foam", planet_rules["palette"]["foam"])),
        "bg_top": ImageColor.getrgb(planet_rules["palette"]["bgTop"]),
        "bg_bottom": ImageColor.getrgb(planet_rules["palette"]["bgBottom"]),
    }

    blobs = [
        {
            "x": clamp(0.18 + rng.random() * 0.64 + offset_x * 0.05, 0.0, 1.0),
            "y": clamp(0.14 + rng.random() * 0.72 + offset_y * 0.05, 0.0, 1.0),
            "sigma": 0.10 + rng.random() * 0.20,
            "amp": 0.45 + rng.random() * 0.75,
        }
        for _ in range(7)
    ]

    vertical_anchors = build_axis_anchors(rng, tiles_y, reverse=river_placement == "bottom_to_top")
    horizontal_anchors = build_axis_anchors(rng, tiles_x)
    curve_points = build_curve_path(rng)
    lake_blobs = build_lake_blobs(rng)
    river_profile = build_river_profile(rng)
    noise_a = rng.randint(0, 10_000)
    noise_b = rng.randint(0, 10_000)

    tiles = []
    for row in range(tiles_y):
        ny = row / max(1, tiles_y - 1)
        for col in range(tiles_x):
            nx = col / max(1, tiles_x - 1)
            island_mask = gaussian_field(nx, ny, blobs)
            macro_noise = fractal_noise(nx * 3.0 + 10.0, ny * 3.0 + 4.0, 4, noise_a)
            micro_noise = fractal_noise(nx * 11.0 + 39.0, ny * 11.0 + 18.0, 3, noise_b)
            center = (0.5 + offset_x * 0.12, 0.5 + offset_y * 0.12)
            edge = 1.0 - min(1.0, math.dist((nx, ny), center) / 0.78) ** 1.6
            water_score, river_strength = water_layout_score(
                nx,
                ny,
                row,
                col,
                river_placement,
                vertical_anchors,
                horizontal_anchors,
                curve_points,
                lake_blobs,
                river_profile,
                water_aspect,
                island_mask,
                offset_x,
                offset_y,
            )

            elevation = island_mask * 0.78 + macro_noise * 0.22 + edge * height_bias - water_score * 0.38
            elevation = clamp(elevation, min_height - 0.2, max_height)
            moisture = clamp01(0.52 + micro_noise * 0.4 + river_strength * 0.3 - abs(elevation - 0.5) * 0.12)
            obstacle_signal = fractal_noise(nx * 15.2 + 17.0, ny * 15.2 + 31.0, 2, seed + row * 19 + col * 7)

            tile = {
                "col": col,
                "row": row,
                "elevation": elevation,
                "elevation_raw": elevation,
                "moisture": moisture,
                "river_strength": river_strength,
                "water_score": water_score,
                "obstacle_signal": obstacle_signal,
                "island_mask": island_mask,
                "macro_noise": macro_noise,
                "micro_noise": micro_noise,
                "edge": edge,
                "water": False,
                "deep_water": False,
                "reef": False,
                "stone": False,
                "log": False,
                "village": False,
                "boar": False,
                "start": False,
                "end": False,
                "height_level": 1,
                "biome": "plain",
            }
            tiles.append(tile)

    assign_terrain_biomes(tiles, terrain_counts, features)
    assign_reefs(tiles, reef_amount, reef_size, features.get("reefs", True), rng)
    assign_obstacles(tiles, bool(features.get("erosion", False)), rng)
    assign_decorations(tiles, features, rng)
    assign_endpoints(tiles)

    image = Image.new("RGBA", (width, height), palette["bg_bottom"])
    draw = ImageDraw.Draw(image, "RGBA")
    paint_background(draw, width, height, palette)

    tile_scale = compute_tile_scale(width, height, tiles_x, tiles_y, base_scale)
    positions = build_positions(width, height, tiles_x, tiles_y, tile_scale, offset_x, offset_y)
    sorted_tiles = sorted(tiles, key=lambda tile: (tile["row"], tile["col"]))

    for tile in sorted_tiles:
        x, y = positions[tile["row"] * tiles_x + tile["col"]]
        height_offset = 0 if tile["water"] else (tile.get("height_level", 1) - 1) * 24 * relief * tile_scale
        draw_tile(draw, x, y - height_offset, tile, tile_scale, palette, render_features, planet_rules)

    draw_label(draw, seed)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def draw_tile(draw, x, y, tile, tile_scale, palette, features, planet_rules):
    radius = HEX_RADIUS * tile_scale
    height_steps = tile.get("height_level", 1)

    fill = tile_color(tile, palette, features)
    for i in range(height_steps):
        layer_y = y + (height_steps - i - 1) * 12 * tile_scale
        layer_fill = darken(fill, 0.10 + i * 0.05) if i < height_steps - 1 else fill
        draw_hex(draw, x, layer_y, radius, layer_fill, darken(layer_fill, 0.18))

    draw_planet_nature(draw, x, y, tile, tile_scale, palette, planet_rules)

    if tile["reef"]:
        draw_reef(draw, x, y - 4 * tile_scale, tile_scale, palette, planet_rules)
    if tile["stone"]:
        draw_stone(draw, x, y - 3 * tile_scale, tile_scale, planet_rules)
    if tile["log"]:
        draw_log(draw, x, y - 1 * tile_scale, tile_scale, planet_rules)
    if tile["village"]:
        draw_village(draw, x, y - 2 * tile_scale, tile_scale, planet_rules)
    if tile["boar"]:
        draw_boar(draw, x, y - 1 * tile_scale, tile_scale, planet_rules)
    if tile["start"]:
        draw_marker(draw, x, y - 10 * tile_scale, tile_scale, (255, 215, 110), "S")
    if tile["end"]:
        draw_marker(draw, x, y - 10 * tile_scale, tile_scale, (243, 138, 93), "E")


def draw_hex(draw, cx, cy, radius, fill, outline):
    points = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=fill, outline=outline)


def draw_reef(draw, x, y, scale, palette, planet_rules):
    for i in range(3):
        rx = x - 9 * scale + i * 7 * scale
        ry = y + (i % 2) * 3 * scale
        r = (2.5 + i) * scale
        if planet_rules["name"] == "frozen":
            draw.polygon(
                [(rx, ry - r), (rx + r * 0.7, ry), (rx, ry + r), (rx - r * 0.7, ry)],
                fill=lighten(palette["foam"], 0.08),
                outline=(215, 240, 255),
            )
        elif planet_rules["name"] == "volcanic":
            draw.ellipse((rx - r, ry - r, rx + r, ry + r), fill=(255, 126, 70), outline=(111, 41, 22))
        elif planet_rules["name"] == "alien":
            draw.ellipse((rx - r, ry - r, rx + r, ry + r), fill=(149, 255, 219), outline=(52, 154, 128))
        else:
            draw.ellipse((rx - r, ry - r, rx + r, ry + r), fill=lighten(palette["foam"], 0.06))


def draw_stone(draw, x, y, scale, planet_rules):
    if planet_rules["name"] == "volcanic":
        draw.ellipse((x - 8 * scale, y - 5 * scale, x + 8 * scale, y + 5 * scale), fill=(88, 84, 92), outline=(46, 44, 48))
        draw.line((x - 4 * scale, y, x + 4 * scale, y - 1 * scale), fill=(255, 116, 54), width=max(1, int(scale)))
        return
    if planet_rules["name"] == "alien":
        draw.polygon(
            [(x, y - 6 * scale), (x + 6 * scale, y), (x, y + 5 * scale), (x - 5 * scale, y)],
            fill=(184, 179, 255),
            outline=(96, 101, 188),
        )
        return
    draw.ellipse((x - 8 * scale, y - 5 * scale, x + 8 * scale, y + 5 * scale), fill=(148, 156, 168), outline=(94, 101, 111))
    draw.ellipse((x - 4 * scale, y - 3 * scale, x, y - 0.5 * scale), fill=(230, 234, 239))


def draw_log(draw, x, y, scale, planet_rules):
    w = 18 * scale
    h = 5 * scale
    if planet_rules["name"] == "frozen":
        draw.rounded_rectangle((x - w / 2, y - h / 2, x + w / 2, y + h / 2), radius=2 * scale, fill=(190, 215, 230), outline=(120, 146, 165))
        return
    if planet_rules["name"] == "volcanic":
        draw.rounded_rectangle((x - w / 2, y - h / 2, x + w / 2, y + h / 2), radius=2 * scale, fill=(72, 58, 56), outline=(37, 29, 29))
        return
    if planet_rules["name"] == "alien":
        draw.rounded_rectangle((x - w / 2, y - h / 2, x + w / 2, y + h / 2), radius=2 * scale, fill=(97, 232, 194), outline=(37, 110, 99))
        return
    draw.rounded_rectangle((x - w / 2, y - h / 2, x + w / 2, y + h / 2), radius=2 * scale, fill=(122, 78, 40), outline=(94, 59, 28))


def draw_village(draw, x, y, scale, planet_rules):
    if planet_rules["name"] == "desert":
        draw.rounded_rectangle((x - 8 * scale, y - 5 * scale, x + 8 * scale, y + 5 * scale), radius=3 * scale, fill=(194, 160, 104), outline=(132, 102, 56))
        draw.arc((x - 9 * scale, y - 12 * scale, x + 9 * scale, y + 4 * scale), 180, 360, fill=(237, 219, 171), width=max(1, int(scale)))
        return
    if planet_rules["name"] == "frozen":
        draw.rounded_rectangle((x - 8 * scale, y - 6 * scale, x + 8 * scale, y + 6 * scale), radius=2 * scale, fill=(166, 194, 219), outline=(92, 121, 147))
        draw.polygon([(x - 10 * scale, y), (x, y - 11 * scale), (x + 10 * scale, y)], fill=(242, 248, 255), outline=(184, 200, 214))
        return
    if planet_rules["name"] == "volcanic":
        draw.rounded_rectangle((x - 8 * scale, y - 6 * scale, x + 8 * scale, y + 6 * scale), radius=2 * scale, fill=(98, 77, 66), outline=(52, 39, 35))
        draw.polygon([(x - 10 * scale, y), (x, y - 11 * scale), (x + 10 * scale, y)], fill=(235, 123, 72), outline=(163, 70, 44))
        return
    if planet_rules["name"] == "alien":
        draw.ellipse((x - 8 * scale, y - 6 * scale, x + 8 * scale, y + 6 * scale), fill=(171, 247, 224), outline=(70, 147, 126))
        draw.ellipse((x - 4 * scale, y - 10 * scale, x + 4 * scale, y - 2 * scale), fill=(214, 255, 244), outline=(112, 190, 173))
        return
    draw.rounded_rectangle((x - 8 * scale, y - 6 * scale, x + 8 * scale, y + 6 * scale), radius=2 * scale, fill=(139, 103, 56), outline=(94, 70, 35))
    draw.polygon([(x - 10 * scale, y - 1 * scale), (x, y - 11 * scale), (x + 10 * scale, y - 1 * scale)], fill=(215, 186, 117), outline=(163, 132, 67))


def draw_boar(draw, x, y, scale, planet_rules):
    if planet_rules["name"] == "frozen":
        body = (220, 233, 240)
        outline = (129, 152, 164)
    elif planet_rules["name"] == "volcanic":
        body = (117, 67, 49)
        outline = (64, 34, 25)
    elif planet_rules["name"] == "alien":
        body = (118, 240, 206)
        outline = (43, 122, 105)
    else:
        body = (90, 56, 32)
        outline = (61, 37, 22)
    draw.ellipse((x - 7 * scale, y - 4 * scale, x + 7 * scale, y + 4 * scale), fill=body, outline=outline)
    draw.rectangle((x + 2 * scale, y - 1.5 * scale, x + 6 * scale, y + 1.5 * scale), fill=body)


def draw_marker(draw, x, y, scale, fill, label):
    r = 9 * scale
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=(29, 28, 26))
    font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text((x - text_w / 2, y - text_h / 2 - 1), label, fill=(29, 28, 26), font=font)


def draw_label(draw, seed):
    draw.rounded_rectangle((20, 18, 200, 68), radius=14, fill=(14, 14, 14, 140))
    font = ImageFont.load_default()
    draw.text((36, 30), "Seed", fill=(242, 239, 234), font=font)
    draw.text((36, 48), str(seed), fill=(242, 239, 234), font=font)


def paint_background(draw, width, height, palette):
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line((0, y, width, y), fill=blend_rgb(palette["bg_top"], palette["bg_bottom"], t))


def draw_planet_nature(draw, x, y, tile, scale, palette, planet_rules):
    if tile["water"]:
        if planet_rules["name"] == "frozen" and not tile["deep_water"]:
            draw.line((x - 7 * scale, y - 1 * scale, x + 7 * scale, y + 1 * scale), fill=(235, 248, 255), width=max(1, int(scale)))
            draw.line((x - 3 * scale, y - 4 * scale, x + 3 * scale, y + 4 * scale), fill=(216, 236, 248), width=max(1, int(scale)))
        elif planet_rules["name"] == "alien":
            draw.ellipse((x - 3 * scale, y - 3 * scale, x + 3 * scale, y + 3 * scale), fill=(150, 255, 229, 160))
        return

    if tile["biome"] == "forest":
        if planet_rules["name"] == "desert":
            draw_desert_shrub(draw, x, y - 3 * scale, scale)
        elif planet_rules["name"] == "frozen":
            draw_frost_tree(draw, x, y - 2 * scale, scale)
        elif planet_rules["name"] == "volcanic":
            draw_smoke_vent(draw, x, y - 2 * scale, scale)
        elif planet_rules["name"] == "alien":
            draw_crystal_cluster(draw, x, y - 2 * scale, scale, (163, 255, 235), (71, 188, 157))
        else:
            draw_forest_canopy(draw, x, y - 2 * scale, scale)
        return

    if tile["biome"] == "sand" and planet_rules["name"] == "desert":
        draw_dunes(draw, x, y, scale)
    elif tile["biome"] == "plain" and planet_rules["name"] == "alien":
        draw_crystal_cluster(draw, x, y - 1 * scale, scale * 0.85, (195, 182, 255), (99, 92, 176))
    elif tile["biome"] == "rock" and planet_rules["name"] == "frozen":
        draw_snow_cap(draw, x, y - 6 * scale, scale)
    elif tile["biome"] in {"stone", "rock"} and planet_rules["name"] == "volcanic":
        draw_lava_crack(draw, x, y - 2 * scale, scale)


def draw_forest_canopy(draw, x, y, scale):
    draw.ellipse((x - 5 * scale, y - 4 * scale, x + 1 * scale, y + 2 * scale), fill=(58, 125, 41, 170))
    draw.ellipse((x - 1 * scale, y - 5 * scale, x + 5 * scale, y + 2 * scale), fill=(43, 104, 31, 170))


def draw_desert_shrub(draw, x, y, scale):
    draw.line((x, y - 4 * scale, x, y + 2 * scale), fill=(101, 134, 59), width=max(1, int(scale)))
    draw.line((x, y - 1 * scale, x - 3 * scale, y - 3 * scale), fill=(101, 134, 59), width=max(1, int(scale)))
    draw.line((x, y, x + 3 * scale, y - 2 * scale), fill=(101, 134, 59), width=max(1, int(scale)))


def draw_frost_tree(draw, x, y, scale):
    draw.polygon([(x, y - 7 * scale), (x + 5 * scale, y + 1 * scale), (x - 5 * scale, y + 1 * scale)], fill=(214, 238, 246), outline=(141, 176, 190))
    draw.line((x, y + 1 * scale, x, y + 5 * scale), fill=(120, 146, 164), width=max(1, int(scale)))


def draw_smoke_vent(draw, x, y, scale):
    draw.ellipse((x - 2 * scale, y, x + 2 * scale, y + 3 * scale), fill=(79, 72, 71))
    draw.ellipse((x - 4 * scale, y - 5 * scale, x, y - 1 * scale), fill=(128, 118, 116, 180))
    draw.ellipse((x, y - 7 * scale, x + 5 * scale, y - 2 * scale), fill=(148, 136, 135, 150))


def draw_crystal_cluster(draw, x, y, scale, fill, outline):
    draw.polygon([(x, y - 7 * scale), (x + 4 * scale, y), (x, y + 5 * scale), (x - 3 * scale, y)], fill=fill, outline=outline)
    draw.polygon([(x + 4 * scale, y - 4 * scale), (x + 7 * scale, y + 1 * scale), (x + 4 * scale, y + 4 * scale), (x + 2 * scale, y + 1 * scale)], fill=lighten(fill, 0.08), outline=outline)


def draw_dunes(draw, x, y, scale):
    draw.arc((x - 8 * scale, y - 2 * scale, x + 2 * scale, y + 5 * scale), 200, 360, fill=(230, 201, 144), width=max(1, int(scale)))
    draw.arc((x - 1 * scale, y - 3 * scale, x + 9 * scale, y + 4 * scale), 180, 340, fill=(199, 163, 102), width=max(1, int(scale)))


def draw_snow_cap(draw, x, y, scale):
    draw.polygon([(x - 5 * scale, y), (x, y - 4 * scale), (x + 5 * scale, y), (x, y + 2 * scale)], fill=(245, 250, 255), outline=(208, 224, 236))


def draw_lava_crack(draw, x, y, scale):
    draw.line((x - 5 * scale, y + 1 * scale, x - 1 * scale, y - 2 * scale), fill=(255, 114, 58), width=max(1, int(scale)))
    draw.line((x - 1 * scale, y - 2 * scale, x + 4 * scale, y + 2 * scale), fill=(255, 144, 71), width=max(1, int(scale)))


def tile_color(tile, palette, features):
    frozen_water = features.get("frozenWater")
    if tile["deep_water"]:
        return (143, 182, 197) if frozen_water else palette["deep_water"]
    if tile["water"]:
        return (185, 214, 223) if frozen_water else blend_rgb(palette["deep_water"], palette["foam"], 0.34)
    if tile["biome"] == "sand":
        return palette["sand"]
    if tile["biome"] == "forest":
        return palette["forest"]
    if tile["biome"] == "deep_forest":
        return palette["deep_forest"]
    if tile["biome"] == "stone":
        return palette["stone"]
    if tile["biome"] == "rock":
        return palette["rock"]
    return palette["plain"]


def normalize_terrain_counts(raw_counts, total_tiles, features):
    counts = {
        "water": max(0, int(raw_counts.get("water", 54))),
        "sand": max(0, int(raw_counts.get("sand", 32))),
        "plain": max(0, int(raw_counts.get("plain", 78))),
        "forest": max(0, int(raw_counts.get("forest", 42))),
        "stone": max(0, int(raw_counts.get("stone", 28))),
        "mountain": max(0, int(raw_counts.get("mountain", 18))),
    }

    if sum(counts.values()) != total_tiles:
        raise ValueError(f"Terrain counts must add up to {total_tiles} tiles")

    return counts


def build_planet_rules(planet_theme):
    presets = {
        "earth": {
            "name": "earth",
            "palette": {
                "sand": "#dfca72",
                "plain": "#6fca49",
                "forest": "#399326",
                "deepForest": "#214f17",
                "stone": "#718176",
                "rock": "#a5b3af",
                "deepWater": "#235f95",
                "foam": "#cdeef7",
                "bgTop": "#34312d",
                "bgBottom": "#201f1d",
            },
            "force_frozen_water": False,
        },
        "desert": {
            "name": "desert",
            "palette": {
                "sand": "#d8b36a",
                "plain": "#c7954c",
                "forest": "#6b8a3a",
                "deepForest": "#496227",
                "stone": "#8d7763",
                "rock": "#c4ab8f",
                "deepWater": "#2a7f8a",
                "foam": "#d8f1ea",
                "bgTop": "#4e3a2c",
                "bgBottom": "#2f231d",
            },
            "force_frozen_water": False,
        },
        "frozen": {
            "name": "frozen",
            "palette": {
                "sand": "#c9d3dd",
                "plain": "#d9e7ee",
                "forest": "#7bb7c8",
                "deepForest": "#4a7a8b",
                "stone": "#8fa2b7",
                "rock": "#e6eef7",
                "deepWater": "#4e7db5",
                "foam": "#f3fbff",
                "bgTop": "#31445a",
                "bgBottom": "#1c2633",
            },
            "force_frozen_water": True,
        },
        "volcanic": {
            "name": "volcanic",
            "palette": {
                "sand": "#6b4a36",
                "plain": "#594136",
                "forest": "#6f5b44",
                "deepForest": "#45352f",
                "stone": "#5b5a60",
                "rock": "#8f8b94",
                "deepWater": "#2f4158",
                "foam": "#f1a36b",
                "bgTop": "#412321",
                "bgBottom": "#1f1518",
            },
            "force_frozen_water": False,
        },
        "alien": {
            "name": "alien",
            "palette": {
                "sand": "#a7d36a",
                "plain": "#4ecb8b",
                "forest": "#16916a",
                "deepForest": "#0d5a4e",
                "stone": "#6e78c8",
                "rock": "#b6a8ff",
                "deepWater": "#1e5f8e",
                "foam": "#b8fff0",
                "bgTop": "#1f2a44",
                "bgBottom": "#13172b",
            },
            "force_frozen_water": False,
        },
    }
    return presets.get(planet_theme, presets["earth"])


def assign_terrain_biomes(tiles, counts, features):
    for tile in tiles:
        tile["biome"] = "plain"
        tile["water"] = False
        tile["deep_water"] = False
        tile["height_level"] = 1

    water_tiles = select_top_tiles(tiles, counts["water"], lambda tile: tile["water_score"])
    deep_water_target = min(len(water_tiles), max(1, round(len(water_tiles) * 0.35))) if water_tiles else 0
    deep_water_keys = {
        (tile["col"], tile["row"])
        for tile in sorted(water_tiles, key=lambda tile: tile["water_score"], reverse=True)[:deep_water_target]
    }
    for tile in water_tiles:
        tile["water"] = True
        tile["deep_water"] = (tile["col"], tile["row"]) in deep_water_keys
        tile["biome"] = "deep_water" if tile["deep_water"] else "water"

    annotate_water_adjacency(tiles)

    sand_tiles = select_top_tiles(
        [tile for tile in tiles if not tile["water"]],
        counts["sand"],
        lambda tile: tile["shoreline_score"] * 1.3 + (1.0 - tile["elevation_raw"]) * 0.35 + tile["river_strength"] * 0.25,
    )
    for tile in sand_tiles:
        tile["biome"] = "sand"

    mountain_tiles = select_top_tiles(
        unassigned_tiles(tiles),
        counts["mountain"],
        lambda tile: tile["elevation_raw"] * 1.2 + tile["macro_noise"] * 0.45 + tile["edge"] * 0.2 - tile["shoreline_score"] * 0.65,
    )
    for tile in mountain_tiles:
        tile["biome"] = "rock"
        tile["height_level"] = 2

    stone_tiles = select_top_tiles(
        unassigned_tiles(tiles),
        counts["stone"],
        lambda tile: (1.0 - abs(tile["elevation_raw"] - 0.72)) * 0.9 + tile["macro_noise"] * 0.25 - tile["shoreline_score"] * 0.3,
    )
    for tile in stone_tiles:
        tile["biome"] = "stone"

    forest_tiles = select_top_tiles(
        unassigned_tiles(tiles),
        counts["forest"],
        lambda tile: tile["moisture"] * 0.9 + (1.0 - abs(tile["elevation_raw"] - 0.48)) * 0.35 - tile["shoreline_score"] * 0.18,
    )
    for tile in forest_tiles:
        tile["biome"] = "forest"

    plain_tiles = unassigned_tiles(tiles)
    if len(plain_tiles) != counts["plain"]:
        raise ValueError("Terrain allocation did not match requested plain tile count")
    for tile in plain_tiles:
        tile["biome"] = "plain"


def select_top_tiles(candidates, count, score_fn):
    ordered = sorted(candidates, key=score_fn, reverse=True)
    selected = ordered[:count]
    for tile in selected:
        tile["_assigned"] = True
    return selected


def unassigned_tiles(tiles):
    return [tile for tile in tiles if not tile.get("_assigned") and not tile["water"]]


def annotate_water_adjacency(tiles):
    tile_map = {(tile["col"], tile["row"]): tile for tile in tiles}
    for tile in tiles:
        if tile["water"]:
            tile["shoreline_score"] = 0.0
            continue
        neighbors = [tile_map.get(neighbor) for neighbor in hex_neighbors(tile["col"], tile["row"])]
        water_neighbors = sum(1 for neighbor in neighbors if neighbor and neighbor["water"])
        tile["shoreline_score"] = water_neighbors / 6.0


def assign_reefs(tiles, reef_amount, reef_size, enabled, rng):
    if not enabled:
        return
    candidates = [tile for tile in tiles if tile["water"] and not tile["deep_water"] and tile["river_strength"] < 0.6]
    rng.shuffle(candidates)
    target = round(len(candidates) * reef_amount * 0.15)
    for tile in candidates[:target]:
        tile["reef"] = tile["obstacle_signal"] > 0.57 - reef_size * 0.18


def assign_obstacles(tiles, erosion_enabled, rng):
    for tile in tiles:
        if tile["water"] and not tile["deep_water"]:
            if tile["obstacle_signal"] > 0.76:
                tile["stone"] = True
            if tile["obstacle_signal"] < 0.12 and tile["river_strength"] > 0.33:
                tile["log"] = True
        if erosion_enabled and not tile["water"] and tile["biome"] == "stone" and tile["obstacle_signal"] > 0.65:
            tile["biome"] = "rock"

    near_river = [tile for tile in tiles if not tile["water"] and tile["river_strength"] > 0.16 and tile["biome"] != "rock"]
    rng.shuffle(near_river)
    for tile in near_river[: max(2, int(len(near_river) * 0.025))]:
        if not tile["stone"]:
            tile["log"] = True


def assign_decorations(tiles, features, rng):
    if features.get("village", True):
        village_tiles = sorted(
            [tile for tile in tiles if not tile["water"] and tile["biome"] == "sand" and tile["river_strength"] < 0.26],
            key=lambda tile: tile["row"],
        )
        if village_tiles:
            village_tiles[len(village_tiles) // 2]["village"] = True

    if features.get("boar", False):
        boar_tiles = [tile for tile in tiles if not tile["water"] and tile["biome"] in {"plain", "forest"}]
        rng.shuffle(boar_tiles)
        for tile in boar_tiles[:3]:
            tile["boar"] = True


def assign_endpoints(tiles):
    passable = [tile for tile in tiles if not tile["water"] and not tile["stone"]]
    if len(passable) < 2:
        return

    tile_map = {(tile["col"], tile["row"]): tile for tile in passable}
    visited = set()
    components = []

    for tile in passable:
        key = (tile["col"], tile["row"])
        if key in visited:
            continue
        queue = [tile]
        visited.add(key)
        component = []
        while queue:
            current = queue.pop(0)
            component.append(current)
            for neighbor in hex_neighbors(current["col"], current["row"]):
                if neighbor in tile_map and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(tile_map[neighbor])
        components.append(component)

    largest = max(components, key=len)
    if len(largest) < 2:
        return

    start = min(largest, key=lambda tile: tile["col"] * 1.15 + tile["row"] * 0.85 + tile["river_strength"] * 6)
    end = max(
        largest,
        key=lambda tile: math.dist((tile["col"], tile["row"]), (start["col"], start["row"]))
        + abs(tile["river_strength"] - start["river_strength"]) * 2.5
        + tile["row"] * 0.15,
    )
    if start != end:
        start["start"] = True
        end["end"] = True


def compute_tile_scale(width, height, tiles_x, tiles_y, base_scale):
    base_width = (tiles_x - 1) * HEX_WIDTH * base_scale + HEX_WIDTH * base_scale * 1.5
    base_height = (tiles_y - 1) * HEX_VERTICAL_STEP * base_scale + HEX_RADIUS * 2 * base_scale + 160
    available_width = max(200, width - 140)
    available_height = max(200, height - 180)
    fit_scale = min(1.0, available_width / base_width, available_height / base_height)
    return base_scale * fit_scale


def build_positions(width, height, tiles_x, tiles_y, scale, offset_x, offset_y):
    total_width = (tiles_x - 1) * HEX_WIDTH * scale + HEX_WIDTH * scale * 1.5
    total_height = (tiles_y - 1) * HEX_VERTICAL_STEP * scale + HEX_RADIUS * 2 * scale
    start_x = width * 0.5 - total_width * 0.5 + offset_x * min(140, width * 0.08)
    start_y = height * 0.54 - total_height * 0.46 + offset_y * min(120, height * 0.08)

    positions = []
    for row in range(tiles_y):
        for col in range(tiles_x):
            x = start_x + col * HEX_WIDTH * scale + (row % 2) * (HEX_WIDTH * scale * 0.5) + HEX_WIDTH * scale * 0.75
            y = start_y + row * HEX_VERTICAL_STEP * scale + 110
            positions.append((x, y))
    return positions


def build_axis_anchors(rng, count, reverse=False):
    anchors = []
    center = 0.18 + rng.random() * 0.64
    for _ in range(count):
        center += (rng.random() - 0.5) * 0.18
        center = clamp(center, 0.2, 0.8)
        anchors.append(center)
    anchors = smooth_array(anchors, 2)
    return list(reversed(anchors)) if reverse else anchors


def build_curve_path(rng):
    start = (-0.06, 0.72 + (rng.random() - 0.5) * 0.18)
    control = (0.28 + rng.random() * 0.14, 0.62 + (rng.random() - 0.5) * 0.16)
    end = (0.58 + rng.random() * 0.18, -0.04)
    points = []
    for step in range(18):
        t = step / 17
        points.append(quadratic_bezier(start, control, end, t))
    return points


def build_lake_blobs(rng):
    center_x = 0.5 + (rng.random() - 0.5) * 0.12
    center_y = 0.5 + (rng.random() - 0.5) * 0.12
    return [
        {"x": center_x, "y": center_y, "sigma": 0.17 + rng.random() * 0.05, "amp": 1.0},
        {"x": center_x - 0.12 + rng.random() * 0.08, "y": center_y + 0.08, "sigma": 0.11 + rng.random() * 0.04, "amp": 0.55},
        {"x": center_x + 0.10 - rng.random() * 0.08, "y": center_y - 0.07, "sigma": 0.10 + rng.random() * 0.04, "amp": 0.45},
    ]


def build_river_profile(rng):
    return {
        "width_base": 0.06 + rng.random() * 0.035,
        "width_wobble": 0.015 + rng.random() * 0.025,
        "jitter_scale": 0.06 + rng.random() * 0.08,
        "branch_strength": 0.05 + rng.random() * 0.08,
        "bank_spread": 1.15 + rng.random() * 0.45,
        "noise_seed": rng.randint(1, 1_000_000),
        "secondary_seed": rng.randint(1, 1_000_000),
    }


def water_layout_score(
    nx,
    ny,
    row,
    col,
    mode,
    vertical_anchors,
    horizontal_anchors,
    curve_points,
    lake_blobs,
    river_profile,
    water_aspect,
    island_mask,
    offset_x,
    offset_y,
):
    jitter = (value_noise(nx * 5.0 + 3.7, ny * 5.0 + 8.2, river_profile["noise_seed"]) - 0.5) * river_profile["jitter_scale"]
    branch = (value_noise(nx * 8.0 + 11.0, ny * 8.0 + 17.0, river_profile["secondary_seed"]) - 0.5) * river_profile["branch_strength"]

    if mode == "top_to_bottom" or mode == "bottom_to_top":
        center = clamp(vertical_anchors[row] + jitter + branch * 0.45, 0.08, 0.92)
        width = river_profile["width_base"] + water_aspect * 0.06 + river_profile["width_wobble"] * (0.5 + island_mask)
        river_distance = abs(nx - center)
        river_strength = clamp01(1.0 - river_distance / width)
        side_channel = clamp01(1.0 - abs(nx - (center + branch)) / (width * 0.7))
        return clamp01(river_strength * 0.88 + side_channel * 0.24 + (1.0 - island_mask) * 0.08), max(river_strength, side_channel * 0.72)

    if mode == "left_to_right":
        center = clamp(horizontal_anchors[col] + jitter + branch * 0.45, 0.08, 0.92)
        width = river_profile["width_base"] + water_aspect * 0.06 + river_profile["width_wobble"] * (0.5 + island_mask)
        river_distance = abs(ny - center)
        river_strength = clamp01(1.0 - river_distance / width)
        side_channel = clamp01(1.0 - abs(ny - (center + branch)) / (width * 0.7))
        return clamp01(river_strength * 0.88 + side_channel * 0.24 + (1.0 - island_mask) * 0.08), max(river_strength, side_channel * 0.72)

    if mode == "left_to_top_curve":
        width = river_profile["width_base"] + water_aspect * 0.05 + river_profile["width_wobble"] * 0.8
        curve_distance = distance_to_polyline((nx, ny), curve_points)
        curve_offset = abs(branch) * 0.4
        river_strength = clamp01(1.0 - curve_distance / width)
        side_channel = clamp01(1.0 - abs(curve_distance - curve_offset) / (width * 0.7))
        return clamp01(river_strength * 0.87 + side_channel * 0.22 + (1.0 - island_mask) * 0.05), max(river_strength, side_channel * 0.68)

    if mode == "middle_pond":
        center = (0.5 + offset_x * 0.08, 0.5 + offset_y * 0.08)
        pond = clamp01(1.0 - math.dist((nx, ny), center) / (0.17 + water_aspect * 0.07 + abs(jitter) * 0.45))
        ripple = clamp01(gaussian_field(nx, ny, [{"x": center[0] + branch, "y": center[1] - jitter, "sigma": 0.08, "amp": 1.0}]))
        return clamp01(pond * 0.85 + ripple * 0.3), pond * 0.7

    if mode == "lake":
        lake_score = clamp01(gaussian_field(nx, ny, lake_blobs) * 1.1)
        shore_variation = value_noise(nx * 6.0 + 2.0, ny * 6.0 + 5.0, river_profile["noise_seed"])
        lake_score = clamp01(lake_score * (0.84 + shore_variation * 0.32))
        return lake_score, lake_score * 0.55

    if mode == "land_around_river":
        center = clamp(vertical_anchors[row] + jitter * 0.8, 0.08, 0.92)
        width = river_profile["width_base"] * 0.8 + water_aspect * 0.04
        river_distance = abs(nx - center)
        river_strength = clamp01(1.0 - river_distance / width)
        bank_bonus = clamp01(1.0 - abs(river_distance - width * river_profile["bank_spread"]) / (width * 0.8))
        return clamp01(river_strength + (1.0 - island_mask) * 0.05), clamp01(river_strength + bank_bonus * 0.25)

    center = vertical_anchors[row]
    width = 0.08 + water_aspect * 0.07
    river_distance = abs(nx - center)
    river_strength = clamp01(1.0 - river_distance / width)
    return river_strength, river_strength


def gaussian_field(x, y, blobs):
    value = 0.0
    for blob in blobs:
        dx = x - blob["x"]
        dy = y - blob["y"]
        value += blob["amp"] * math.exp(-((dx * dx + dy * dy) / (2 * blob["sigma"] * blob["sigma"])))
    return clamp01(value / 2.8)


def smooth_array(values, passes):
    result = values[:]
    for _ in range(passes):
        result = [
            (result[max(0, i - 1)] + result[i] * 2 + result[min(len(result) - 1, i + 1)]) / 4
            for i in range(len(result))
        ]
    return result


def fractal_noise(x, y, octaves, seed):
    amplitude = 0.5
    frequency = 1.0
    total = 0.0
    norm = 0.0
    for i in range(octaves):
        total += value_noise(x * frequency, y * frequency, seed + i * 31) * amplitude
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return total / norm if norm else 0.0


def value_noise(x, y, seed):
    x0 = math.floor(x)
    y0 = math.floor(y)
    x1 = x0 + 1
    y1 = y0 + 1
    sx = smoothstep(x - x0)
    sy = smoothstep(y - y0)

    n00 = hash_noise(x0, y0, seed)
    n10 = hash_noise(x1, y0, seed)
    n01 = hash_noise(x0, y1, seed)
    n11 = hash_noise(x1, y1, seed)

    ix0 = lerp(n00, n10, sx)
    ix1 = lerp(n01, n11, sx)
    return lerp(ix0, ix1, sy)


def hash_noise(x, y, seed):
    value = math.sin(x * 127.1 + y * 311.7 + seed * 0.019) * 43758.5453123
    return value - math.floor(value)


def hex_neighbors(col, row):
    if row % 2:
        deltas = [(-1, 0), (1, 0), (0, -1), (1, -1), (0, 1), (1, 1)]
    else:
        deltas = [(-1, 0), (1, 0), (-1, -1), (0, -1), (-1, 1), (0, 1)]
    return [(col + dc, row + dr) for dc, dr in deltas]


def quadratic_bezier(start, control, end, t):
    mt = 1.0 - t
    x = mt * mt * start[0] + 2 * mt * t * control[0] + t * t * end[0]
    y = mt * mt * start[1] + 2 * mt * t * control[1] + t * t * end[1]
    return (x, y)


def distance_to_polyline(point, points):
    if len(points) < 2:
        return math.dist(point, points[0]) if points else 1.0
    return min(point_segment_distance(point, points[i], points[i + 1]) for i in range(len(points) - 1))


def point_segment_distance(point, start, end):
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.dist(point, start)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = clamp01(t)
    projection = (x1 + dx * t, y1 + dy * t)
    return math.dist(point, projection)


def blend_rgb(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def darken(color, amount):
    return tuple(int(round(channel * (1 - amount))) for channel in color)


def lighten(color, amount):
    return tuple(int(round(channel + (255 - channel) * amount)) for channel in color)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    return t * t * (3 - 2 * t)


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def clamp01(value):
    return clamp(value, 0.0, 1.0)


def main():
    server = ThreadingHTTPServer((HOST, PORT), MapRequestHandler)
    print(f"Drift Wood map server running at http://{HOST}:{PORT}")
    print('Start it on macOS with: python3 server.py')
    server.serve_forever()


if __name__ == "__main__":
    main()
