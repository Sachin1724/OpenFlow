"""Self-check for the settings hotkey recorder: python -m openflow.test_hotkey_recorder (from the repo's parent)."""
from openflow.ui.main_window import vk_name, combo_from_keys, pretty_hotkey


def test_combos():
    assert vk_name(0xA2) == "ctrl" and vk_name(0x77) == "f8" and vk_name(0x41) == "a" and vk_name(0x20) == "space"
    assert combo_from_keys({"shift", "ctrl"}) == "ctrl+shift"
    assert combo_from_keys({"space", "alt"}) == "alt+space"
    assert combo_from_keys({"f8"}) == "f8"
    assert combo_from_keys({"a"}) == "" and combo_from_keys({"space"}) == ""  # would fire while typing
    assert pretty_hotkey("ctrl+shift+f12") == ["Ctrl", "Shift", "F12"]


if __name__ == "__main__":
    test_combos()
    print("ok")
