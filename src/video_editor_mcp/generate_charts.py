from manim import *
import numpy as np

import sys
import json
import os
from contextlib import redirect_stdout, redirect_stderr


class LineGraphAnimation(Scene):
    def __init__(
        self,
        x_values=None,
        y_values=None,
        x_label="X-Axis",
        y_label="Y-Axis",
        title="Graph",
    ):
        super().__init__()
        # Default values if none provided
        self.x_values = x_values if x_values is not None else list(range(6))
        self.y_values = y_values if y_values is not None else [1, 4, 2, 8, 5, 7]
        self.x_label = x_label
        self.y_label = y_label
        self.title = title

        # Validate input
        if len(self.x_values) != len(self.y_values):
            raise ValueError("X and Y value lists must be the same length")

    def create_axes(self):
        # Calculate appropriate ranges for y-axis
        y_min, y_max = min(self.y_values), max(self.y_values)
        y_padding = (y_max - y_min) * 0.1  # 10% padding

        # Store original x values and create numerical mapping if needed
        self.original_x_values = self.x_values
        if not all(isinstance(x, (int, float)) for x in self.x_values):
            self.x_values = list(range(len(self.x_values)))

        x_min, x_max = min(self.x_values), max(self.x_values)
        x_padding = (x_max - x_min) * 0.1 if isinstance(x_min, (int, float)) else 0.5

        # Adjust ranges to start at 0 for x-axis
        x_range = [0, x_max + x_padding, (x_max - x_min) / 10 if x_max != x_min else 1]
        y_range = [0, y_max + y_padding, (y_max - y_min) / 10 if y_max != y_min else 1]

        axes = Axes(
            x_range=x_range,
            y_range=y_range,
            axis_config={
                "include_tip": True,
                "tick_size": 0.1,
                "color": self.black,
            },
            x_axis_config={
                "include_numbers": isinstance(x_min, (int, float)),
                "decimal_number_config": {"num_decimal_places": 1, "color": self.black},
            },
            y_axis_config={
                "include_numbers": True,
                "decimal_number_config": {"num_decimal_places": 1, "color": self.black},
            },
            tips=True,
            x_length=10,
            y_length=6,
        )

        # Ensure axes start at origin
        axes.move_to(ORIGIN)
        axes.to_corner(DOWN + LEFT)

        return axes

    def create_labels(self, axes):
        # Create axis labels
        x_label = Text(self.x_label, font_size=24).next_to(axes.x_axis, DOWN)
        y_label = Text(self.y_label, font_size=24).next_to(axes.y_axis, LEFT)

        # Create title
        title = Text(self.title, font_size=36).to_edge(UP, buff=-0.25)

        return x_label, y_label, title

    def create_data_points(self, axes):
        # Convert data points to coordinates
        points = [
            axes.coords_to_point(x, y) for x, y in zip(self.x_values, self.y_values)
        ]

        # Create the graph line
        graph = VMobject()
        graph.set_points_smoothly([*points])
        graph.set_color("#87c2a5")

        # Create dots for each point
        dots = VGroup(*[Dot(point, color="#525893") for point in points])

        # Create labels for data points
        value_labels = VGroup(
            *[
                Text(f"({x}, {y})", font_size=16, color=self.black).next_to(dot, UP)
                for x, y, dot in zip(self.x_values, self.y_values, dots)
            ]
        )

        return graph, dots, value_labels

    def construct(self):
        # Create the elements
        self.camera.frame_height = 10
        self.camera.frame_width = 17
        self.camera.background_color = "#ece6e2"
        self.camera.frame_center = [-1.3, 0, 0]
        self.black = "#343434"
        Text.set_default(font="Helvetica", color=self.black)
        axes = self.create_axes()
        x_label, y_label, title = self.create_labels(axes)
        graph, dots, value_labels = self.create_data_points(axes)

        # Initial animations
        self.play(Write(title))
        self.play(Create(axes), Write(x_label), Write(y_label))

        # Graph creation animation
        self.play(Create(graph), run_time=2)

        # Animate dots appearing
        self.play(Create(dots))

        # Animate value labels
        self.play(Write(value_labels))

        # Sequential point highlighting
        for dot, label in zip(dots, value_labels):
            self.play(
                dot.animate.scale(1.5).set_color("#e07a5f"),
                label.animate.scale(1.2),
                rate_func=there_and_back,
                run_time=0.5,
            )

        # Final pause
        self.wait(2)


