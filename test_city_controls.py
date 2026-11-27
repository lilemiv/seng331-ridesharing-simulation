"""Timer lifecycle regressions run without a graphical display."""

import unittest
from unittest.mock import Mock

from city_visualization import CityViewer


class AnimationTimerTests(unittest.TestCase):
    def viewer(self):
        viewer = CityViewer.__new__(CityViewer)
        viewer.root = Mock()
        viewer.canvas = Mock()
        viewer.animation_after_id = "animation-token"
        viewer.after_id = "replay-token"
        viewer.play_button = Mock()
        viewer.playing = True
        return viewer

    def test_pause_cancels_both_timer_types(self):
        viewer = self.viewer()
        viewer.toggle()
        viewer.canvas.after_cancel.assert_called_once_with("animation-token")
        viewer.root.after_cancel.assert_called_once_with("replay-token")
        self.assertIsNone(viewer.animation_after_id)
        self.assertIsNone(viewer.after_id)

    def test_close_cancels_animation_before_destroying_widgets(self):
        viewer = self.viewer()
        calls = Mock()
        calls.attach_mock(viewer.canvas.after_cancel, "cancel_animation")
        calls.attach_mock(viewer.root.destroy, "destroy")
        viewer.close()
        self.assertEqual([c[0] for c in calls.mock_calls], ["cancel_animation", "destroy"])

    def test_stopping_animation_twice_is_safe(self):
        viewer = self.viewer()
        viewer.stop_animation()
        viewer.stop_animation()
        viewer.canvas.after_cancel.assert_called_once_with("animation-token")
