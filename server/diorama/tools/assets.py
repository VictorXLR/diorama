"""Asset tools: real maps, geocoding, remote images and routing.

All providers are keyless by default (OpenStreetMap tiles, Nominatim, OSRM demo) and
overridable through environment variables so a deployment can point at Mapbox,
Geoapify, a self-hosted tile server, etc.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import math
import os
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from pydantic import BaseModel, ConfigDict, Field

from diorama.models.canvas import CanvasFile, CanvasPatch
from diorama.tools.base import Tool, ToolContext, ToolError, ToolResult
from diorama.visual.primitives import ImagePrimitive

USER_AGENT = os.getenv("DIORAMA_HTTP_USER_AGENT", "Diorama/0.1 (+https://github.com/diorama; whiteboard agent)")

TILE_STYLES: Dict[str, str] = {
    "streets": os.getenv("DIORAMA_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
    "light": os.getenv("DIORAMA_TILE_URL_LIGHT", "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"),
    "dark": os.getenv("DIORAMA_TILE_URL_DARK", "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"),
}
ATTRIBUTION = "© OpenStreetMap contributors" + (", © CARTO" if "cartocdn" in TILE_STYLES["light"] else "")
NOMINATIM_URL = os.getenv("DIORAMA_GEOCODER_URL", "https://nominatim.openstreetmap.org/search")
OSRM_URL = os.getenv("DIORAMA_OSRM_URL", "https://router.project-osrm.org")
TILE_SIZE = 256
MAX_TILES = 64
MAX_IMAGE_BYTES = 6 * 1024 * 1024

# Tiny in-process caches keep repeated lookups (same trip, several turns) fast and polite.
_geocode_cache: Dict[str, Tuple[float, float, str]] = {}
_tile_cache: Dict[str, bytes] = {}


class MapMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Label, also used for geocoding when lat/lon are omitted.")
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)


class FetchMapArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(default="map", description="Primitive id for the placed image (reuse to replace).")
    markers: List[MapMarker] = Field(
        min_length=1,
        max_length=25,
        description="Places to include; the map is fitted around them. Order matters when drawRoute is true.",
    )
    width: int = Field(default=800, ge=200, le=1600, description="Image width in scene px.")
    height: int = Field(default=520, ge=200, le=1200)
    zoom: Optional[int] = Field(default=None, ge=1, le=17, description="Override the auto-fitted zoom level.")
    style: Literal["auto", "streets", "light", "dark"] = "auto"
    draw_route: bool = Field(default=False, alias="drawRoute", description="Draw straight legs between markers in order.")
    draw_markers: bool = Field(default=False, alias="drawMarkers", description="Burn dots into the image (usually false: place pins instead).")
    x: Optional[float] = Field(default=None, description="Scene x to place the image; omit to only return the asset.")
    y: Optional[float] = None
    frame: Optional[str] = None
    caption: Optional[str] = None


class GeocodeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    places: List[str] = Field(min_length=1, max_length=25)


class FetchImageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1, description="Primitive id for the placed image.")
    url: str = Field(pattern=r"^https://", description="Direct https link to a PNG/JPEG/GIF/WebP/SVG.")
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = Field(default=None, gt=0, description="Scene width; height keeps aspect ratio.")
    frame: Optional[str] = None
    caption: Optional[str] = None


class RouteInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waypoints: List[MapMarker] = Field(min_length=2, max_length=12)
    profile: Literal["driving", "walking", "cycling"] = "driving"


# --------------------------------------------------------------------------- helpers


def _client(timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


async def geocode(place: str) -> Tuple[float, float, str]:
    key = place.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]
    async with _client() as client:
        try:
            response = await client.get(
                NOMINATIM_URL, params={"q": place, "format": "jsonv2", "limit": 1, "accept-language": "en"}
            )
            response.raise_for_status()
            results = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolError(f"Geocoding '{place}' failed: {exc.__class__.__name__}") from exc
    if not results:
        raise ToolError(f"No location found for '{place}'. Try a more specific name or pass lat/lon.")
    hit = results[0]
    value = (float(hit["lat"]), float(hit["lon"]), str(hit.get("display_name", place)))
    _geocode_cache[key] = value
    return value


async def resolve_markers(markers: List[MapMarker]) -> List[Dict[str, Any]]:
    resolved: List[Dict[str, Any]] = []
    for marker in markers:
        if marker.lat is not None and marker.lon is not None:
            resolved.append({"name": marker.name, "lat": marker.lat, "lon": marker.lon})
            continue
        lat, lon, display = await geocode(marker.name)
        resolved.append({"name": marker.name, "lat": lat, "lon": lon, "resolved": display})
        await asyncio.sleep(0.2)  # Nominatim usage policy: max 1 req/s
    return resolved


def _project(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Web-Mercator lat/lon → global pixel coordinates at ``zoom``."""
    scale = TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(max(min(lat, 85.05112878), -85.05112878))
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * scale
    return x, y


