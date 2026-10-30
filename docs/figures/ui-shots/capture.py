"""Renders the product pictures used on the landing page: the dashboard (sample data, never a real history)
and the island's states (transparent PNG). Run from the repo root: python docs/figures/ui-shots/capture.py"""
import os, sys, datetime
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QScrollArea
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QRect

app = QApplication([])
import openflow.ui.main_window as mw
mw.save_config = lambda *_: None                      # drives real controls: never write the user's config
from openflow.ui.main_window import MainWindow
from openflow.ui.island import IslandPill
from openflow.database import Database
from openflow.config import load_config
from openflow.engine.meeting import transcript_text, format_meeting_notes

OUT = os.path.join("docs", "img")
db = Database(":memory:")
SAMPLES = [
    ("Slack", "Team standup", "Quick update from my side: the export fix is merged and I am moving on to the landing page.", 11, 0.42),
    ("Gmail", "Re: Launch plan", "Thanks Priya, Friday works for me. I will send the final build and the release notes by noon.", 18, 0.38),
    ("VS Code", "main.py", "Add a guard so an empty recording never reaches the model.", 11, 0.31),
    ("Notion", "Roadmap", "Next up: a lighter engine process, then the island, then the new dashboard.", 14, 0.45),
    ("WhatsApp", "Maa", "Reaching home by eight, keep the dinner warm.", 8, 0.29),
    ("Chrome", "Docs", "Can you check whether the installer still asks for administrator rights on a clean machine.", 15, 0.4),
]
now = datetime.datetime.now()
for i, (app_name, win, text, words, lat) in enumerate(SAMPLES):
    db.add_history_entry(text, text, app_name, win, words / 3.1, words, "smart_clean", "small", "cpu", int(lat * 1000))
for phrase, rep in (("open flow", "OpenFlow"), ("odia", "Odia"), ("kubernetes", "Kubernetes")):
    db.add_dictionary_entry(phrase, rep)
lines = [(4, "You", "Thanks everyone for joining, let us start with the release."), (11, "Them", "The installer is ready and the new dashboard is in."),
         (19, "Them", "We decided to ship on Friday."), (27, "Them", "Rahul will follow up with design by tomorrow."),
         (36, "You", "Great, I will send the notes after the call.")]
raw = transcript_text(lines)
db.add_meeting_note("Product sync", "Zoom", raw, format_meeting_notes(raw, "Zoom"), 38 * 60)
raw2 = transcript_text([(5, "Them", "Welcome back to the show."), (9, "Them", "Today we talk about voice on the desktop."), (20, "Them", "Privacy is the reason people stay local.")])
db.add_meeting_note("Podcast episode", "What's playing", raw2, format_meeting_notes(raw2, "What's playing"), 22 * 60)

cfg = dict(load_config())
cfg.update(capsule_style="island", capsule_opacity=1.0, capsule_width_pct=100, capsule_height_pct=100)
w = MainWindow(db, cfg)
w.resize(1180, 760); w.show(); QTest.qWait(500)
w.refresh_history(); w.refresh_meetings(); w.refresh_stats(); w.refresh_dictionary()
for name, page in (("history", 0), ("meetings", 1), ("models", 3), ("analytics", 5)):
    w.select_page(page); QTest.qWait(350)
    w.grab().save(os.path.join(OUT, f"ui-{name}.png"))
w.select_page(4); QTest.qWait(300)
sa = w.stack.currentWidget().findChild(QScrollArea)
sa.verticalScrollBar().setValue(int(sa.verticalScrollBar().maximum() * 0.40)); QTest.qWait(300)
w.grab().save(os.path.join(OUT, "ui-settings.png"))

isl = IslandPill("Realtek Microphone", "en-in", "small"); isl.populate_models("small"); isl.populate_mics([])
isl.show(); isl.activate(); QTest.qWait(900)
def island(name, h=70):
    QTest.qWait(1000)
    r = isl._shape_rect().toAlignedRect().adjusted(-10, 0, 10, 10)
    path = os.path.join(OUT, f"island-{name}.png")
    isl.grab().copy(QRect(r.x(), 0, r.width(), min(h, isl.height()))).save(path)
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    im.crop(im.getchannel("A").getbbox()).save(path)  # tight to the shape: transparent edges only get in the way
island("idle", 40)
isl.show_listening(); island("listen")
isl.show_processing(); island("writing")
isl.show_pasted(9); island("pasted", 60)
isl._to_idle(); QTest.qWait(600)
isl.show_mic_event("Realtek Microphone", "connected"); island("mic", 90)
isl._to_idle(); QTest.qWait(600)
isl._open_panel(); island("panel", 300)
print("saved to", OUT)
