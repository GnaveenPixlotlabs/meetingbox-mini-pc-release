"""
Shared Figma-aligned Wi‑Fi list UI (onboarding + home Wi‑Fi screen).

Background #0B0E14, bordered list card, network rows, add/rescan row, footer buttons.
"""

from __future__ import annotations

from pathlib import Path

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from config import BORDER_RADIUS, COLORS, FONT_SIZES

# Figma frame background #0B0E14; accent blue ~#3B82F6
FIGMA_BG = (11 / 255, 14 / 255, 20 / 255, 1)
FIGMA_ACCENT = (59 / 255, 130 / 255, 246 / 255, 1)
SUBTITLE_GRAY = (0.61, 0.64, 0.69, 1)  # #9CA3AF


def _sv() -> float:
    from config import other_screen_vertical_scale

    return other_screen_vertical_scale()


def _sh() -> float:
    from config import other_screen_horizontal_scale

    return other_screen_horizontal_scale()


def suv(px: float) -> int:
    return max(1, int(round(float(px) * _sv())))


def suh(px: float) -> int:
    return max(1, int(round(float(px) * _sh())))


def suf(fs: float) -> int:
    return max(6, int(round(float(fs) * _sv())))


def format_wifi_security(sec: str) -> str:
    """Security line as in Figma: OPEN, WPA2 PERSONAL, WPA2 ENTERPRISE, …"""
    s = (sec or "").strip().upper().replace("_", " ")
    if not s or s in ("--", "NONE", "OPEN"):
        return "OPEN"
    if "ENTERPRISE" in s or "8021X" in s or "EAP" in s:
        if "WPA3" in s:
            return "WPA3 ENTERPRISE"
        return "WPA2 ENTERPRISE"
    if "WPA3" in s:
        return "WPA3 PERSONAL"
    if "WPA2" in s or "WPA" in s:
        return "WPA2 PERSONAL"
    if "WEP" in s:
        return "WEP"
    return s[:24]


def is_open_wifi(sec: str) -> bool:
    s = (sec or "").lower().strip()
    return not s or s in ("open", "--", "none", "")


class FigmaSignalBars(Widget):
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
        bw = suh(self._BAR_W)
        gap = suh(self._GAP)
        x0 = self.x + suh(2)
        bot = self.y + suv(2)
        radius = max(1, suv(2))

        with self.canvas:
            for i, h_raw in enumerate(self._HEIGHTS):
                h = suv(h_raw)
                Color(*(active if (self._connected and i < lit) else dim))
                RoundedRectangle(
                    pos=(x0 + i * (bw + gap), bot),
                    size=(bw, h),
                    radius=[radius],
                )


