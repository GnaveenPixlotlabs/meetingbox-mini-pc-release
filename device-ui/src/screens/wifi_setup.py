"""
WiFi Setup Screen – full rework for 7-inch touch display (1024 × 600).

Design principles
─────────────────
• All tap targets ≥ 52 px tall for finger accuracy.
• Signal bars drawn with canvas (no missing-glyph Unicode characters).
• Password dialog is placed in the upper portion of the screen so the
  software keyboard (bottom ~40 %) never covers the input field.
  When a TextInput gains focus, the card also slides further up by
  binding to Window.on_keyboard_height.
• Show / Hide password toggle lets the user verify what they typed.
• Animated scanning dots while the radio is working.
• Wi-Fi radio toggle at the top; turning it on triggers an auto-scan.
"""

import logging
import math
import threading
from pathlib import Path
from typing import Optional

import wifi_nmcli_local

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from async_helper import run_async
from components.button import PrimaryButton, SecondaryButton
from components.modal_dialog import ModalDialog
from components.toggle_switch import ToggleSwitch
from config import ASSETS_DIR, BORDER_RADIUS, COLORS, FONT_SIZES
from screens.base_screen import BaseScreen

logger = logging.getLogger(__name__)

WELCOME_DIR = ASSETS_DIR / "welcome"
LOGO_PATH = str(WELCOME_DIR / "LOGO.png")

