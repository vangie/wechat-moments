from datetime import datetime

import click

from . import __version__
from .adb import ADB
from .config import DEBUG_BASE_DIR
from .preview import cleanup_expired_archive, cleanup_expired_staging, prepare_post
from .submit import execute_submit


@click.group()
@click.version_option(__version__, prog_name="wx-pyq")
def main() -> None:
    """WeChat Moments poster via ADB automation."""


@main.command()
@click.argument("text", default="")
@click.option(
    "-i", "--image", "images", multiple=True, help="Image file path or URL (can repeat, max 9)"
)
@click.option("--no-preview", is_flag=True, help="Skip preview confirmation")
@click.option(
    "--debug", is_flag=True, help="Save debug screenshots to a timestamped dir under debug/"
)
def post(text: str, images: tuple[str, ...], no_preview: bool, debug: bool) -> None:
    """Prepare and post to WeChat Moments."""
    if not text and not images:
        raise click.UsageError("Provide TEXT and/or at least one --image/-i")

    click.echo("Preparing post...")
    prepared = prepare_post(text, list(images))
    post_id = prepared["post_id"]

    debug_dir = None
    if debug:
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        debug_dir = DEBUG_BASE_DIR / timestamp
        debug_dir.mkdir(parents=True, exist_ok=True)
        click.echo(f"Debug output: {debug_dir}")

    if not no_preview:
        click.echo(f"\nPreview image: {prepared['preview_path']}")
        click.echo(f"Text:          {text!r}")
        click.echo(f"Images:        {len(images)}")
        click.confirm("\nPost to WeChat Moments?", default=True, abort=True)

    click.echo("Posting...")
    try:
        result = execute_submit(post_id, debug_dir=debug_dir)
    except RuntimeError as e:
        if "No device connected" in str(e):
            click.secho(str(e), fg="red", err=True)
            raise SystemExit(1) from None
        raise

    if result["status"] == "success":
        click.secho("Posted successfully.", fg="green")
    elif result["status"] == "possibly_submitted":
        click.secho(f"Warning: {result['message']}", fg="yellow")
    else:
        click.secho(f"Failed: {result.get('error')}", fg="red", err=True)
        raise SystemExit(1)

    # Restart ADB server after posting to prevent stale transport on Honor/Huawei devices.
    # These devices' USB transport tends to break after intensive ADB operations (screenshots,
    # input events), causing subsequent 'adb devices' to return empty. Restarting the server
    # proactively ensures the next command can connect immediately.
    try:
        ADB(serial=None).restart_server()
    except Exception:
        pass  # Best-effort; don't fail the post because of this


@main.command()
def status() -> None:
    """Check ADB connection and WeChat status."""
    serials = ADB.get_connected_serials()
    if not serials:
        click.secho(
            "No device connected. Connect your phone via USB and run 'adb devices' to confirm it is listed.",
            fg="red",
        )
        raise SystemExit(1)
    for s in serials:
        adb = ADB(serial=s)
        wechat_installed = adb.is_app_installed("com.tencent.mm")
        adbkb_installed = adb.is_app_installed("com.android.adbkeyboard")
        click.echo(f"Device:          {s}")
        click.echo(f"WeChat:          {'installed' if wechat_installed else 'NOT installed'}")
        click.echo(f"ADBKeyboard:     {'installed' if adbkb_installed else 'NOT installed'}")


