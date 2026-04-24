"""Glass matte black theme — single source of truth for colours and styles."""

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG         = '#0e0e12'   # root / tab background
SURFACE    = '#17171e'   # panel / LabelFrame surface
SURFACE2   = '#1e1e28'   # raised controls inside panels
BORDER     = '#2a2a3a'   # hairline borders
TEXT       = '#dcdcef'   # primary text
TEXT_DIM   = '#55556a'   # secondary / disabled text
ACCENT     = '#5c7cfa'   # indigo-blue accent
SELECT_BG  = '#262650'   # selection background
SELECT_FG  = TEXT
ENTRY_BG   = '#11111a'   # entry / listbox / text bg
BUTTON_BG  = '#1c1c2e'   # resting button
BUTTON_ACT = '#2a2a45'   # hovered button
CANVAS_BG  = '#09090f'   # minimap canvas

# Typography (tuple form for widget configure; string for option_add)
_FF       = 'Segoe UI'
FONT      = (_FF, 10)
FONT_BOLD = (_FF, 10, 'bold')
FONT_SM   = (_FF, 9)
_FONT_STR = f'{_FF} 10'


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def apply_theme(root: tk.Tk) -> None:
    """Configure the glass matte black theme on ROOT before any widgets are built."""
    root.configure(bg=BG)
    root.attributes('-alpha', 0.97)

    _apply_option_db(root)
    _apply_ttk_styles(root)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_option_db(root: tk.Tk) -> None:
    """Set defaults for every classic tk widget via the option database."""
    O = root.option_add

    # Universals
    O('*background',               SURFACE)
    O('*foreground',               TEXT)
    O('*font',                     _FONT_STR)
    O('*relief',                   'flat')
    O('*borderWidth',              0)
    O('*highlightThickness',       0)
    O('*activeBackground',         BUTTON_ACT)
    O('*activeForeground',         TEXT)
    O('*disabledForeground',       TEXT_DIM)
    O('*selectBackground',         SELECT_BG)
    O('*selectForeground',         SELECT_FG)

    # Entry
    O('*Entry.background',         ENTRY_BG)
    O('*Entry.disabledBackground', SURFACE2)
    O('*Entry.readonlyBackground', SURFACE2)
    O('*Entry.insertBackground',   TEXT)

    # Listbox
    O('*Listbox.background',       ENTRY_BG)

    # Text
    O('*Text.background',          ENTRY_BG)
    O('*Text.insertBackground',    TEXT)

    # Canvas
    O('*Canvas.background',        CANVAS_BG)

    # Button cursor
    O('*Button.cursor',            'hand2')

    # Toggle widgets
    O('*Checkbutton.selectColor',  ENTRY_BG)
    O('*Radiobutton.selectColor',  ENTRY_BG)

    # Menus
    O('*Menu.background',          SURFACE2)
    O('*Menu.activeBackground',    SELECT_BG)
    O('*Menu.activeForeground',    TEXT)
    O('*Menu.relief',              'flat')


def _apply_ttk_styles(root: tk.Tk) -> None:
    s = ttk.Style(root)
    s.theme_use('clam')

    # Frame
    s.configure('TFrame',         background=BG)
    s.configure('Surface.TFrame', background=SURFACE)

    # Label
    s.configure('TLabel',
                background=BG, foreground=TEXT, font=FONT)
    s.configure('Surface.TLabel',
                background=SURFACE, foreground=TEXT, font=FONT)
    s.configure('Dim.TLabel',
                background=SURFACE, foreground=TEXT_DIM, font=FONT_SM)

    # LabelFrame
    s.configure('TLabelframe',
                background=SURFACE,
                bordercolor=BORDER,
                darkcolor=BORDER,
                lightcolor=BORDER,
                relief='solid',
                borderwidth=1)
    s.configure('TLabelframe.Label',
                background=SURFACE,
                foreground=ACCENT,
                font=FONT_BOLD)

    # Notebook
    s.configure('TNotebook',
                background=BG,
                borderwidth=0,
                tabmargins=[0, 0, 0, 0])
    s.configure('TNotebook.Tab',
                background=SURFACE,
                foreground=TEXT_DIM,
                font=FONT,
                padding=[14, 7],
                borderwidth=0)
    s.map('TNotebook.Tab',
          background=[('selected', SURFACE2), ('active', SURFACE2)],
          foreground=[('selected', TEXT),     ('active', TEXT)])

    # Standard button
    s.configure('TButton',
                background=BUTTON_BG,
                foreground=TEXT,
                font=FONT,
                borderwidth=0,
                focuscolor='none',
                relief='flat',
                padding=[10, 5])
    s.map('TButton',
          background=[('active', BUTTON_ACT), ('pressed', SURFACE2)],
          foreground=[('active', TEXT)])

    # Accent button (Save, Add)
    s.configure('Accent.TButton',
                background=ACCENT,
                foreground='#ffffff',
                font=FONT_BOLD,
                borderwidth=0,
                relief='flat',
                padding=[10, 5])
    s.map('Accent.TButton',
          background=[('active', '#7a9aff'), ('pressed', '#3a5fe0')],
          foreground=[('active', '#ffffff'), ('pressed', '#ffffff')])

    # Danger button (Delete)
    s.configure('Danger.TButton',
                background='#2e1515',
                foreground='#ff6b6b',
                font=FONT,
                borderwidth=0,
                relief='flat',
                padding=[10, 5])
    s.map('Danger.TButton',
          background=[('active', '#3d1a1a'), ('pressed', '#1e0d0d')],
          foreground=[('active', '#ff6b6b')])

    # Icon button (▲ ▼ ➕ ✕ in toolbar)
    s.configure('Icon.TButton',
                background=BUTTON_BG,
                foreground=TEXT,
                font=(_FF, 12),
                borderwidth=0,
                focuscolor='none',
                relief='flat',
                padding=[6, 4])
    s.map('Icon.TButton',
          background=[('active', BUTTON_ACT), ('pressed', ACCENT)])

    # Scrollbar
    s.configure('TScrollbar',
                background=SURFACE2,
                troughcolor=BG,
                borderwidth=0,
                arrowcolor=TEXT_DIM,
                arrowsize=12,
                relief='flat')
    s.map('TScrollbar',
          background=[('active', BORDER), ('pressed', ACCENT)])

    # Checkbutton
    s.configure('TCheckbutton',
                background=SURFACE,
                foreground=TEXT,
                font=FONT,
                indicatorcolor=ENTRY_BG,
                indicatorrelief='flat',
                focuscolor='none')
    s.map('TCheckbutton',
          indicatorcolor=[('selected', ACCENT)],
          background=[('active', SURFACE)])

    # Radiobutton
    s.configure('TRadiobutton',
                background=SURFACE,
                foreground=TEXT,
                font=FONT,
                indicatorcolor=ENTRY_BG,
                focuscolor='none')
    s.map('TRadiobutton',
          indicatorcolor=[('selected', ACCENT)],
          background=[('active', SURFACE)])

    # Entry (ttk version, if used)
    s.configure('TEntry',
                fieldbackground=ENTRY_BG,
                foreground=TEXT,
                insertcolor=TEXT,
                bordercolor=BORDER,
                lightcolor=BORDER,
                darkcolor=BORDER,
                borderwidth=1,
                relief='flat',
                padding=4)
    s.map('TEntry',
          fieldbackground=[('disabled', SURFACE2), ('readonly', SURFACE2)],
          foreground=[('disabled', TEXT_DIM),       ('readonly', TEXT_DIM)])