# Dark blue-tinted background for WiFi setup
_BG = (0.043, 0.051, 0.067, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _format_security(sec: str) -> str:
    s = (sec or "").strip()
    if not s or s in ("--", "none", "open"):
        return "Open"
    s = s.upper().replace("_", " ")
    for token in ("WPA3", "WPA2", "WPA", "WEP"):
        if token in s:
            return token
    return s[:8]


def _is_open(sec: str) -> bool:
    s = (sec or "").lower().strip()
    return not s or s in ("open", "--", "none", "")


def _sv() -> float:
    from config import other_screen_vertical_scale
    return other_screen_vertical_scale()


def _sh() -> float:
    from config import other_screen_horizontal_scale
    return other_screen_horizontal_scale()


def _suv(px: float) -> int:
    return max(1, int(round(float(px) * _sv())))


def _suh(px: float) -> int:
    return max(1, int(round(float(px) * _sh())))


def _suf(fs: float) -> int:
    return max(6, int(round(float(fs) * _sv())))


# ─────────────────────────────────────────────────────────────────────────────
# Signal strength bar widget (4 rising bars, canvas-drawn)
# ─────────────────────────────────────────────────────────────────────────────

class _SignalBars(Widget):
    """Four rising bars showing Wi-Fi signal strength (0–100)."""

    _BAR_W = 5
    _GAP = 3
    _HEIGHTS = [5, 9, 13, 17]

    def __init__(self, signal: int = 0, connected: bool = False, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (32, 22))
        super().__init__(**kwargs)
        self._signal = max(0, min(100, int(signal)))
        self._connected = connected
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_once(lambda *_: self._draw(), 0)

    def set(self, signal: int, connected: bool):
        self._signal = max(0, min(100, int(signal)))
        self._connected = connected
        self._draw()

    def _lit(self) -> int:
        s = self._signal
        if s >= 75:
            return 4
        if s >= 50:
            return 3
        if s >= 25:
            return 2
        if s >= 5:
            return 1
        return 0

    def _color(self) -> tuple:
        if not self._connected:
            return COLORS["gray_600"]
        if self._signal >= 65:
            return COLORS["green"]
        if self._signal >= 35:
            return COLORS["yellow"]
        return COLORS["red"]

    def _draw(self, *_):
        self.canvas.clear()
        lit = self._lit()
        active = self._color()
        dim = COLORS["gray_800"]
        bw = _suh(self._BAR_W)
        gap = _suh(self._GAP)
        x0 = self.x + _suh(2)
        bot = self.y + _suv(2)
        radius = max(1, _suv(2))

        with self.canvas:
            for i, h_raw in enumerate(self._HEIGHTS):
                h = _suv(h_raw)
                Color(*(active if (self._connected and i < lit) else dim))
                RoundedRectangle(
                    pos=(x0 + i * (bw + gap), bot),
                    size=(bw, h),
                    radius=[radius],
                )


# ─────────────────────────────────────────────────────────────────────────────
# Individual network row
# ─────────────────────────────────────────────────────────────────────────────

class _NetworkRow(ButtonBehavior, BoxLayout):
    """One tappable network row with signal bars, SSID, security badge."""

    _H = 64  # logical px; scaled at build time

    def __init__(self, net: dict, connecting_ssid: str, **kwargs):
        self.net = net
        ssid = (net.get("ssid") or "").strip()
        sec = net.get("security") or ""
        connected = bool(net.get("connected"))
        signal = int(net.get("signal_strength") or 0)
        busy = (connecting_ssid or "") == ssid

        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", _suv(self._H))
        kwargs.setdefault("padding", [_suh(14), _suv(8), _suh(10), _suv(8)])
        kwargs.setdefault("spacing", _suh(10))
        super().__init__(**kwargs)

        # Card background
        with self.canvas.before:
            self._bg_color = Color(*COLORS["surface"])
            self._bg = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[BORDER_RADIUS])
        self.bind(
            pos=lambda w, *_: setattr(self._bg, "pos", w.pos),
            size=lambda w, *_: setattr(self._bg, "size", w.size),
        )

        # ── Left: signal bars or spinner ──────────────────────────────────
        left_col = BoxLayout(
            orientation="vertical",
            size_hint=(None, 1),
            width=_suh(36),
            spacing=_suv(2),
        )
        if busy:
            self._spinner_label = Label(
                text="...",
                font_size=_suf(FONT_SIZES["small"]),
                color=COLORS["blue"],
                halign="center",
                valign="middle",
                size_hint=(1, None),
                height=_suv(22),
            )
            self._spinner_event = Clock.schedule_interval(
                self._tick_spinner, 0.5)
            left_col.add_widget(Widget(size_hint=(1, 1)))
            left_col.add_widget(self._spinner_label)
            left_col.add_widget(Widget(size_hint=(1, 1)))
        else:
            bars = _SignalBars(
                signal=signal,
                connected=connected,
                size=(_suh(30), _suv(20)),
            )
            bars_anchor = AnchorLayout(
                anchor_x="center", anchor_y="center", size_hint=(1, 1))
            bars_anchor.add_widget(bars)
            left_col.add_widget(bars_anchor)

            pct = Label(
                text=f"{signal}%",
                font_size=_suf(FONT_SIZES["tiny"]),
                color=COLORS["gray_500"] if not connected else COLORS["green"],
                halign="center",
                size_hint=(1, None),
                height=_suv(14),
            )
            left_col.add_widget(pct)
        self.add_widget(left_col)

        # ── Middle: SSID + security ───────────────────────────────────────
        mid = BoxLayout(orientation="vertical", size_hint=(1, 1), spacing=_suv(3))

        ssid_lbl = Label(
            text=ssid or "(hidden network)",
            font_size=_suf(FONT_SIZES["medium"]),
            bold=True,
            color=COLORS["white"],
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=_suv(24),
        )
        ssid_lbl.bind(size=ssid_lbl.setter("text_size"))
        mid.add_widget(ssid_lbl)

        sec_txt = "Connecting…" if busy else _format_security(sec)
        sec_color = COLORS["blue"] if busy else (
            COLORS["green"] if _is_open(sec) else COLORS["gray_500"])
        sec_lbl = Label(
            text=sec_txt,
            font_size=_suf(FONT_SIZES["tiny"]),
            color=sec_color,
            halign="left",
            valign="top",
            size_hint=(1, None),
            height=_suv(16),
        )
        sec_lbl.bind(size=sec_lbl.setter("text_size"))
        mid.add_widget(sec_lbl)
        self.add_widget(mid)

        # ── Right: connected dot or padlock label ─────────────────────────
        right = BoxLayout(
            orientation="vertical",
            size_hint=(None, 1),
            width=_suh(30),
        )
        if connected:
            dot_anchor = AnchorLayout(anchor_x="center", anchor_y="center",
                                      size_hint=(1, 1))
            dot = _ConnectedDot(size=(_suv(10), _suv(10)))
            dot_anchor.add_widget(dot)
            right.add_widget(dot_anchor)
        elif not busy and not _is_open(sec):
            lock = Label(
                text="LOCK",
                font_size=_suf(FONT_SIZES["tiny"] - 1),
                color=COLORS["gray_600"],
                halign="center",
                valign="middle",
                size_hint=(1, 1),
            )
            lock.bind(size=lock.setter("text_size"))
            right.add_widget(lock)
        self.add_widget(right)

    def _tick_spinner(self, *_):
        if hasattr(self, "_spinner_label"):
            t = self._spinner_label.text
            self._spinner_label.text = (
                "." if t == "..." else t + ".")

    def cleanup(self):
        if hasattr(self, "_spinner_event"):
            self._spinner_event.cancel()

    def on_press(self):
        self._bg_color.rgba = COLORS["surface_light"]

    def on_release(self):
        self._bg_color.rgba = COLORS["surface"]


class _ConnectedDot(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_once(lambda *_: self._draw(), 0)

    def _draw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(*COLORS["green"])
            r = min(self.width, self.height) / 2
            cx, cy = self.center
            Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2))


# ─────────────────────────────────────────────────────────────────────────────
# Tap-anywhere dismiss link button
# ─────────────────────────────────────────────────────────────────────────────