def fit_zoom(points: List[Tuple[float, float]], width: int, height: int, padding: float = 0.15) -> int:
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    for zoom in range(17, 0, -1):
        xs, ys = zip(*(_project(lat, lon, zoom) for lat, lon in zip(lats, lons)))
        span_x = (max(xs) - min(xs)) * (1 + 2 * padding)
        span_y = (max(ys) - min(ys)) * (1 + 2 * padding)
        if span_x <= width and span_y <= height:
            return zoom
    return 1


async def _fetch_tile(client: httpx.AsyncClient, template: str, z: int, x: int, y: int) -> Optional[bytes]:
    n = 2**z
    x %= n
    if y < 0 or y >= n:
        return None
    url = template.format(z=z, x=x, y=y, s="a")
    if url in _tile_cache:
        return _tile_cache[url]
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    if len(_tile_cache) > 512:
        _tile_cache.clear()
    _tile_cache[url] = response.content
    return response.content


async def render_static_map(
    points: List[Dict[str, Any]],
    *,
    width: int,
    height: int,
    zoom: Optional[int],
    style: str,
    draw_route: bool,
    draw_markers: bool,
) -> Tuple[bytes, List[Dict[str, Any]], int]:
    """Stitch OSM tiles into a PNG centred on the markers; returns (png, marker pixel positions, zoom)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise ToolError("Pillow is required for map rendering (pip install pillow).") from exc

    coords = [(p["lat"], p["lon"]) for p in points]
    zoom = zoom or fit_zoom(coords, width, height)
    projected = [_project(lat, lon, zoom) for lat, lon in coords]
    center_x = (min(p[0] for p in projected) + max(p[0] for p in projected)) / 2
    center_y = (min(p[1] for p in projected) + max(p[1] for p in projected)) / 2
    origin_x = center_x - width / 2
    origin_y = center_y - height / 2

    tile_x0, tile_y0 = int(math.floor(origin_x / TILE_SIZE)), int(math.floor(origin_y / TILE_SIZE))
    tile_x1, tile_y1 = int(math.floor((origin_x + width) / TILE_SIZE)), int(math.floor((origin_y + height) / TILE_SIZE))
    tile_count = (tile_x1 - tile_x0 + 1) * (tile_y1 - tile_y0 + 1)
    if tile_count > MAX_TILES:
        raise ToolError("Map would need too many tiles; reduce width/height or zoom.")

    template = TILE_STYLES.get(style, TILE_STYLES["streets"])
    canvas = Image.new("RGB", (width, height), (232, 233, 235))
    async with _client() as client:
        tasks = [
            _fetch_tile(client, template, zoom, tx, ty)
            for ty in range(tile_y0, tile_y1 + 1)
            for tx in range(tile_x0, tile_x1 + 1)
        ]
        tiles = await asyncio.gather(*tasks)
    index = 0
    fetched = 0
    for ty in range(tile_y0, tile_y1 + 1):
        for tx in range(tile_x0, tile_x1 + 1):
            data = tiles[index]
            index += 1
            if not data:
                continue
            try:
                tile = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception:  # noqa: BLE001 - skip corrupt tile
                continue
            fetched += 1
            canvas.paste(tile, (int(tx * TILE_SIZE - origin_x), int(ty * TILE_SIZE - origin_y)))
    if fetched == 0:
        raise ToolError("Could not download any map tiles (network blocked?). Try again or use an embed instead.")

    pixel_markers: List[Dict[str, Any]] = []
    for point, (px, py) in zip(points, projected):
        pixel_markers.append({**point, "px": round(px - origin_x), "py": round(py - origin_y)})

    if draw_route or draw_markers:
        drawer = ImageDraw.Draw(canvas)
        if draw_route and len(pixel_markers) > 1:
            path = [(m["px"], m["py"]) for m in pixel_markers]
            drawer.line(path, fill=(79, 70, 229), width=4, joint="curve")
        if draw_markers:
            for m in pixel_markers:
                r = 7
                drawer.ellipse((m["px"] - r, m["py"] - r, m["px"] + r, m["py"] + r), fill=(224, 49, 49), outline=(255, 255, 255), width=2)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), pixel_markers, zoom


def _data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


def _stable_id(payload: bytes) -> str:
    """Content-addressed id so identical assets dedupe across turns and restarts."""
    return hashlib.sha1(payload).hexdigest()[:16]


def _image_patch(
    *,
    file_id: str,
    file: CanvasFile,
    primitive_id: str,
    x: Optional[float],
    y: Optional[float],
    width: float,
    height: float,
    frame: Optional[str],
    caption: Optional[str],
) -> CanvasPatch:
    primitives = []
    if x is not None and y is not None:
        primitives.append(
            ImagePrimitive(
                kind="image", id=primitive_id, assetId=file_id, x=x, y=y, width=width, height=height,
                caption=caption, frame=frame,
            )
        )
    return CanvasPatch(files={file_id: file}, primitives=primitives)


# --------------------------------------------------------------------------- handlers


async def _fetch_map(args: FetchMapArgs, context: ToolContext) -> ToolResult:
    style = args.style
    if style == "auto":
        style = "dark" if context.theme == "dark" else "light"
    points = await resolve_markers(args.markers)
    png, pixel_markers, zoom = await render_static_map(
        points,
        width=args.width,
        height=args.height,
        zoom=args.zoom,
        style=style,
        draw_route=args.draw_route,
        draw_markers=args.draw_markers,
    )
    file_id = "map-" + _stable_id(png)
    file = CanvasFile(
        mimeType="image/png",
        dataURL=_data_url("image/png", png),
        created=int(time.time() * 1000),
        source=f"{style} tiles z{zoom}; {ATTRIBUTION}",
    )
    patch = _image_patch(
        file_id=file_id, file=file, primitive_id=args.id, x=args.x, y=args.y,
        width=args.width, height=args.height, frame=args.frame, caption=args.caption or ATTRIBUTION,
    )
    placed = args.x is not None and args.y is not None
    for marker in pixel_markers:
        if placed:
            marker["sceneX"] = round(args.x + marker["px"])  # type: ignore[operator]
            marker["sceneY"] = round(args.y + marker["py"])  # type: ignore[operator]
    return ToolResult(
        content={
            "assetId": file_id,
            "imagePrimitiveId": args.id if placed else None,
            "placedAt": {"x": args.x, "y": args.y, "width": args.width, "height": args.height} if placed else None,
            "zoom": zoom,
            "markers": pixel_markers,
            "hint": (
                "Place pin primitives at each marker's sceneX/sceneY (they are the exact map positions) "
                "and connect them with route primitives."
                if placed
                else "Call draw with an image primitive using assetId, then place pins at x+px / y+py."
            ),
            "attribution": ATTRIBUTION,
        },
        patch=patch,
        summary=f"Fetched a {style} map (zoom {zoom}) around {', '.join(m['name'] for m in points[:4])}"
        + ("…" if len(points) > 4 else ""),
    )


async def _geocode(args: GeocodeArgs, context: ToolContext) -> ToolResult:
    results = []
    for place in args.places:
        try:
            lat, lon, display = await geocode(place)
            results.append({"place": place, "lat": lat, "lon": lon, "resolved": display})
        except ToolError as exc:
            results.append({"place": place, "error": str(exc)})
        await asyncio.sleep(0.2)
    return ToolResult(content={"results": results}, summary=f"Geocoded {len(args.places)} place(s)")


async def _fetch_image(args: FetchImageArgs, context: ToolContext) -> ToolResult:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ToolError("Pillow is required for image tools.") from exc
    async with _client(timeout=30.0) as client:
        try:
            response = await client.get(args.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"Could not download image: {exc.__class__.__name__}") from exc
    mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        raise ToolError(f"URL did not return an image (content-type {mime or 'unknown'}).")
    if len(response.content) > MAX_IMAGE_BYTES:
        raise ToolError("Image is larger than 6 MB; pick a smaller one.")
    if mime == "image/svg+xml":
        natural_w, natural_h = 400.0, 300.0
    else:
        try:
            with Image.open(io.BytesIO(response.content)) as image:
                natural_w, natural_h = float(image.width), float(image.height)
        except Exception as exc:  # noqa: BLE001
            raise ToolError("Downloaded file is not a decodable image.") from exc
    width = args.width or min(natural_w, 480.0)
    height = width * natural_h / natural_w if natural_w else width * 0.75
    file_id = "img-" + _stable_id(response.content)
    file = CanvasFile(mimeType=mime, dataURL=_data_url(mime, response.content), created=int(time.time() * 1000), source=args.url)
    patch = _image_patch(
        file_id=file_id, file=file, primitive_id=args.id, x=args.x, y=args.y, width=width, height=height,
        frame=args.frame, caption=args.caption,
    )
    return ToolResult(
        content={"assetId": file_id, "width": round(width), "height": round(height), "placed": args.x is not None},
        patch=patch,
        summary=f"Fetched image {args.url.split('/')[-1][:40]}",
    )


async def _route_info(args: RouteInfoArgs, context: ToolContext) -> ToolResult:
    points = await resolve_markers(args.waypoints)
    profile = {"driving": "driving", "walking": "foot", "cycling": "bike"}[args.profile]
    coords = ";".join(f"{p['lon']},{p['lat']}" for p in points)
    async with _client() as client:
        try:
            response = await client.get(f"{OSRM_URL}/route/v1/{profile}/{coords}", params={"overview": "false", "steps": "false"})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolError(f"Routing failed: {exc.__class__.__name__}") from exc
    routes = data.get("routes") or []
    if not routes:
        raise ToolError("No route found between those waypoints (the routing service covers roads only).")
    legs = []
    for leg, start, end in zip(routes[0].get("legs", []), points, points[1:]):
        legs.append({
            "from": start["name"], "to": end["name"],
            "distanceKm": round(leg["distance"] / 1000, 1),
            "durationMin": round(leg["duration"] / 60),
        })
    return ToolResult(
        content={
            "profile": args.profile,
            "totalDistanceKm": round(routes[0]["distance"] / 1000, 1),
            "totalDurationMin": round(routes[0]["duration"] / 60),
            "legs": legs,
            "note": "Road routing only; trains/flights are not covered. Great-circle distance is fine for flights.",
        },
        summary=f"Looked up a {args.profile} route with {len(legs)} leg(s)",
    )


FETCH_MAP_TOOL = Tool(
    name="fetch_map",
    description=(
        "Render a real map (OpenStreetMap tiles) fitted around the given places and add it to the board as an image. "
        "Returns exact scene coordinates for each marker so you can layer pins, routes and notes on top. "
        "Use this whenever the user mentions places, trips, geography or 'a map'. Never hand-draw geography."
    ),
    args_model=FetchMapArgs,
    handler=_fetch_map,
    mutates_canvas=True,
)

GEOCODE_TOOL = Tool(
    name="geocode",
    description="Look up latitude/longitude for place names (OpenStreetMap Nominatim).",
    args_model=GeocodeArgs,
    handler=_geocode,
)

FETCH_IMAGE_TOOL = Tool(
    name="fetch_image",
    description=(
        "Download an https image (e.g. a Wikimedia Commons photo or a public diagram) and place it on the board. "
        "Only use URLs you are confident exist; the tool verifies the download."
    ),
    args_model=FetchImageArgs,
    handler=_fetch_image,
    mutates_canvas=True,
)

ROUTE_INFO_TOOL = Tool(
    name="route_info",
    description="Real road distance and travel time between waypoints (OSRM). Use for driving/walking legs instead of guessing.",
    args_model=RouteInfoArgs,
    handler=_route_info,
)

ASSET_TOOLS = [FETCH_MAP_TOOL, GEOCODE_TOOL, FETCH_IMAGE_TOOL, ROUTE_INFO_TOOL]
