from functools import lru_cache
try:
    from ..config import get_asset_path
except (ImportError, ValueError):
    from config import get_asset_path

_CHECK = get_asset_path("check_white.svg").replace("\\", "/")
_CHEVRON = get_asset_path("chevron.svg").replace("\\", "/")

# Apple dark system greys: content < sidebar < grouped rows < controls; one accent (systemBlue)
FONT = "'General Sans', 'Inter', 'SF Pro Text', 'Segoe UI Variable Text', 'Segoe UI', -apple-system, 'Helvetica Neue', sans-serif"

COLORS = {
    "bg_dark": "#1c1c1e",
    "bg_sidebar": "#242426",
    "bg_card": "#2c2c2e",
    "bg_control": "#3a3a3c",
    "border_glass": "rgba(255, 255, 255, 0.08)",
    "accent_primary": "#0a84ff",
    "danger": "#ff453a",
    "success": "#30d158",
    "text_main": "#ffffff",
    "text_secondary": "rgba(235, 235, 245, 0.60)",
    "text_muted": "rgba(235, 235, 245, 0.38)",
}

MAIN_WINDOW_QSS = f"""
QMainWindow, QWidget#Content {{ background-color: {COLORS["bg_dark"]}; }}
QWidget {{ color: {COLORS["text_main"]}; font-family: {FONT}; font-size: 13px; }}
QLabel {{ background: transparent; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QToolTip {{ background: {COLORS["bg_card"]}; color: #fff; border: 1px solid {COLORS["border_glass"]}; padding: 4px 8px; }}

/* Sidebar */
QFrame#Sidebar {{ background-color: {COLORS["bg_sidebar"]}; border: none; border-right: 1px solid {COLORS["border_glass"]}; }}
QLabel#AppName {{ font-size: 15px; font-weight: 600; }}
QLabel#NavCaption {{ color: {COLORS["text_muted"]}; font-size: 11px; font-weight: 600; padding: 12px 10px 4px 10px; }}
QLabel#HotkeyHint {{ color: {COLORS["text_muted"]}; font-size: 11.5px; padding: 6px 10px; }}
QPushButton[nav="true"] {{
    background: transparent; color: rgba(255,255,255,0.86); text-align: left;
    padding: 0 10px; height: 32px; border-radius: 8px; font-weight: 500;
}}
QPushButton[nav="true"]:hover {{ background: rgba(255,255,255,0.06); }}
QPushButton[nav="true"]:checked {{ background: rgba(255,255,255,0.12); color: #fff; font-weight: 600; }}

/* Page chrome */
QLabel#PageTitle {{ font-size: 26px; font-weight: 600; }}
QLabel#PageSub {{ color: {COLORS["text_secondary"]}; font-size: 13px; }}
QLabel#SectionHeader {{ color: {COLORS["text_secondary"]}; font-size: 11px; font-weight: 600; padding-left: 4px; }}
QLabel#SectionFooter {{ color: {COLORS["text_muted"]}; font-size: 11.5px; padding: 0 4px; }}
QLabel#Empty {{ color: {COLORS["text_muted"]}; font-size: 13px; }}

/* Grouped lists */
QFrame#Group {{ background-color: {COLORS["bg_card"]}; border: 1px solid {COLORS["border_glass"]}; border-radius: 12px; }}
QFrame#Sep {{ background: {COLORS["border_glass"]}; border: none; max-height: 1px; min-height: 1px; }}
QLabel#RowLabel {{ font-size: 13.5px; }}
QLabel#RowSub {{ color: {COLORS["text_secondary"]}; font-size: 12px; }}
QLabel#RowValue {{ color: {COLORS["text_secondary"]}; font-size: 13px; }}
QLabel#MetricValue {{ font-size: 28px; font-weight: 600; }}

/* Badges */
QLabel[badge] {{ border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600; background: rgba(255,255,255,0.10); color: {COLORS["text_secondary"]}; }}
QLabel[badge="active"] {{ background: rgba(48,209,88,0.18); color: {COLORS["success"]}; }}
QLabel[badge="accent"] {{ background: rgba(10,132,255,0.20); color: {COLORS["accent_primary"]}; }}

/* Buttons: secondary by default, primary = accent fill, danger = tinted red */
QPushButton {{
    background-color: rgba(120,120,128,0.28); color: #fff; border: none; border-radius: 8px;
    padding: 0 14px; height: 32px; font-weight: 500;
}}
QPushButton:hover {{ background-color: rgba(120,120,128,0.40); }}
QPushButton:pressed {{ background-color: rgba(120,120,128,0.52); }}
QPushButton:disabled {{ color: {COLORS["text_muted"]}; background-color: rgba(120,120,128,0.16); }}
QPushButton[small="true"] {{ height: 28px; padding: 0 10px; font-size: 12.5px; }}
QPushButton#PrimaryButton {{ background-color: {COLORS["accent_primary"]}; color: #fff; }}
QPushButton#PrimaryButton:hover {{ background-color: #3395ff; }}
QPushButton#PrimaryButton:pressed {{ background-color: #0071e3; }}
QPushButton#PrimaryButton:disabled {{ background-color: rgba(10,132,255,0.35); color: rgba(255,255,255,0.6); }}
QPushButton#DangerButton {{ background-color: rgba(255,69,58,0.16); color: {COLORS["danger"]}; }}
QPushButton#DangerButton:hover {{ background-color: rgba(255,69,58,0.28); }}

/* Inputs */
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background-color: {COLORS["bg_control"]}; border: 1px solid transparent; border-radius: 8px;
    padding: 0 10px; height: 30px; selection-background-color: {COLORS["accent_primary"]};
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1px solid {COLORS["accent_primary"]}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({_CHEVRON}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {COLORS["bg_card"]}; border: 1px solid rgba(255,255,255,0.12); border-radius: 8px;
    selection-background-color: {COLORS["accent_primary"]}; selection-color: #fff; outline: 0; padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: rgba(120,120,128,0.40); }}
QSlider::sub-page:horizontal {{ background: {COLORS["accent_primary"]}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; background: #fff; }}
QProgressBar {{ background: rgba(255,255,255,0.10); border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {COLORS["accent_primary"]}; border-radius: 2px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 9px; border: 1.5px solid rgba(255,255,255,0.35); }}
QCheckBox::indicator:checked {{ background: {COLORS["accent_primary"]}; border-color: {COLORS["accent_primary"]}; image: url({_CHECK}); }}

/* Tables and lists */
QTableWidget {{ background: transparent; border: none; gridline-color: transparent; outline: 0;
    selection-background-color: rgba(10,132,255,0.28); selection-color: #fff; }}
QTableWidget::item {{ border-bottom: 1px solid {COLORS["border_glass"]}; padding: 0 8px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {COLORS["text_muted"]}; padding: 10px 11px; border: none;
    border-bottom: 1px solid {COLORS["border_glass"]}; font-size: 12px; font-weight: 500; text-align: left; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QListWidget {{ background: transparent; border: none; outline: 0; padding: 6px; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; margin-bottom: 2px; }}
QListWidget::item:selected {{ background: rgba(10,132,255,0.28); color: #fff; }}
QListWidget::item:hover:!selected {{ background: rgba(255,255,255,0.06); }}
QTextBrowser {{ background: transparent; border: none; }}
QSplitter::handle {{ background: {COLORS["border_glass"]}; width: 1px; }}

/* Scrollbar */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.22); border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.40); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QMessageBox, QInputDialog {{ background-color: {COLORS["bg_card"]}; }}
"""


@lru_cache(maxsize=1)
def main_qss() -> str:
    """MAIN_WINDOW_QSS with one resolved font family. A fallback list of uninstalled fonts makes
    Qt search the font database on every widget polish (~19 s to build the dashboard)."""
    from .floating_pill import ui_font_family
    return MAIN_WINDOW_QSS.replace(FONT, f"'{ui_font_family()}'")
