"""Screenshot annotation utilities for fixture collection."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def annotate_screenshot(
    input_path: Path,
    output_path: Path,
    action: str,
    coords: tuple[int, int] | None,
    swipe_end: tuple[int, int] | None = None,
    circle_radius: int = 40,
    tap_color: tuple[int, int, int, int] = (255, 0, 0, 180),
    swipe_color: tuple[int, int, int, int] = (0, 100, 255, 200),
    show_grid: bool = True,
) -> None:
    """
    Annotate a screenshot with action indicators and optional grid.

    For tap/long_press: draws a circle at the tap location with coordinates.
    For swipe: draws a line with arrow from start to end with coordinates.
    """
    img = Image.open(input_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = img.size

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
        grid_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except OSError:
        font = ImageFont.load_default()
        grid_font = font

    # Draw grid and rulers
    if show_grid:
        _draw_grid(draw, width, height, grid_font)

    if action in ("tap", "long_press") and coords:
        x, y = coords
        # Draw circle outline
        draw.ellipse(
            [
                x - circle_radius,
                y - circle_radius,
                x + circle_radius,
                y + circle_radius,
            ],
            outline=tap_color[:3],
            width=4,
        )
        # Draw crosshair
        cross_size = circle_radius // 2
        draw.line([(x - cross_size, y), (x + cross_size, y)], fill=tap_color[:3], width=2)
        draw.line([(x, y - cross_size), (x, y + cross_size)], fill=tap_color[:3], width=2)

        # Draw coordinate text with background
        text = f"({x}, {y})"
        text_x = x + circle_radius + 10
        text_y = y - 16
        # Text background
        bbox = draw.textbbox((text_x, text_y), text, font=font)
        draw.rectangle(
            [bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2],
            fill=(255, 255, 255, 220),
        )
        draw.text((text_x, text_y), text, fill=tap_color[:3], font=font)

        # For long_press, add a second outer ring
        if action == "long_press":
            draw.ellipse(
                [
                    x - circle_radius - 10,
                    y - circle_radius - 10,
                    x + circle_radius + 10,
                    y + circle_radius + 10,
                ],
                outline=tap_color[:3],
                width=2,
            )

    elif action == "swipe" and coords and swipe_end:
        x1, y1 = coords
        x2, y2 = swipe_end

        # Draw line
        draw.line([(x1, y1), (x2, y2)], fill=swipe_color[:3], width=4)

        # Draw start circle
        draw.ellipse(
            [x1 - 15, y1 - 15, x1 + 15, y1 + 15],
            fill=swipe_color,
            outline=swipe_color[:3],
        )

        # Draw end arrow
        _draw_arrowhead(draw, x1, y1, x2, y2, swipe_color[:3], size=20)

        # Draw coordinate labels
        start_text = f"({x1},{y1})"
        end_text = f"({x2},{y2})"

        # Start label
        bbox = draw.textbbox((x1, y1 - 40), start_text, font=font)
        draw.rectangle(
            [bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2],
            fill=(255, 255, 255, 220),
        )
        draw.text((x1, y1 - 40), start_text, fill=swipe_color[:3], font=font)

        # End label
        bbox = draw.textbbox((x2, y2 + 20), end_text, font=font)
        draw.rectangle(
            [bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2],
            fill=(255, 255, 255, 220),
        )
        draw.text((x2, y2 + 20), end_text, fill=swipe_color[:3], font=font)

    result = Image.alpha_composite(img, overlay)
    result.convert("RGB").save(output_path)


def _draw_grid(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    font: ImageFont.FreeTypeFont,
    grid_spacing: int = 200,
    grid_color: tuple[int, int, int, int] = (0, 200, 0, 120),
    label_color: tuple[int, int, int] = (0, 150, 0),
) -> None:
    """Draw grid lines and rulers on the image."""
    # Draw vertical grid lines and X-axis labels
    for x in range(0, width, grid_spacing):
        # Grid line - more visible green
        draw.line([(x, 0), (x, height)], fill=grid_color, width=2)
        # X-axis label at top
        if x > 0:
            label = str(x)
            bbox = draw.textbbox((x, 5), label, font=font)
            # White background for readability
            draw.rectangle(
                [bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 4],
                fill=(255, 255, 255, 230),
            )
            draw.text((x + 4, 5), label, fill=label_color, font=font)

    # Draw horizontal grid lines and Y-axis labels
    for y in range(0, height, grid_spacing):
        # Grid line
        draw.line([(0, y), (width, y)], fill=grid_color, width=2)
        # Y-axis label at left
        if y > 0:
            label = str(y)
            bbox = draw.textbbox((5, y), label, font=font)
            draw.rectangle(
                [bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 4],
                fill=(255, 255, 255, 230),
            )
            draw.text((5, y + 4), label, fill=label_color, font=font)

    # Draw minor tick marks every 100px - thicker and more visible
    tick_spacing = 100
    tick_length = 20
    tick_color = (0, 180, 0, 180)
    for x in range(tick_spacing, width, tick_spacing):
        if x % grid_spacing != 0:
            draw.line([(x, 0), (x, tick_length)], fill=tick_color, width=2)
    for y in range(tick_spacing, height, tick_spacing):
        if y % grid_spacing != 0:
            draw.line([(0, y), (tick_length, y)], fill=tick_color, width=2)


def _draw_arrowhead(
    draw: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int],
    size: int = 20,
) -> None:
    """Draw an arrowhead at the end of a line."""
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    arrow_angle = math.pi / 6  # 30 degrees

    # Calculate arrowhead points
    left_x = x2 - size * math.cos(angle - arrow_angle)
    left_y = y2 - size * math.sin(angle - arrow_angle)
    right_x = x2 - size * math.cos(angle + arrow_angle)
    right_y = y2 - size * math.sin(angle + arrow_angle)

    draw.polygon(
        [(x2, y2), (left_x, left_y), (right_x, right_y)],
        fill=color,
    )
