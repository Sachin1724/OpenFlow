"""Island: contents always fit the shape, only one capsule shows at a time, the live caption types in steadily."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication([])
from openflow.ui.floating_pill import FloatingPill
from openflow.ui.island import IslandPill, CapsuleRouter, DIMS

ARGS = dict(current_mic_name="Mic", current_language="en", current_model="base", hide_when_idle=False, follow_mouse_screen=True)


def test_contents_fit_the_shape_for_any_width_and_height():
    isl = IslandPill(**ARGS)
    isl.activate()
    for wf in (0.5, 1.0, 2.0):
        for hf in (0.5, 1.0, 2.0):
            isl.set_capsule_size(wf, hf, False)
            for state in ("listen", "write", "done"):
                isl._go(state)
                w, h, _ = isl._to
                base_w, base_h, _ = DIMS[state]
                # contents are drawn scaled by the smaller factor: they must fit inside the shape
                assert base_w * isl._sk <= w + 0.5 and base_h * isl._sk <= h + 0.5, (wf, hf, state)
    isl.deactivate()


def test_size_change_retargets_the_shape_while_showing():
    isl = IslandPill(**ARGS)
    isl.activate()
    isl.show_listening()
    for hf in (1.0, 1.3, 1.6):  # a slider drag
        isl.set_capsule_size(1.0, hf, False)
    assert abs(isl._to[1] - DIMS["listen"][1] * 1.6) < 0.5  # the shape follows the last tick
    isl.deactivate()


def test_only_one_capsule_ever_shows():
    pill = FloatingPill(capsule_style="compact", **ARGS)
    isl = IslandPill(**ARGS)
    r = CapsuleRouter(pill, isl, "island", True)
    r.set_capsule_size(1.2, 1.2, True)  # re-laying out the hidden capsule must not show it
    r.show_message("hello", 300)
    QTest.qWait(300)
    assert isl.isVisible() and not pill.isVisible()
    r.set_capsule_style("compact")  # pending island timers must not bring it back
    QTest.qWait(1800)
    assert pill.isVisible() and not isl.isVisible()
    r.set_capsule_style("island")
    QTest.qWait(300)
    assert isl.isVisible()
    pill.show()  # anything that shows the hidden capsule is undone
    QTest.qWait(100)
    assert not pill.isVisible()
    r.set_capsule_style("standard")
    isl.deactivate()
    pill.hide()


def test_island_caption_types_in_below_the_island():
    isl = IslandPill(**ARGS)
    isl.activate()
    isl.show_listening()
    isl.update_realtime_text("hello there how")
    isl.update_realtime_text("there how are you")  # the next window overlaps the last
    b = isl.caption_bubble
    assert b._text == "hello there how are you" and isl.caption_below
    QTest.qWait(120)
    assert 0 < b._shown < len(b._text)  # typing in, not popped in whole
    QTest.qWait(1500)
    assert int(b._shown) == len(b._text)
    isl.show_processing()
    QTest.qWait(400)
    assert not b.isVisible() or b.windowOpacity() < 0.1
    isl.deactivate()