class FigmaConnectingBadge(Widget):
    """Blue circle with white Wi‑Fi arcs (Figma “connecting” row)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        super().__init__(**kwargs)
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_once(lambda *_: self._draw(), 0)

    def _draw(self, *_):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height) / 2 - max(1, suh(2))
        if r < 4:
            return
        with self.canvas:
            Color(*FIGMA_ACCENT)
            Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2))
            Color(1, 1, 1, 1)
            for scale in (0.42, 0.68, 0.94):
                rr = r * 0.5 * scale
                Line(
                    circle=(cx, cy - rr * 0.1, rr, 118, 242),
                    width=max(1.0, suh(1.5)),
                )


class FigmaListDivider(Widget):
    """Full-width hairline between network rows."""

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", max(1, suv(1)))
        super().__init__(**kwargs)
        self.bind(pos=self._sync, size=self._sync)
        Clock.schedule_once(lambda *_: self._sync(), 0)

    def _sync(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(*COLORS["gray_800"])
            Rectangle(pos=self.pos, size=self.size)


class FigmaIconHit(ButtonBehavior, BoxLayout):
    """Small tappable area (e.g. rescan) that does not use the row’s main press."""


class FigmaWifiNetworkRow(ButtonBehavior, BoxLayout):
    """One tappable row: SSID, security caps, signal or connecting badge, lock/refresh."""

    _H = 76

    def __init__(
        self,
        net: dict,
        connecting_ssid: str,
        parent_screen,
        **kwargs,
    ):
        self.net = net
        self.parent_screen = parent_screen
        ssid = (net.get("ssid") or "").strip()
        sec = net.get("security") or ""
        connected = bool(net.get("connected"))
        signal = int(net.get("signal_strength") or 0)
        busy = (connecting_ssid or "") == ssid and not connected

        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", suv(self._H))
        kwargs.setdefault("padding", [suh(16), suv(10), suh(14), suv(10)])
        kwargs.setdefault("spacing", suh(12))
        super().__init__(**kwargs)

        with self.canvas.before:
            self._bg_color = Color(0, 0, 0, 0)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda w, *_: setattr(self._bg, "pos", w.pos),
            size=lambda w, *_: setattr(self._bg, "size", w.size),
        )

        left_wrap = AnchorLayout(
            anchor_x="center",
            anchor_y="center",
            size_hint=(None, 1),
            width=suh(52),
        )
        if busy:
            left_wrap.add_widget(FigmaConnectingBadge(size=(suh(46), suv(46))))
            self._dots = 0
            self._spinner_event = Clock.schedule_interval(self._tick_connecting, 0.45)
        else:
            left_wrap.add_widget(
                FigmaSignalBars(
                    signal=signal,
                    connected=connected,
                    size=(suh(32), suv(22)),
                )
            )
        self.add_widget(left_wrap)

        mid = BoxLayout(orientation="vertical", size_hint=(1, 1), spacing=suv(4))

        ssid_lbl = Label(
            text=ssid or "(hidden network)",
            font_size=suf(FONT_SIZES["medium"]),
            bold=True,
            color=COLORS["white"],
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=suv(22),
        )
        ssid_lbl.bind(size=ssid_lbl.setter("text_size"))
        mid.add_widget(ssid_lbl)

        if busy:
            sec_txt = "Connecting."
            sec_color = FIGMA_ACCENT
        elif connected:
            sec_txt = "Connected"
            sec_color = COLORS["green"]
        else:
            sec_txt = format_wifi_security(sec)
            sec_color = SUBTITLE_GRAY if not is_open_wifi(sec) else COLORS["gray_500"]

        sec_lbl = Label(
            text=sec_txt,
            font_size=suf(FONT_SIZES["small"]),
            color=sec_color,
            halign="left",
            valign="top",
            size_hint=(1, None),
            height=suv(18),
        )
        sec_lbl.bind(size=sec_lbl.setter("text_size"))
        mid.add_widget(sec_lbl)
        self._sec_lbl = sec_lbl
        self.add_widget(mid)

        right = BoxLayout(
            orientation="horizontal",
            size_hint=(None, 1),
            width=suh(44),
            spacing=0,
        )
        if busy:

            def _rescan(*_a):
                self.parent_screen._load_networks(rescan=True)

            hit = FigmaIconHit(orientation="vertical", size_hint=(1, 1))
            rlab = Label(
                text="\u21bb",
                font_size=suf(24),
                color=COLORS["gray_500"],
                halign="center",
                valign="middle",
            )
            rlab.bind(size=rlab.setter("text_size"))
            hit.add_widget(rlab)
            hit.bind(on_press=_rescan)
            right.add_widget(hit)
        elif not is_open_wifi(sec):
            lock = Label(
                text="\U0001f512",
                font_size=suf(16),
                color=COLORS["gray_600"],
                halign="center",
                valign="middle",
                size_hint=(1, 1),
            )
            lock.bind(size=lock.setter("text_size"))
            right.add_widget(lock)
        self.add_widget(right)

    def _tick_connecting(self, *_):
        if not hasattr(self, "_sec_lbl"):
            return
        self._dots = (self._dots + 1) % 4
        self._sec_lbl.text = "Connecting" + "." * self._dots

    def cleanup(self):
        if hasattr(self, "_spinner_event"):
            self._spinner_event.cancel()

    def on_press(self):
        self._bg_color.rgba = (*COLORS["surface_light"][:3], 0.35)

    def on_release(self):
        self._bg_color.rgba = (0, 0, 0, 0)


class FigmaTextLink(ButtonBehavior, Label):
    def on_press(self):
        self.opacity = 0.5

    def on_release(self):
        self.opacity = 1.0


def build_figma_wifi_column(logo_path: str) -> dict:
    """
    Build the main Figma column (brand → list → actions → footer).

    Returns dict keys: root, scan_status_lbl, scroll, list_grid, next_btn, back_btn,
    card_bg, card_outline, list_card (container), add_link, rescan_btn.
    """
    root = BoxLayout(
        orientation="vertical",
        padding=[suh(20), suv(12), suh(20), suv(12)],
        spacing=0,
        size_hint=(1, 1),
    )
    with root.canvas.before:
        Color(*FIGMA_BG)
        root_bg = Rectangle(pos=root.pos, size=root.size)
    root.bind(
        pos=lambda w, *_: setattr(root_bg, "pos", w.pos),
        size=lambda w, *_: setattr(root_bg, "size", w.size),
    )

    brand = BoxLayout(
        orientation="horizontal",
        size_hint=(1, None),
        height=suv(40),
        spacing=suh(8),
    )
    if logo_path and Path(logo_path).exists():
        brand.add_widget(
            Image(
                source=logo_path,
                size_hint=(None, 1),
                width=suh(32),
                fit_mode="contain",
            )
        )
    brand_lbl = Label(
        text="MeetingBox AI",
        font_size=suf(FONT_SIZES["medium"]),
        bold=False,
        color=COLORS["white"],
        halign="left",
        valign="middle",
        size_hint=(1, 1),
    )
    brand_lbl.bind(size=brand_lbl.setter("text_size"))
    brand.add_widget(brand_lbl)
    root.add_widget(brand)

    root.add_widget(Widget(size_hint=(1, None), height=suv(8)))

    title_main = Label(
        text="Connect to WiFi",
        font_size=suf(FONT_SIZES["large"]),
        bold=True,
        color=COLORS["white"],
        halign="left",
        valign="middle",
        size_hint=(1, None),
        height=suv(30),
    )
    title_main.bind(size=title_main.setter("text_size"))
    root.add_widget(title_main)

    root.add_widget(Widget(size_hint=(1, None), height=suv(6)))

    sub = Label(
        text="Required for calendar sync and email delivery.",
        font_size=suf(FONT_SIZES["small"]),
        color=SUBTITLE_GRAY,
        halign="left",
        valign="middle",
        size_hint=(1, None),
        height=suv(22),
    )
    sub.bind(size=sub.setter("text_size"))
    root.add_widget(sub)

    root.add_widget(Widget(size_hint=(1, None), height=suv(8)))

    scan_status_lbl = Label(
        text="",
        font_size=suf(FONT_SIZES["small"]),
        bold=False,
        color=COLORS["gray_500"],
        halign="left",
        valign="middle",
        size_hint=(1, None),
        height=suv(18),
    )
    scan_status_lbl.bind(size=scan_status_lbl.setter("text_size"))
    root.add_widget(scan_status_lbl)

    root.add_widget(Widget(size_hint=(1, None), height=suv(6)))

    list_card = BoxLayout(
        orientation="vertical",
        size_hint=(1, 1),
        spacing=0,
    )
    with list_card.canvas.before:
        Color(*COLORS["surface"])
        card_bg = RoundedRectangle(
            pos=list_card.pos, size=list_card.size,
            radius=[BORDER_RADIUS])
    with list_card.canvas.after:
        Color(*FIGMA_ACCENT)
        card_outline = Line(width=1.25)

    def _list_card_geom(*_a):
        card_bg.pos = list_card.pos
        card_bg.size = list_card.size
        inset = max(1.0, float(suh(1)))
        card_outline.rounded_rectangle = (
            list_card.x + inset,
            list_card.y + inset,
            max(0.0, list_card.width - 2 * inset),
            max(0.0, list_card.height - 2 * inset),
            BORDER_RADIUS,
        )

    list_card.bind(pos=_list_card_geom, size=_list_card_geom)
    Clock.schedule_once(_list_card_geom, 0)

    scroll = ScrollView(
        do_scroll_x=False,
        size_hint=(1, 1),
        bar_width=suh(4),
        bar_color=[*FIGMA_ACCENT[:3], 0.55],
        bar_inactive_color=[*COLORS["gray_700"][:3], 0.4],
    )
    list_grid = GridLayout(
        cols=1,
        spacing=0,
        size_hint_y=None,
        padding=[suh(12), suv(10), suh(12), suv(10)],
    )
    list_grid.bind(minimum_height=list_grid.setter("height"))
    scroll.add_widget(list_grid)
    list_card.add_widget(scroll)
    root.add_widget(list_card)

    actions = BoxLayout(
        orientation="horizontal",
        size_hint=(1, None),
        height=suv(42),
        spacing=suh(8),
        padding=[0, suv(6), 0, 0],
    )
    add_link = FigmaTextLink(
        text="+ Add Network Manually",
        font_size=suf(FONT_SIZES["medium"]),
        color=FIGMA_ACCENT,
        halign="left",
        valign="middle",
        size_hint=(None, 1),
        width=suh(260),
    )
    add_link.bind(size=add_link.setter("text_size"))
    actions.add_widget(add_link)
    actions.add_widget(Widget(size_hint=(1, 1)))
    rescan_btn = FigmaTextLink(
        text="\u21bb  Rescan",
        font_size=suf(FONT_SIZES["medium"]),
        color=COLORS["gray_500"],
        halign="right",
        valign="middle",
        size_hint=(None, 1),
        width=suh(120),
    )
    rescan_btn.bind(size=rescan_btn.setter("text_size"))
    actions.add_widget(rescan_btn)
    root.add_widget(actions)

    root.add_widget(Widget(size_hint=(1, None), height=suv(6)))

    from components.button import PrimaryButton, SecondaryButton

    foot = BoxLayout(
        orientation="horizontal",
        size_hint=(1, None),
        height=suv(56),
        spacing=suh(12),
    )
    back_btn = SecondaryButton(
        text="Back",
        size_hint=(0.5, 1),
        font_size=suf(FONT_SIZES["medium"]),
    )
    foot.add_widget(back_btn)

    next_btn = PrimaryButton(
        text="Next",
        size_hint=(0.5, 1),
        font_size=suf(FONT_SIZES["medium"]),
    )
    foot.add_widget(next_btn)
    root.add_widget(foot)

    return {
        "root": root,
        "scan_status_lbl": scan_status_lbl,
        "scroll": scroll,
        "list_grid": list_grid,
        "next_btn": next_btn,
        "back_btn": back_btn,
        "card_bg": card_bg,
        "card_outline": card_outline,
        "list_card": list_card,
        "add_link": add_link,
        "rescan_btn": rescan_btn,
    }