class _TextBtn(ButtonBehavior, Label):
    def on_press(self):
        self.opacity = 0.5

    def on_release(self):
        self.opacity = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Styled TextInput with rounded border
# ─────────────────────────────────────────────────────────────────────────────

class _StyledInput(TextInput):
    """TextInput with a visible rounded border that highlights on focus."""

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", _suv(52))
        kwargs.setdefault("font_size", _suf(FONT_SIZES["medium"]))
        kwargs.setdefault("foreground_color", COLORS["white"])
        kwargs.setdefault("cursor_color", COLORS["blue"])
        kwargs.setdefault("hint_text_color", [0.4, 0.4, 0.42, 1])
        kwargs.setdefault("padding", [_suh(14), _suv(14), _suh(14), _suv(14)])
        # Transparent kivy background – we draw our own
        kwargs["background_normal"] = ""
        kwargs["background_active"] = ""
        kwargs["background_color"] = (0, 0, 0, 0)
        super().__init__(**kwargs)
        self._focused = False
        self.bind(focus=self._on_focus_change, pos=self._draw_border,
                  size=self._draw_border)
        Clock.schedule_once(lambda *_: self._draw_border(), 0)

    def _on_focus_change(self, _inst, focused):
        self._focused = focused
        self._draw_border()

    def _draw_border(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            # Field fill
            Color(*COLORS["surface_light"])
            RoundedRectangle(pos=self.pos, size=self.size,
                             radius=[max(6, BORDER_RADIUS - 4)])
            # Border – brighter when focused
            if self._focused:
                Color(*COLORS["blue"])
                bw = 1.8
            else:
                Color(*COLORS["gray_700"])
                bw = 1.0
            Line(
                rounded_rectangle=(
                    self.x, self.y, self.width, self.height,
                    max(6, BORDER_RADIUS - 4)),
                width=bw,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Password dialog helper – positions the card above the keyboard
# ─────────────────────────────────────────────────────────────────────────────

def _card_y_for_keyboard(card_h: float, window_h: float,
                         keyboard_h: float, padding: float = 24) -> float:
    """
    Return the y coordinate that places the card fully above the keyboard,
    clamped so it stays on screen.
    """
    if keyboard_h > 0:
        target = keyboard_h + padding
    else:
        # Sit in the upper-middle: 15 % from top
        target = window_h * 0.55 - card_h / 2
    return float(max(padding, min(window_h - card_h - padding, target)))


def _center_y_hint(card_h: float, window_h: float, keyboard_h: float) -> float:
    y = _card_y_for_keyboard(card_h, window_h, keyboard_h)
    return (y + card_h / 2) / max(1, window_h)


# ─────────────────────────────────────────────────────────────────────────────
# Main Screen
# ─────────────────────────────────────────────────────────────────────────────

class WiFiSetupScreen(BaseScreen):
    """First-boot WiFi page: scan → connect → Next."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.networks: list = []
        self._connecting_ssid: Optional[str] = None
        self._ready_for_next = False
        self._connected_ssid = ""
        self._scan_anim_event = None
        self._scan_dots = 0
        self._row_widgets: list = []
        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = BoxLayout(
            orientation="vertical",
            padding=[_suh(20), _suv(12), _suh(20), _suv(12)],
            spacing=0,
            size_hint=(1, 1),
        )
        with root.canvas.before:
            Color(*_BG)
            self._root_bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda w, *_: setattr(self._root_bg, "pos", w.pos),
            size=lambda w, *_: setattr(self._root_bg, "size", w.size),
        )

        # ── Header ────────────────────────────────────────────────────────
        header = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=_suv(48),
            spacing=_suh(10),
        )
        if Path(LOGO_PATH).exists():
            header.add_widget(Image(
                source=LOGO_PATH,
                size_hint=(None, 1),
                width=_suh(36),
                fit_mode="contain",
            ))
        title_lbl = Label(
            text="Wi-Fi Setup",
            font_size=_suf(FONT_SIZES["title"]),
            bold=True,
            color=COLORS["white"],
            halign="left",
            valign="middle",
            size_hint=(1, 1),
        )
        title_lbl.bind(size=title_lbl.setter("text_size"))
        header.add_widget(title_lbl)
        root.add_widget(header)

        root.add_widget(Widget(size_hint=(1, None), height=_suv(4)))

        # ── Subtitle ──────────────────────────────────────────────────────
        sub = Label(
            text="Select your network to enable calendar sync and email delivery.",
            font_size=_suf(FONT_SIZES["small"]),
            color=COLORS["gray_400"],
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=_suv(20),
        )
        sub.bind(size=sub.setter("text_size"))
        root.add_widget(sub)

        root.add_widget(Widget(size_hint=(1, None), height=_suv(10)))

        # ── Wi-Fi radio toggle row ─────────────────────────────────────────
        radio_row = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=_suv(44),
            spacing=_suh(12),
            padding=[_suh(4), 0],
        )
        with radio_row.canvas.before:
            Color(*COLORS["surface"])
            _radio_bg = RoundedRectangle(
                pos=radio_row.pos, size=radio_row.size,
                radius=[BORDER_RADIUS])
        radio_row.bind(
            pos=lambda w, *_: setattr(_radio_bg, "pos", w.pos),
            size=lambda w, *_: setattr(_radio_bg, "size", w.size),
        )
        radio_icon = Label(
            text="WiFi",
            font_size=_suf(FONT_SIZES["tiny"]),
            bold=True,
            color=COLORS["blue"],
            size_hint=(None, 1),
            width=_suh(36),
        )
        radio_row.add_widget(radio_icon)
        radio_label = Label(
            text="Wi-Fi radio",
            font_size=_suf(FONT_SIZES["medium"]),
            color=COLORS["white"],
            bold=False,
            halign="left",
            valign="middle",
            size_hint=(1, 1),
        )
        radio_label.bind(size=radio_label.setter("text_size"))
        radio_row.add_widget(radio_label)
        self._radio_status_lbl = Label(
            text="",
            font_size=_suf(FONT_SIZES["tiny"]),
            color=COLORS["gray_500"],
            halign="right",
            valign="middle",
            size_hint=(None, 1),
            width=_suh(80),
        )
        self._radio_status_lbl.bind(size=self._radio_status_lbl.setter("text_size"))
        radio_row.add_widget(self._radio_status_lbl)
        self._wifi_toggle = ToggleSwitch(
            active=True,
            on_toggle=self._on_radio_toggled,
            size_hint=(None, None),
            size=(_suh(52), _suv(30)),
            pos_hint={"center_y": 0.5},
        )
        radio_row.add_widget(self._wifi_toggle)
        radio_row.add_widget(Widget(size_hint=(None, 1), width=_suh(8)))
        root.add_widget(radio_row)

        root.add_widget(Widget(size_hint=(1, None), height=_suv(10)))

        # ── Network list card ──────────────────────────────────────────────
        list_card = BoxLayout(
            orientation="vertical",
            size_hint=(1, 1),
            spacing=0,
        )
        with list_card.canvas.before:
            Color(*COLORS["surface"])
            self._card_bg = RoundedRectangle(
                pos=list_card.pos, size=list_card.size,
                radius=[BORDER_RADIUS])
        list_card.bind(
            pos=lambda w, *_: setattr(self._card_bg, "pos", w.pos),
            size=lambda w, *_: setattr(self._card_bg, "size", w.size),
        )

        # Card header row
        card_hdr = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=_suv(38),
            padding=[_suh(12), _suv(6)],
        )
        self._scan_status_lbl = Label(
            text="Scanning…",
            font_size=_suf(FONT_SIZES["small"]),
            bold=True,
            color=COLORS["gray_400"],
            halign="left",
            valign="middle",
            size_hint=(1, 1),
        )
        self._scan_status_lbl.bind(size=self._scan_status_lbl.setter("text_size"))
        card_hdr.add_widget(self._scan_status_lbl)

        scan_btn = _TextBtn(
            text="Scan",
            font_size=_suf(FONT_SIZES["small"]),
            color=COLORS["blue"],
            halign="right",
            valign="middle",
            size_hint=(None, 1),
            width=_suh(52),
        )
        scan_btn.bind(size=scan_btn.setter("text_size"))
        scan_btn.bind(on_press=lambda *_: self._load_networks(rescan=True))
        card_hdr.add_widget(scan_btn)

        add_btn = _TextBtn(
            text="+ Add",
            font_size=_suf(FONT_SIZES["small"]),
            color=COLORS["blue"],
            halign="right",
            valign="middle",
            size_hint=(None, 1),
            width=_suh(52),
        )
        add_btn.bind(size=add_btn.setter("text_size"))
        add_btn.bind(on_press=lambda *_: self._show_manual_dialog())
        card_hdr.add_widget(add_btn)
        list_card.add_widget(card_hdr)

        # Separator
        sep = Widget(size_hint=(1, None), height=1)
        with sep.canvas:
            Color(*COLORS["gray_800"])
            _sr = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(
            pos=lambda w, *_: setattr(_sr, "pos", w.pos),
            size=lambda w, *_: setattr(_sr, "size", w.size),
        )
        list_card.add_widget(sep)

        # Scrollable network list
        self._scroll = ScrollView(
            do_scroll_x=False,
            size_hint=(1, 1),
            bar_width=_suh(4),
            bar_color=[*COLORS["blue"][:3], 0.6],
            bar_inactive_color=[*COLORS["gray_700"][:3], 0.4],
        )
        self._list = GridLayout(
            cols=1,
            spacing=_suv(6),
            size_hint_y=None,
            padding=[_suh(10), _suv(8), _suh(10), _suv(8)],
        )
        self._list.bind(minimum_height=self._list.setter("height"))
        self._scroll.add_widget(self._list)
        list_card.add_widget(self._scroll)
        root.add_widget(list_card)

        root.add_widget(Widget(size_hint=(1, None), height=_suv(10)))

        # ── Footer: Back | spacer | Next ──────────────────────────────────
        foot = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=_suv(52),
            spacing=_suh(12),
        )
        back_btn = SecondaryButton(
            text="Back",
            size_hint=(None, 1),
            width=_suh(100),
            font_size=_suf(FONT_SIZES["medium"]),
        )
        back_btn.bind(on_press=lambda *_: self.go_back())
        foot.add_widget(back_btn)
        foot.add_widget(Widget(size_hint=(1, 1)))

        self._next_btn = PrimaryButton(
            text="Next  →",
            size_hint=(None, 1),
            width=_suh(130),
            font_size=_suf(FONT_SIZES["medium"]),
        )
        self._next_btn.bind(on_press=self._on_next)
        foot.add_widget(self._next_btn)
        root.add_widget(foot)

        self.add_widget(root)
        self._sync_next_btn()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_enter(self):
        self._connecting_ssid = None
        self._ready_for_next = False
        self._connected_ssid = ""
        self._sync_next_btn()
        self._sync_radio_toggle()
        self._load_networks(rescan=True)

    def on_leave(self):
        self._connecting_ssid = None
        self._stop_scan_anim()
        self._cleanup_rows()

    # ── Next button ───────────────────────────────────────────────────────

    def _sync_next_btn(self):
        self._next_btn.disabled = not self._ready_for_next
        self._next_btn.opacity = 1.0 if self._ready_for_next else 0.4

    def _set_ready(self, ssid: str):
        self._ready_for_next = True
        self._connected_ssid = ssid or ""
        self._sync_next_btn()

    def _on_next(self, *_):
        if not self._ready_for_next:
            return
        self.app.connected_wifi_ssid = self._connected_ssid
        self.app.setup_network_is_ethernet = False
        self.goto("wifi_connected", transition="fade")

    # ── Radio toggle ──────────────────────────────────────────────────────

    def _sync_radio_toggle(self):
        en = wifi_nmcli_local.get_wifi_radio_enabled()
        if en is not None:
            self._wifi_toggle.active = bool(en)
            self._radio_status_lbl.text = "On" if en else "Off"

    def _on_radio_toggled(self, active: bool):
        self._radio_status_lbl.text = "On" if active else "Off"

        def work():
            result = wifi_nmcli_local.set_wifi_radio(active)
            Clock.schedule_once(
                lambda *_: self._after_radio_set(result, active), 0)

        threading.Thread(target=work, daemon=True).start()

    def _after_radio_set(self, result: dict, wanted_on: bool):
        if not result.get("ok"):
            msg = (result.get("message") or "Could not change Wi-Fi.").strip()
            self._wifi_toggle.active = not wanted_on
            self._radio_status_lbl.text = "On" if (not wanted_on) else "Off"
            self.add_widget(ModalDialog(
                title="Wi-Fi",
                message=msg[:280],
                confirm_text="OK",
                cancel_text="",
            ))
            return
        if wanted_on:
            self._load_networks(rescan=True)
        else:
            self._stop_scan_anim()
            self.networks = []
            self._populate()

    # ── Scanning animation ────────────────────────────────────────────────

    def _start_scan_anim(self):
        self._scan_dots = 0
        self._scan_status_lbl.text = "Scanning."
        self._scan_anim_event = Clock.schedule_interval(
            self._tick_scan_anim, 0.4)

    def _tick_scan_anim(self, *_):
        self._scan_dots = (self._scan_dots + 1) % 4
        self._scan_status_lbl.text = "Scanning" + "." * max(1, self._scan_dots)

    def _stop_scan_anim(self):
        if self._scan_anim_event:
            self._scan_anim_event.cancel()
            self._scan_anim_event = None

    # ── Network loading ───────────────────────────────────────────────────

    def _load_networks(self, rescan: bool = False):
        self._start_scan_anim()

        async def _load():
            nets: list = []
            try:
                nets = wifi_nmcli_local.scan_wifi_networks(rescan=rescan)
            except Exception as e:
                logger.warning("Local WiFi scan failed, trying backend: %s", e)
            if not nets:
                try:
                    nets = await self.backend.get_wifi_networks()
                except Exception as be:
                    logger.warning("Backend WiFi scan failed: %s", be)
                    Clock.schedule_once(
                        lambda *_: self._show_scan_error(), 0)
                    Clock.schedule_once(
                        lambda *_: self._apply_networks([]), 0)
                    return
            Clock.schedule_once(lambda *_: self._apply_networks(nets), 0)

        run_async(_load())

    def _show_scan_error(self):
        self.add_widget(ModalDialog(
            title="Scan failed",
            message=(
                "Could not scan for networks.\n"
                "Check that the Wi-Fi radio is on and NetworkManager is running."
            ),
            confirm_text="OK",
            cancel_text="",
        ))

    def _apply_networks(self, nets):
        self._stop_scan_anim()
        self.networks = nets or []
        for n in self.networks:
            if n.get("connected") and n.get("ssid"):
                self._set_ready(n["ssid"])
                break

        count = len([n for n in self.networks if n.get("ssid")])
        self._scan_status_lbl.text = (
            f"{count} network{'s' if count != 1 else ''} found"
            if count else "No networks found")
        self._populate()

    def _cleanup_rows(self):
        for w in self._row_widgets:
            if hasattr(w, "cleanup"):
                w.cleanup()
        self._row_widgets.clear()

    def _populate(self):
        self._cleanup_rows()
        self._list.clear_widgets()

        def _key(n):
            return (0 if n.get("connected") else 1,
                    -(n.get("signal_strength") or 0))

        for net in sorted(self.networks, key=_key):
            if not (net.get("ssid") or "").strip():
                continue
            row = _NetworkRow(net, self._connecting_ssid or "")
            row.bind(on_press=lambda inst, n=net: self._on_row_tap(n))
            self._list.add_widget(row)
            self._row_widgets.append(row)

        if not self._list.children:
            hint = wifi_nmcli_local.empty_scan_hint()
            lbl = Label(
                text=hint,
                font_size=_suf(FONT_SIZES["small"]),
                color=COLORS["gray_500"],
                halign="left",
                valign="top",
                size_hint=(1, None),
                height=_suv(100),
            )
            lbl.bind(size=lbl.setter("text_size"))
            self._list.add_widget(lbl)

    # ── Row tap ───────────────────────────────────────────────────────────

    def _on_row_tap(self, net: dict):
        if self._connecting_ssid:
            return
        ssid = (net.get("ssid") or "").strip()
        if not ssid:
            return
        if net.get("connected"):
            self._set_ready(ssid)
            self._populate()
            return
        if _is_open(net.get("security") or ""):
            self._connect(ssid, None)
        else:
            self._show_password_dialog(ssid)

    # ── Password dialog ────────────────────────────────────────────────────
    # Positioned in the upper 65 % of the screen so the software keyboard
    # (occupying the lower ~40 %) never covers the input field.
    # When the TextInput gains focus, Window.on_keyboard_height fires and we
    # slide the card up by the reported keyboard height.

    def _show_password_dialog(self, ssid: str):
        overlay = FloatLayout(size_hint=(1, 1))
        with overlay.canvas.before:
            Color(0, 0, 0, 0.72)
            _ov = Rectangle(pos=overlay.pos, size=overlay.size)
        overlay.bind(
            pos=lambda w, *_: setattr(_ov, "pos", w.pos),
            size=lambda w, *_: setattr(_ov, "size", w.size),
        )

        card_w = min(_suh(440), int(Window.width * 0.88))
        card_h = _suv(280)

        card = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            size=(card_w, card_h),
            padding=[_suh(20), _suv(16), _suh(20), _suv(16)],
            spacing=_suv(10),
        )
        with card.canvas.before:
            Color(*COLORS["surface"])
            _cbg = RoundedRectangle(
                pos=card.pos, size=card.size, radius=[BORDER_RADIUS + 2])
            Color(*COLORS["gray_800"])
            _cbo = Line(
                rounded_rectangle=(0, 0, 0, 0, BORDER_RADIUS + 2), width=1.2)
        def _sync_card_bg(*_):
            _cbg.pos = card.pos
            _cbg.size = card.size
            _cbo.rounded_rectangle = (
                card.x, card.y, card.width, card.height, BORDER_RADIUS + 2)
        card.bind(pos=_sync_card_bg, size=_sync_card_bg)

        # Title
        title = Label(
            text=f"Connect to  {ssid}",
            font_size=_suf(FONT_SIZES["title"]),
            bold=True,
            color=COLORS["white"],
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=_suv(30),
        )
        title.bind(size=title.setter("text_size"))
        card.add_widget(title)

        # Network name chip
        ssid_chip = Label(
            text=ssid,
            font_size=_suf(FONT_SIZES["small"]),
            color=COLORS["blue"],
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=_suv(18),
        )
        ssid_chip.bind(size=ssid_chip.setter("text_size"))
        card.add_widget(ssid_chip)

        # Password row: field + show/hide button
        pwd_row = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=_suv(52),
            spacing=_suh(8),
        )
        pwd = _StyledInput(
            hint_text="Password",
            password=True,
            size_hint=(1, None),
            height=_suv(52),
        )
        pwd_row.add_widget(pwd)

        toggle_btn = SecondaryButton(
            text="Show",
            size_hint=(None, 1),
            width=_suh(62),
            font_size=_suf(FONT_SIZES["tiny"]),
        )

        def _toggle_visibility(*_):
            pwd.password = not pwd.password
            toggle_btn.text = "Hide" if not pwd.password else "Show"

        toggle_btn.bind(on_press=_toggle_visibility)
        pwd_row.add_widget(toggle_btn)
        card.add_widget(pwd_row)

        # Hint label
        hint_lbl = Label(
            text="Tip: tap Show to verify your password before connecting.",
            font_size=_suf(FONT_SIZES["tiny"]),
            color=COLORS["gray_600"],
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=_suv(16),
        )
        hint_lbl.bind(size=hint_lbl.setter("text_size"))
        card.add_widget(hint_lbl)

        # Buttons
        btn_row = BoxLayout(
            size_hint=(1, None),
            height=_suv(52),
            spacing=_suh(12),
        )
        cancel_btn = SecondaryButton(text="Cancel", size_hint=(0.42, 1))
        connect_btn = PrimaryButton(text="Connect", size_hint=(0.58, 1))
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(connect_btn)
        card.add_widget(btn_row)

        overlay.add_widget(card)

        # Initial position: upper-mid (well above keyboard zone)
        def _reposition(kbd_h: float = 0.0):
            cy = _center_y_hint(card_h, Window.height, kbd_h)
            card.pos_hint = {"center_x": 0.5, "center_y": cy}
            overlay.do_layout()

        _reposition(0)

        def _on_kbd_height(_win, height):
            _reposition(float(height))

        def _on_focus_kbd(_inst, focused):
            if focused:
                # If keyboard height not reported yet, nudge card up anyway
                kh = getattr(Window, "keyboard_height", 0) or 0
                _reposition(float(kh))

        Window.bind(on_keyboard_height=_on_kbd_height)
        pwd.bind(focus=_on_focus_kbd)

        # Dismiss
        def _dismiss(*_):
            Window.unbind(on_keyboard_height=_on_kbd_height)
            if overlay.parent:
                overlay.parent.remove_widget(overlay)

        def _do_connect(*_):
            pw = pwd.text.strip()
            if not pw:
                self.add_widget(ModalDialog(
                    title="Password required",
                    message="Enter the Wi-Fi password, then tap Connect.",
                    confirm_text="OK",
                    cancel_text="",
                ))
                return
            _dismiss()
            self._connect(ssid, pw)

        cancel_btn.bind(on_press=_dismiss)
        connect_btn.bind(on_press=_do_connect)

        self.add_widget(overlay)
        Clock.schedule_once(lambda *_: pwd.focus_next, 0.1)

    # ── Manual network dialog ─────────────────────────────────────────────

    def _show_manual_dialog(self):
        overlay = FloatLayout(size_hint=(1, 1))
        with overlay.canvas.before:
            Color(0, 0, 0, 0.72)
            _ov = Rectangle(pos=overlay.pos, size=overlay.size)
        overlay.bind(
            pos=lambda w, *_: setattr(_ov, "pos", w.pos),
            size=lambda w, *_: setattr(_ov, "size", w.size),
        )

        card_w = min(_suh(460), int(Window.width * 0.90))
        card_h = _suv(360)

        card = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            size=(card_w, card_h),
            padding=[_suh(20), _suv(16), _suh(20), _suv(16)],
            spacing=_suv(10),
        )
        with card.canvas.before:
            Color(*COLORS["surface"])
            _cbg = RoundedRectangle(
                pos=card.pos, size=card.size, radius=[BORDER_RADIUS + 2])
        card.bind(
            pos=lambda w, *_: setattr(_cbg, "pos", w.pos),
            size=lambda w, *_: setattr(_cbg, "size", w.size),
        )

        card.add_widget(Label(
            text="Add network manually",
            font_size=_suf(FONT_SIZES["title"]),
            bold=True,
            color=COLORS["white"],
            halign="left",
            size_hint=(1, None),
            height=_suv(30),
        ))
        card.add_widget(Label(
            text="Use this when the network is hidden or scan is unavailable.",
            font_size=_suf(FONT_SIZES["tiny"]),
            color=COLORS["gray_500"],
            halign="left",
            size_hint=(1, None),
            height=_suv(16),
        ))

        ssid_in = _StyledInput(hint_text="Network name (SSID)")
        card.add_widget(ssid_in)

        # Security type
        sec_lbl = Label(
            text="Security",
            font_size=_suf(FONT_SIZES["small"]),
            color=COLORS["gray_400"],
            halign="left",
            size_hint=(1, None),
            height=_suv(18),
        )
        sec_lbl.bind(size=sec_lbl.setter("text_size"))
        card.add_widget(sec_lbl)

        spin = Spinner(
            text="WPA2 Personal",
            values=("Open", "WPA2 Personal", "WPA3 Personal", "WEP"),
            size_hint=(1, None),
            height=_suv(46),
            font_size=_suf(FONT_SIZES["small"]),
            background_color=COLORS["surface_light"],
            color=COLORS["white"],
        )
        card.add_widget(spin)

        # Password row
        pwd_row = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=_suv(52),
            spacing=_suh(8),
        )
        pwd_in = _StyledInput(
            hint_text="Password",
            password=True,
            size_hint=(1, None),
            height=_suv(52),
        )
        pwd_row.add_widget(pwd_in)
        show_btn = SecondaryButton(
            text="Show",
            size_hint=(None, 1),
            width=_suh(62),
            font_size=_suf(FONT_SIZES["tiny"]),
        )

        def _toggle_pwd(*_):
            pwd_in.password = not pwd_in.password
            show_btn.text = "Hide" if not pwd_in.password else "Show"

        show_btn.bind(on_press=_toggle_pwd)
        pwd_row.add_widget(show_btn)
        card.add_widget(pwd_row)

        def _on_sec(spinner, txt):
            is_open = txt == "Open"
            pwd_in.disabled = is_open
            pwd_in.opacity = 0.35 if is_open else 1.0
            show_btn.disabled = is_open
            show_btn.opacity = 0.35 if is_open else 1.0

        spin.bind(text=_on_sec)
        _on_sec(spin, spin.text)

        btn_row = BoxLayout(
            size_hint=(1, None),
            height=_suv(52),
            spacing=_suh(12),
        )

        def _dismiss(*_):
            Window.unbind(on_keyboard_height=_on_kbd_height)
            if overlay.parent:
                overlay.parent.remove_widget(overlay)

        def _do_add(*_):
            name = ssid_in.text.strip()
            if not name:
                self.add_widget(ModalDialog(
                    title="Network name required",
                    message="Enter the Wi-Fi network name (SSID).",
                    confirm_text="OK",
                    cancel_text="",
                ))
                return
            sec = spin.text
            if sec != "Open":
                pw = pwd_in.text.strip()
                if not pw:
                    self.add_widget(ModalDialog(
                        title="Password required",
                        message="Enter the network password, or choose Open.",
                        confirm_text="OK",
                        cancel_text="",
                    ))
                    return
                _dismiss()
                self._connect(name, pw)
            else:
                _dismiss()
                self._connect(name, None)

        cancel_btn = SecondaryButton(text="Cancel", size_hint=(0.42, 1))
        connect_btn = PrimaryButton(text="Connect", size_hint=(0.58, 1))
        cancel_btn.bind(on_press=_dismiss)
        connect_btn.bind(on_press=_do_add)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(connect_btn)
        card.add_widget(btn_row)

        overlay.add_widget(card)

        def _reposition(kbd_h: float = 0.0):
            cy = _center_y_hint(card_h, Window.height, kbd_h)
            card.pos_hint = {"center_x": 0.5, "center_y": cy}
            overlay.do_layout()

        _reposition(0)

        def _on_kbd_height(_win, height):
            _reposition(float(height))

        def _on_focus_any(_inst, focused):
            if focused:
                kh = getattr(Window, "keyboard_height", 0) or 0
                _reposition(float(kh))

        Window.bind(on_keyboard_height=_on_kbd_height)
        ssid_in.bind(focus=_on_focus_any)
        pwd_in.bind(focus=_on_focus_any)

        self.add_widget(overlay)

    # ── Connect ───────────────────────────────────────────────────────────

    def _connect(self, ssid: str, password: Optional[str]):
        self._connecting_ssid = ssid
        self._scan_status_lbl.text = f"Connecting to {ssid}…"
        self._populate()

        async def _run():
            result = {"status": "failed", "message": ""}
            try:
                if wifi_nmcli_local.has_nmcli():
                    result = wifi_nmcli_local.connect_wifi_network(ssid, password)
                if result.get("status") != "connected":
                    try:
                        result = await self.backend.connect_wifi(
                            ssid, password=password)
                    except Exception:
                        pass
            except Exception as e:
                result = {"status": "failed", "message": str(e)[:200]}

            ok = result.get("status") == "connected"
            msg = (result.get("message") or "").strip()

            def _done(*_):
                self._connecting_ssid = None
                if ok:
                    self._set_ready(ssid)
                    self._scan_status_lbl.text = f"Connected to {ssid}"
                    self._load_networks(rescan=False)
                else:
                    self._scan_status_lbl.text = "Connection failed"
                    self._populate()
                    self.add_widget(ModalDialog(
                        title="Could not connect",
                        message=(
                            msg or
                            "Check the password and try again.\n"
                            "Make sure the network is in range."
                        ),
                        confirm_text="OK",
                        cancel_text="",
                    ))

            Clock.schedule_once(_done, 0)

        run_async(_run())
