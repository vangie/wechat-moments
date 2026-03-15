"""Fixture collector for recording UI automation steps."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .annotate import annotate_screenshot

if TYPE_CHECKING:
    from .adb import ADB
    from .calibration import UIProfile


@dataclass
class StepResult:
    """Result of a single step execution."""

    phase: int
    step: int
    name: str
    action: str
    coords: tuple[int, int] | None
    swipe_end: tuple[int, int] | None
    dir_name: str


def parse_steps(steps_str: str | None) -> tuple[int | None, int | None]:
    """
    Parse steps range string into (start, end) tuple.

    Examples:
        "2-"  -> (2, None)   # from step 2 to end
        "-5"  -> (None, 5)   # from start to step 5
        "2-5" -> (2, 5)      # steps 2 to 5
        "3"   -> (3, 3)      # only step 3
        None  -> (None, None) # all steps
    """
    if not steps_str:
        return None, None
    if "-" not in steps_str:
        n = int(steps_str)
        return n, n
    parts = steps_str.split("-", 1)
    start = int(parts[0]) if parts[0] else None
    end = int(parts[1]) if parts[1] else None
    return start, end


class FixtureCollector:
    """
    Collector for recording UI automation steps with screenshots.

    Each step captures:
    - Raw screenshot
    - Annotated screenshot with action indicators (tap circles, swipe arrows)
    """

    def __init__(
        self,
        adb: ADB,
        output_dir: Path,
        profile: UIProfile,
        step_start: int | None = None,
        step_end: int | None = None,
    ):
        self._adb = adb
        self._output = output_dir
        self._profile = profile
        self._phase = 0
        self._phase_name = ""
        self._step = 0
        self._step_start = step_start
        self._step_end = step_end
        self._results: list[StepResult] = []

    def set_phase(self, phase: int, name: str) -> None:
        """Start a new phase, resetting step counter."""
        self._phase = phase
        self._phase_name = name
        self._step = 0
        click.secho(f"\n=== Phase {phase}: {name} ===", fg="cyan")

    def _should_execute(self) -> bool:
        """Check if current step should be executed based on step range."""
        if self._step_start is not None and self._step < self._step_start:
            return False
        if self._step_end is not None and self._step > self._step_end:
            return False
        return True

    def tap(self, x: int, y: int, name: str, wait: float = 0.8) -> None:
        """Execute tap action and capture screenshots."""
        self._step += 1
        if self._should_execute():
            self._execute("tap", name, coords=(x, y), wait=wait)

    def long_press(self, x: int, y: int, name: str, wait: float = 1.5) -> None:
        """Execute long press action and capture screenshots."""
        self._step += 1
        if self._should_execute():
            self._execute("long_press", name, coords=(x, y), wait=wait)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, name: str, wait: float = 0.5) -> None:
        """Execute swipe action and capture screenshots."""
        self._step += 1
        if self._should_execute():
            self._execute("swipe", name, coords=(x1, y1), swipe_end=(x2, y2), wait=wait)

    def wait(self, name: str, duration: float) -> None:
        """Wait and capture screenshot (no action)."""
        self._step += 1
        if self._should_execute():
            self._execute("wait", name, wait=duration)

    def input_text(self, text: str, name: str, wait: float = 1.0) -> None:
        """Input text via IME and capture screenshot."""
        self._step += 1
        if self._should_execute():
            self._execute("input", name, input_text=text, wait=wait)

    def back(self, name: str, wait: float = 1.0) -> None:
        """Press back button and capture screenshot."""
        self._step += 1
        if self._should_execute():
            self._execute("back", name, wait=wait)

    def _execute(
        self,
        action: str,
        name: str,
        coords: tuple[int, int] | None = None,
        swipe_end: tuple[int, int] | None = None,
        input_text: str | None = None,
        wait: float = 0.8,
    ) -> None:
        """Capture screenshots first, then execute action and wait."""
        step_id = f"P{self._phase}S{self._step:02d}"
        coord_str = ""
        if coords:
            coord_str = f" at ({coords[0]},{coords[1]})"
        click.echo(f"[{step_id}] {name}{coord_str}")

        # For "wait" action: wait first, then capture (to show loaded UI)
        # For other actions: capture first, then execute (to show where we clicked)
        if action == "wait":
            time.sleep(wait)
            dir_name = self._capture(step_id, name, action, coords, swipe_end)
        else:
            # Capture screenshots BEFORE executing action
            dir_name = self._capture(step_id, name, action, coords, swipe_end)

            # Execute the action
            if action == "tap" and coords:
                self._adb.tap(*coords)
            elif action == "long_press" and coords:
                self._adb.long_press(*coords)
            elif action == "swipe" and coords and swipe_end:
                self._adb.swipe(*coords, *swipe_end)
            elif action == "back":
                self._adb.press_back()
            elif action == "input" and input_text:
                self._adb.input_text_adbkeyboard(input_text)

            # Wait for UI to settle after action
            time.sleep(wait)

        # Record result
        self._results.append(
            StepResult(
                phase=self._phase,
                step=self._step,
                name=name,
                action=action,
                coords=coords,
                swipe_end=swipe_end,
                dir_name=dir_name,
            )
        )

    def _capture(
        self,
        step_id: str,
        name: str,
        action: str,
        coords: tuple[int, int] | None,
        swipe_end: tuple[int, int] | None,
    ) -> str:
        """Capture raw and annotated screenshots."""
        import shutil

        # Create safe directory name
        safe_name = re.sub(r"[^\w\-]", "_", name.lower())[:30]
        dir_name = f"{step_id}_{action}_{safe_name}"
        d = self._output / dir_name

        # Remove any existing directories with the same step_id prefix but different name
        for existing in self._output.glob(f"{step_id}_*"):
            if existing.is_dir() and existing.name != dir_name:
                shutil.rmtree(existing)

        d.mkdir(parents=True, exist_ok=True)

        # Save raw screenshot
        raw_path = d / "screenshot.png"
        self._adb.screenshot_to_file(raw_path)

        # Save annotated screenshot
        annotated_path = d / "annotated.png"
        try:
            annotate_screenshot(raw_path, annotated_path, action, coords, swipe_end)
        except Exception as e:
            click.echo(f"       Warning: annotation failed ({e})")

        click.echo(f"       → {dir_name}/")
        return dir_name

    def get_results(self) -> list[StepResult]:
        """Return all recorded step results."""
        return self._results

    def print_summary(self) -> None:
        """Print summary of all captured fixtures."""
        click.secho(f"\n=== Fixtures saved to {self._output}/ ===", fg="green")
        click.echo("\nDirectories:")
        for d in sorted(self._output.iterdir()):
            if d.is_dir():
                files = list(d.iterdir())
                click.echo(f"  {d.name}/  ({len(files)} files)")