class BarChartAnimation(Scene):
    def __init__(
        self,
        x_values=None,
        y_values=None,
        x_label="Categories",
        y_label="Values",
        title="Bar Chart",
    ):
        super().__init__()
        self.x_values = x_values if x_values is not None else ["A", "B", "C", "D", "E"]
        self.y_values = y_values if y_values is not None else [4, 8, 2, 6, 5]
        self.x_label = x_label
        self.y_label = y_label
        self.title = title
        self.bar_color = BLUE
        self.bar_width = 0.5

    def construct(self):
        # Calculate ranges
        self.camera.frame_height = 10
        self.camera.frame_width = 17
        self.camera.background_color = "#ece6e2"
        self.camera.frame_center = [-1.3, 0, 0]
        self.black = "#343434"

        y_max = max(self.y_values)
        y_padding = y_max * 0.2
        Text.set_default(font="Helvetica", color=self.black)
        # Create axes with adjusted ranges and position
        axes = Axes(
            x_range=[0, len(self.x_values), 1],  # Start from 0
            y_range=[0, y_max + y_padding, y_max / 5],
            axis_config={
                "include_tip": True,
                "tip_width": 0.2,
                "tip_height": 0.2,
                "color": BLACK,
            },
            x_length=8,
            y_length=6,
        ).to_corner(DL, buff=1)  # Align to bottom left with padding

        # Shift the entire axes right to create space after y-axis
        axes.shift(RIGHT * 1)

        # Create bars using axes coordinates
        bars = VGroup()
        labels = VGroup()

        for i, value in enumerate(self.y_values):
            # Calculate bar position and height
            bar_bottom = axes.c2p(i + 0.5, 0)  # Add 0.5 to center on tick marks
            bar_top = axes.c2p(i + 0.5, value)
            bar_height = bar_top[1] - bar_bottom[1]

            bar = Rectangle(
                width=self.bar_width,
                height=bar_height,
                color=self.bar_color,
                fill_opacity=0.8,
            ).move_to(bar_bottom, aligned_edge=DOWN)

            # Create value label
            label = Text(f"{value}", font_size=24)
            label.next_to(bar, UP, buff=0.1)

            bars.add(bar)
            labels.add(label)

        # Create axis labels
        x_labels = VGroup()
        for i, label_text in enumerate(self.x_values):
            label = Text(label_text, font_size=24)
            label.next_to(
                axes.c2p(i + 0.5, 0), DOWN, buff=0.5
            )  # Add 0.5 to align with bars
            x_labels.add(label)

        y_label = Text(self.y_label, font_size=24).next_to(axes.y_axis, LEFT, buff=0.5)
        x_axis_label = Text(self.x_label, font_size=24).next_to(
            axes.x_axis, DOWN, buff=1.5
        )
        title = Text(self.title, font_size=36).to_edge(UP, buff=0.5)

        # Animations
        self.play(Create(axes))
        self.play(Write(title))
        self.play(Write(VGroup(y_label, x_axis_label)))
        self.play(Write(x_labels))

        # Animate each bar appearing
        for bar, label in zip(bars, labels):
            self.play(GrowFromEdge(bar, DOWN), Write(label), run_time=0.5)

        # Highlight bars
        for bar, label in zip(bars, labels):
            self.play(
                bar.animate.set_color(RED),
                label.animate.scale(1.2),
                rate_func=there_and_back,
                run_time=0.3,
            )

        self.wait()


def render_bar_chart(
    x_values, y_values, x_label, y_label, title, filename="bar_chart.mp4"
):
    config.verbosity = "ERROR"
    config.pixel_height = 720
    config.pixel_width = 1280
    config.frame_height = 8
    config.frame_width = 14
    config.output_file = filename  # Optional: specify output filename
    config.preview = True  # Opens the video after rendering
    config.quality = "medium_quality"  # or "high_quality", "production_quality"

    scene = BarChartAnimation(
        x_values=x_values,
        y_values=y_values,
        x_label=x_label,
        y_label=y_label,
        title=title,
    )
    scene.render()
    return


# Example usage
if __name__ == "__main__":
    # Sample data
    input_json_file = sys.argv[1]
    chart_type = sys.argv[2]
    with open(input_json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "x_values" not in data or "y_values" not in data:
        raise ValueError("Invalid JSON data format")

    x_values = data["x_values"]
    y_values = data["y_values"]
    x_label = data["x_label"] or "Categories"
    y_label = data["y_label"] or "Values"
    title = data["title"]
    filename = data["filename"]

    config.verbosity = "ERROR"
    config.pixel_height = 720
    config.pixel_width = 1280
    config.frame_height = 8
    config.frame_width = 14
    config.output_file = filename
    config.preview = True
    config.quality = "medium_quality"
    # Configure scene settings

    if chart_type == "bar":
        scene = BarChartAnimation(
            x_values=x_values,
            y_values=y_values,
            x_label=x_label,
            y_label=y_label,
            title=title,
        )
    elif chart_type == "line":
        scene = LineGraphAnimation(
            x_values=x_values,
            y_values=y_values,
            x_label=x_label,
            y_label=y_label,
            title=title,
        )
    else:
        raise ValueError("Invalid chart type. Use 'bar' or 'line'")

    scene.render()
