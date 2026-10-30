"""Dashboard: the mouse wheel scrolls the page and never edits a slider, combo or spin box under the cursor."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from database import Database
from config import load_config
import ui.main_window as mw
from ui.main_window import MainWindow

mw.save_config = lambda *_: None  # these tests drive real controls: never write the user's config

app = QApplication.instance() or QApplication([])


def wheel(widget, dy=-120):
    """Returns whether the control took the event (accepted) - an ignored wheel event goes on to the scroll area."""
    ev = QWheelEvent(QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)
    return ev.isAccepted()


def _val(c):
    return c.value() if hasattr(c, "value") else c.currentIndex()


def test_wheel_is_left_to_the_page_unless_focused():
    w = MainWindow(Database(":memory:"), dict(load_config()))
    w.resize(760, 560)
    w.show()
    w.select_page(4)  # Settings
    QTest.qWait(200)
    for ctrl in (w.opacity_slider, w.model_combo, w.capsule_style_combo, w.silence_spin):
        ctrl.clearFocus()
        before = _val(ctrl)
        assert not wheel(ctrl), f"{type(ctrl).__name__} kept the wheel event, so the page would not scroll"
        assert _val(ctrl) == before, f"{type(ctrl).__name__} changed on wheel without focus"
    # focused: the wheel edits the control as usual
    w.activateWindow()
    w.opacity_slider.setFocus()
    QTest.qWait(100)
    if w.opacity_slider.hasFocus():  # offscreen platforms may not grant focus; the unfocused checks above still hold
        before = w.opacity_slider.value()
        wheel(w.opacity_slider, -120 if before >= w.opacity_slider.maximum() else 120)
        assert w.opacity_slider.value() != before


def test_every_page_builds_and_nav_matches():
    w = MainWindow(Database(":memory:"), dict(load_config()))
    w.show()
    for i in range(w.stack.count()):
        w.select_page(i)
        assert w.stack.currentIndex() == i and w._nav_btns[i].isChecked()


if __name__ == "__main__":
    test_wheel_is_left_to_the_page_unless_focused()
    test_every_page_builds_and_nav_matches()
    print("ok")
