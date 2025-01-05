from manim import *
from manim.opengl import *

from pyglet.window import key


class CameraScene(Scene):
    def construct(self):
        self.camera_states = []

        self.interactive_embed()

    def on_key_press(self, symbol, modifiers):
        # + adds a new camera position to interpolate
        if symbol == key.PLUS:
            print("New position added!")
            self.camera_states.append(self.camera.copy())

        # P plays the animations, one by one
        elif symbol == key.P:
            print("Replaying!")
            for cam in self.camera_states:
                self.play(self.camera.animate.become(cam))

        super().on_key_press(symbol, modifiers)
