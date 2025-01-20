from manim import *
import numpy as np


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
        y_max = max(self.y_values)
        y_padding = y_max * 0.2

        # Create axes with adjusted ranges and position
        axes = Axes(
            x_range=[0, len(self.x_values), 1],  # Start from 0
            y_range=[0, y_max + y_padding, y_max / 5],
            axis_config={"include_tip": True, "tip_width": 0.2, "tip_height": 0.2},
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


def render_chart(x_values, y_values, x_label, y_label, title, filename):
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


# Example usage
if __name__ == "__main__":
    # Sample data
    categories = ["A", "B", "C", "D", "E"]
    values = [4, 8, 2, 6, 5]

    # Configure scene settings
    config.pixel_height = 720
    config.pixel_width = 1280
    config.frame_height = 8
    config.frame_width = 14

    scene = BarChartAnimation(
        x_values=categories,
        y_values=values,
        x_label="Categories",
        y_label="Values",
        title="Bar Chart",
    )
    scene.render()