@main.command("collect-fixtures")
@click.option(
    "-o",
    "--output",
    "output_dir",
    default="tests/fsm/fixtures",
    show_default=True,
    help="Output directory for fixture files",
)
@click.option("--phase", type=int, default=None, help="Run specific phase only (1, 2, or 3)")
@click.option(
    "--steps",
    type=str,
    default=None,
    help="Step range: '2-' (from 2), '-5' (up to 5), '2-5' (2 to 5), '3' (only 3)",
)
def collect_fixtures(output_dir: str, phase: int | None, steps: str | None) -> None:
    """
    Connect to device and record screenshots for every FSM state.

    Covers both image+text path (short tap camera) and long-text path (long press camera).
    Each step captures raw and annotated screenshots with tap/swipe indicators.

    Examples:
        wx-pyq collect-fixtures                    # Run all phases
        wx-pyq collect-fixtures --phase 2         # Run phase 2 only
        wx-pyq collect-fixtures --phase 2 --steps 3-5  # Phase 2, steps 3-5
    """
    import time
    from pathlib import Path

    from .calibration import load_profile
    from .collector import FixtureCollector, parse_steps
    from .config import WECHAT_PACKAGE
    from .ime import ImeManager

    output = Path(output_dir)
    adb = ADB.auto_connect()

    click.echo("Waking up screen...")
    adb.wake_screen()

    # Ensure WeChat is in foreground
    if adb.get_foreground_package() != WECHAT_PACKAGE:
        click.echo("Starting WeChat...")
        adb.start_app(WECHAT_PACKAGE)
        if not adb.wait_for_package(WECHAT_PACKAGE, timeout=10.0):
            click.secho("ERROR: Failed to bring WeChat to foreground.", fg="red", err=True)
            raise SystemExit(1)
        time.sleep(1.0)

    # Load device profile
    profile = load_profile(adb.serial or "huawei_default")
    sw, sh = profile.screen_width, profile.screen_height
    click.echo(f"Screen: {sw}x{sh} (from profile)")

    # Parse step range
    step_start, step_end = parse_steps(steps)
    if steps:
        click.echo(f"Step range: {step_start or 'start'} to {step_end or 'end'}")

    # Create collector
    collector = FixtureCollector(
        adb=adb,
        output_dir=output,
        profile=profile,
        step_start=step_start,
        step_end=step_end,
    )

    # Get coordinates from profile
    cam_x, cam_y = profile.camera_coords()
    text_x, text_y = profile.compose_text_coords()
    long_text_x, long_text_y = profile.long_text_text_coords()
    discard_x, discard_y = profile.discard_abandon_coords()
    keep_x, keep_y = profile.discard_keep_coords()

    ime = ImeManager(adb)

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 1: Launch WeChat and navigate to Moments
    # ═══════════════════════════════════════════════════════════════════════════
    if phase is None or phase == 1:
        collector.set_phase(1, "Launch WeChat")

        # Force restart WeChat
        click.echo("Restarting WeChat to ensure clean state...")
        adb.force_stop(WECHAT_PACKAGE)
        time.sleep(1.0)

        # Start WeChat
        adb.start_app(WECHAT_PACKAGE)
        if not adb.wait_for_package(WECHAT_PACKAGE, timeout=20.0):
            click.secho("ERROR: WeChat never reached foreground.", fg="red", err=True)
            raise SystemExit(1)

        collector.wait("WeChat main screen", duration=3.0)

        # Navigate to Moments
        tab_x, tab_y = profile.tab_coords(2)
        collector.tap(tab_x, tab_y, "Tap Discover tab", wait=0.8)

        moments_x = sw // 2
        moments_y = 325  # Center of "朋友圈" row in Discover page
        collector.tap(moments_x, moments_y, "Tap Moments entry", wait=1.2)

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 2: Image+Text path (short tap camera → bottom sheet → album)
    # ═══════════════════════════════════════════════════════════════════════════
    if phase is None or phase == 2:
        collector.set_phase(2, "Image+Text Path")

        collector.tap(cam_x, cam_y, "Tap camera button", wait=0.8)

        album_x, album_y = profile.album_option_coords()
        collector.tap(album_x, album_y, "Tap album option", wait=1.2)

        # Switch to WeChatMCP album
        dropdown_x, dropdown_y = profile.album_dropdown_coords()
        collector.tap(dropdown_x, dropdown_y, "Tap album dropdown", wait=0.8)

        wechatmcp_x, wechatmcp_y = profile.album_wechatmcp_coords()
        collector.tap(wechatmcp_x, wechatmcp_y, "Select WeChatMCP album", wait=1.0)

        cell_x, cell_y = profile.album_cell_coords(0)
        collector.tap(cell_x, cell_y, "Select image 1 (row1 col1)", wait=0.5)

        cell_x, cell_y = profile.album_cell_coords(4)
        collector.tap(cell_x, cell_y, "Select image 5 (row2 col1)", wait=0.5)

        cell_x, cell_y = profile.album_cell_coords(5)
        collector.tap(cell_x, cell_y, "Select image 6 (row2 col2)", wait=0.5)

        done_x, done_y = profile.album_done_coords()
        collector.tap(done_x, done_y, "Tap done button", wait=1.2)

        collector.tap(text_x, text_y, "Tap text area", wait=1.0)

        # Input text
        ime.input_with_ime_switch("fixture image post")
        collector.wait("Text input complete", duration=1.0)

        # Tap back button (top-left) to trigger discard dialog
        collector.tap(50, 190, "Tap back button", wait=0.8)

        collector.tap(discard_x, discard_y, "Tap discard button", wait=0.8)

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 3: Long-text path (long press camera → long text compose)
    # ═══════════════════════════════════════════════════════════════════════════
    if phase is None or phase == 3:
        collector.set_phase(3, "Long-Text Path")

        # Long press camera to enter text-only compose
        collector.long_press(cam_x, cam_y, "Long press camera", wait=1.5)

        # Input text
        collector.tap(long_text_x, long_text_y, "Tap text area", wait=1.0)
        ime.input_with_ime_switch("fixture long text post")
        collector.wait("Text input complete", duration=1.0)

        # Exit and discard
        collector.tap(50, 200, "Tap back button", wait=1.5)
        collector.tap(discard_x, discard_y, "Tap discard button", wait=0.8)

    # ═══════════════════════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════════════════════
    collector.print_summary()
    click.echo("\nReview annotated.png files to verify tap coordinates are correct.")
    click.echo("If any step landed on the wrong screen, adjust profile ratios in profiles/.")


@main.command()
def cleanup() -> None:
    """Remove expired staging and archive directories."""
    s = cleanup_expired_staging()
    a = cleanup_expired_archive()
    click.echo(f"Removed {s} expired staging dirs, {a} expired archive dirs.")
