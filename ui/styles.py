import os
from functools import lru_cache
from ..config import get_asset_path

_CHECK = get_asset_path("check.svg").replace("\\", "/")

# Black & white minimal theme (Apple HIG: system font, hairlines, generous radii, no accent colours)

FONT = "'General Sans', 'Inter', 'SF Pro Text', 'Segoe UI Variable Text', 'Segoe UI', -apple-system, 'Helvetica Neue', sans-serif"

COLORS = {
    "bg_dark": "#000000",
    "bg_card": "#1c1c1e",
    "border_glass": "rgba(255, 255, 255, 0.10)",
    "accent_primary": "#ffffff",
    "text_main": "#ffffff",
    "text_secondary": "rgba(255, 255, 255, 0.60)",
    "text_muted": "rgba(255, 255, 255, 0.38)",
}

MAIN_WINDOW_QSS = f"""
QMainWindow, QWidget#CentralWidget {{
    background-color: {COLORS["bg_dark"]};
}}

QWidget {{
    color: {COLORS["text_main"]};
    font-family: {FONT};
    font-size: 13px;
}}

QLabel {{ background: transparent; }}

/* Tabs: segmented text, underline-free */
QTabWidget::pane {{
    border: none;
    background: transparent;
    margin-top: 8px;
}}

QTabBar {{ background: transparent; }}

QTabBar::tab {{
    background: transparent;
    color: {COLORS["text_muted"]};
    padding: 8px 16px;
    margin-right: 4px;
    font-weight: 500;
    border-radius: 14px;
}}

QTabBar::tab:selected {{
    color: #000000;
    background: #ffffff;
}}

QTabBar::tab:hover:!selected {{
    color: {COLORS["text_main"]};
    background: rgba(255, 255, 255, 0.08);
}}

/* Cards */
QFrame[class="Card"] {{
    background-color: {COLORS["bg_card"]};
    border: none;
    border-radius: 14px;
}}

/* Buttons */
QPushButton {{
    background-color: rgba(255, 255, 255, 0.10);
    color: {COLORS["text_main"]};
    border: none;
    border-radius: 10px;
    padding: 8px 16px;
    min-height: 20px;
    font-weight: 500;
}}

QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.16); }}
QPushButton:pressed {{ background-color: rgba(255, 255, 255, 0.24); }}

QPushButton#PrimaryButton {{
    background-color: #ffffff;
    color: #000000;
    font-weight: 500;
}}

QPushButton#PrimaryButton:hover {{ background-color: rgba(255, 255, 255, 0.86); }}
QPushButton#PrimaryButton:pressed {{ background-color: rgba(255, 255, 255, 0.70); }}

QPushButton#DangerButton {{
    background-color: rgba(255, 69, 58, 0.14);
    color: #ff6961;
    border: 1px solid rgba(255, 69, 58, 0.28);
    border-radius: 10px;
    padding: 6px 14px;
    font-weight: 500;
}}
QPushButton#DangerButton:hover {{
    background-color: rgba(255, 69, 58, 0.26);
    color: #ffffff;
}}

/* Model Status Badges */
QLabel.ActiveBadge {{
    background-color: rgba(52, 199, 89, 0.16);
    color: #32d74b;
    border: 1px solid rgba(52, 199, 89, 0.35);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel.DownloadedBadge {{
    background-color: rgba(10, 132, 255, 0.16);
    color: #0a84ff;
    border: 1px solid rgba(10, 132, 255, 0.35);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel.NotDownloadedBadge {{
    background-color: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 500;
}}

/* Inputs */
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background-color: rgba(255, 255, 255, 0.07);
    border: 1px solid transparent;
    border-radius: 10px;
    color: {COLORS["text_main"]};
    padding: 8px 12px;
    min-height: 20px;
    selection-background-color: rgba(255, 255, 255, 0.30);
}}

QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 1px solid rgba(255, 255, 255, 0.55);
}}

QComboBox::drop-down {{ border: none; width: 22px; }}

QComboBox QAbstractItemView {{
    background: {COLORS["bg_card"]};
    border: 1px solid {COLORS["border_glass"]};
    selection-background-color: rgba(255, 255, 255, 0.14);
    selection-color: #ffffff;
    outline: 0;
    padding: 4px;
}}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border-radius: 9px;
    border: 1.5px solid rgba(255, 255, 255, 0.35);
    background: transparent;
}}
QCheckBox::indicator:checked {{ background: #ffffff; border: 1.5px solid #ffffff; image: url({_CHECK}); }}

QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; border: none; }}

/* Tables */
QTableWidget {{
    background-color: transparent;
    border: none;
    gridline-color: transparent;
    alternate-background-color: transparent;
    selection-background-color: rgba(255, 255, 255, 0.12);
    selection-color: #ffffff;
}}

QTableWidget::item {{
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    padding: 6px;
}}

QHeaderView::section {{
    background-color: transparent;
    color: {COLORS["text_muted"]};
    padding: 10px 8px;
    border: none;
    border-bottom: 1px solid {COLORS["border_glass"]};
    font-weight: 500;
    text-align: left;
}}

QTableCornerButton::section {{ background: transparent; border: none; }}

/* Scrollbar */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0px; }}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.22);
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255, 255, 255, 0.40); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

QMessageBox {{ background-color: {COLORS["bg_card"]}; }}
"""


@lru_cache(maxsize=1)
def main_qss() -> str:
    """MAIN_WINDOW_QSS with one resolved font family. A fallback list of uninstalled fonts makes
    Qt search the font database on every widget polish (~19 s to build the dashboard)."""
    from .floating_pill import ui_font_family
    return MAIN_WINDOW_QSS.replace(FONT, f"'{ui_font_family()}'")
