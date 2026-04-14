"""
WiFi Settings Screen – Dark themed (480 × 320)

Compact network list with scan button.
"""

import logging
from typing import Any, Dict, List, Optional
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle
from kivy.clock import Clock
from async_helper import run_async
import wifi_nmcli_local

from screens.base_screen import BaseScreen
from components.status_bar import StatusBar
from components.wifi_network_item import WiFiNetworkItem
from components.button import SecondaryButton, PrimaryButton
from components.modal_dialog import ModalDialog
from config import (
    BORDER_RADIUS,
    COLORS,
    FONT_SIZES,
    SPACING,
    other_screen_horizontal_scale,
    other_screen_vertical_scale,
)

logger = logging.getLogger(__name__)


def _ws_suv(px):
    v = other_screen_vertical_scale()
    return max(1, int(round(float(px) * v)))


def _ws_suh(px):
    h = other_screen_horizontal_scale()
    return max(1, int(round(float(px) * h)))


class _WifiSignalStrip(Widget):
    """Four rising bars: count and color reflect signal strength (0–100) when connected."""

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (_ws_suh(56), _ws_suv(30)))
        super().__init__(**kwargs)
        self._pct = 0
        self._connected = False
        self.bind(pos=self._redraw, size=self._redraw)

    def set_state(self, connected: bool, signal_pct: int) -> None:
        self._connected = bool(connected)
        self._pct = max(0, min(100, int(signal_pct)))
        self._redraw()

    def _bar_color(self):
        if not self._connected:
            return COLORS["gray_600"]
        p = self._pct
        if p >= 70:
            return COLORS["green"]
        if p >= 45:
            return COLORS["yellow"]
        if p >= 25:
            return COLORS["yellow"]
        return COLORS["red"]

    def _lit_count(self) -> int:
        if not self._connected:
            return 0
        p = self._pct
        if p >= 80:
            return 4
        if p >= 55:
            return 3
        if p >= 30:
            return 2
        if p >= 10:
            return 1
        return 1

    def _redraw(self, *_args):
        self.canvas.clear()
        bar_w = _ws_suh(9)
        gap = _ws_suh(3)
        heights = [_ws_suv(7), _ws_suv(12), _ws_suv(17), _ws_suv(22)]
        x0 = self.x + _ws_suh(2)
        bottom = self.y + _ws_suv(3)
        lit = self._lit_count()
        active_color = self._bar_color()
        dim = COLORS["gray_800"]

        with self.canvas:
            for i in range(4):
                h = heights[i]
                if self._connected and i < lit:
                    Color(*active_color)
                else:
                    Color(*dim)
                RoundedRectangle(
                    pos=(x0 + i * (bar_w + gap), bottom),
                    size=(bar_w, h),
                    radius=[max(1, _ws_suv(2))],
                )


class WiFiScreen(BaseScreen):
    """WiFi settings – dark theme."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.networks = []
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation='vertical')
        self.make_dark_bg(root)

        self.status_bar = StatusBar(
            status_text='WiFi',
            device_name='WiFi',
            back_button=True,
            on_back=self.go_back,
            show_settings=False,
        )
        root.add_widget(self.status_bar)

        content = BoxLayout(
            orientation='horizontal',
            padding=self.suh(SPACING['screen_padding']),
            spacing=self.suv(SPACING['section_spacing']),
        )

        left = BoxLayout(
            orientation='vertical',
            size_hint=(0.7, 1),
            spacing=self.suv(SPACING['button_spacing']),
        )

        status_row = BoxLayout(
            orientation='horizontal',
            size_hint=(1, None),
            height=self.suv(48),
            spacing=self.suh(12),
        )
        self.signal_strip = _WifiSignalStrip()
        status_row.add_widget(self.signal_strip)
        status_col = BoxLayout(orientation='vertical', spacing=self.suv(2))
        self.status_title = Label(
            text='Wi‑Fi status',
            font_size=self.suf(FONT_SIZES['medium']),
            bold=True,
            color=COLORS['white'],
            halign='left',
            valign='bottom',
            size_hint=(1, None),
            height=self.suv(22),
        )
        self.status_title.bind(size=self.status_title.setter('text_size'))
        status_col.add_widget(self.status_title)
        self.status_detail = Label(
            text='Loading…',
            font_size=self.suf(FONT_SIZES['small']),
            color=COLORS['gray_400'],
            halign='left',
            valign='top',
            size_hint=(1, None),
            height=self.suv(36),
        )
        self.status_detail.bind(size=self.status_detail.setter('text_size'))
        status_col.add_widget(self.status_detail)
        status_row.add_widget(status_col)
        left.add_widget(status_row)

        scroll = ScrollView(do_scroll_x=False)
        self.networks_container = GridLayout(
            cols=1, spacing=self.suv(SPACING['list_item_spacing']), size_hint_y=None)
        self.networks_container.bind(
            minimum_height=self.networks_container.setter('height'))
        scroll.add_widget(self.networks_container)
        left.add_widget(scroll)

        content.add_widget(left)

        right = BoxLayout(orientation='vertical', size_hint=(0.3, 1),
                          spacing=self.suv(SPACING['button_spacing']))
        from kivy.uix.widget import Widget
        right.add_widget(Widget(size_hint=(1, 0.6)))
        scan_btn = SecondaryButton(text='SCAN', size_hint=(1, 0.35))
        scan_btn.bind(on_press=lambda _: self._load_networks(rescan=True))
        right.add_widget(scan_btn)
        content.add_widget(right)

        root.add_widget(content)

        footer = self.build_footer()
        root.add_widget(footer)

        self.add_widget(root)

    def on_enter(self):
        self._load_networks(rescan=True)

    def _load_networks(self, rescan: bool = False):
        async def _load():
            nets: list = []
            info: dict = {}
            try:
                if wifi_nmcli_local.has_nmcli():
                    nets = wifi_nmcli_local.scan_wifi_networks(rescan=rescan)
            except Exception as e:
                logger.warning("Local WiFi scan failed, trying backend: %s", e)
                nets = []
            if not nets:
                try:
                    raw = await self.backend.get_wifi_networks()
                    if isinstance(raw, list):
                        nets = raw
                except Exception as e:
                    logger.warning("WiFi scan (backend) failed: %s", e)
                    nets = []
            for n in nets:
                if not isinstance(n, dict):
                    continue
                if "signal_strength" not in n and n.get("signal") is not None:
                    try:
                        n["signal_strength"] = int(n["signal"])
                    except (TypeError, ValueError):
                        n["signal_strength"] = 0
            try:
                info = await self.backend.get_system_info()
            except Exception as e:
                logger.debug("system info for WiFi screen: %s", e)
                info = {}
            self.networks = nets

            def _apply(_dt):
                self._populate(nets, info)

            Clock.schedule_once(_apply, 0)

        run_async(_load())

    def _populate(self, networks: Optional[List[Dict[str, Any]]] = None, info: Optional[Dict[str, Any]] = None):
        nets = networks if networks is not None else getattr(self, "networks", []) or []
        info = info or {}
        ssid = (info.get("wifi_ssid") or "").strip()
        sig = int(info.get("wifi_signal") or 0)
        ip = (info.get("ip_address") or "").strip()
        connected = bool(ssid)

        self.signal_strip.set_state(connected, sig if connected else 0)
        if connected:
            self.status_title.text = "Connected"
            self.status_detail.text = f"{ssid}\nSignal {sig}% · IP {ip or '—'}"
        else:
            self.status_title.text = "Not connected"
            self.status_detail.text = "Select a network below or tap SCAN."

        self.networks_container.clear_widgets()
        if not nets:
            hint = Label(
                text='No networks in list. Tap SCAN or check device Wi‑Fi.',
                font_size=self.suf(FONT_SIZES['small']),
                color=COLORS['gray_500'],
                halign='left',
                valign='top',
                size_hint_y=None,
                height=self.suv(56),
            )
            hint.bind(size=hint.setter('text_size'))
            self.networks_container.add_widget(hint)
            return

        for net in nets:
            n = dict(net) if isinstance(net, dict) else {}
            if "signal_strength" not in n:
                n["signal_strength"] = int(n.get("signal") or 0)
            item = WiFiNetworkItem(network=n)
            item.bind(on_press=self._on_network)
            self.networks_container.add_widget(item)

    def _on_network(self, instance):
        if instance.network.get('connected'):
            return
        net = instance.network
        security = (net.get('security') or '').lower()
        if security and security != 'open' and security != '--':
            self._show_password_dialog(net['ssid'])
        else:
            self._connect_to_network(net['ssid'], password=None)

    def _show_password_dialog(self, ssid):
        from kivy.uix.floatlayout import FloatLayout
        from kivy.graphics import Color, RoundedRectangle, Rectangle

        overlay = FloatLayout()
        with overlay.canvas.before:
            Color(*COLORS['overlay'])
            _bg = Rectangle(pos=overlay.pos, size=overlay.size)
        overlay.bind(
            pos=lambda w, v: setattr(_bg, 'pos', w.pos),
            size=lambda w, v: setattr(_bg, 'size', w.size),
        )

        card = BoxLayout(
            orientation='vertical',
            size_hint=(None, None),
            size=(self.suh(360), self.suv(220)),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            padding=self.suh(16),
            spacing=self.suv(10),
        )
        with card.canvas.before:
            Color(*COLORS['surface'])
            _cbg = RoundedRectangle(pos=card.pos, size=card.size, radius=[BORDER_RADIUS])
        card.bind(
            pos=lambda w, v: setattr(_cbg, 'pos', w.pos),
            size=lambda w, v: setattr(_cbg, 'size', w.size),
        )

        title = Label(
            text=f'Connect to {ssid}',
            font_size=self.suf(FONT_SIZES['title']), bold=True,
            color=COLORS['white'], halign='left',
            size_hint=(1, None), height=self.suv(28),
        )
        title.bind(size=title.setter('text_size'))
        card.add_widget(title)

        hint = Label(
            text='Enter WiFi password:',
            font_size=self.suf(FONT_SIZES['small']), color=COLORS['gray_400'],
            halign='left', size_hint=(1, None), height=self.suv(20),
        )
        hint.bind(size=hint.setter('text_size'))
        card.add_widget(hint)

        pwd_input = TextInput(
            hint_text='Password',
            password=True,
            multiline=False,
            font_size=self.suf(FONT_SIZES['body']),
            size_hint=(1, None), height=self.suv(40),
            background_color=COLORS['background'],
            foreground_color=COLORS['white'],
            cursor_color=COLORS['blue'],
        )
        card.add_widget(pwd_input)

        btn_row = BoxLayout(
            size_hint=(1, None),
            height=self.suv(50),
            spacing=self.suv(SPACING['button_spacing']),
        )
        cancel_btn = SecondaryButton(text='CANCEL', size_hint=(0.5, 1))
        connect_btn = PrimaryButton(text='CONNECT', size_hint=(0.5, 1))

        def _dismiss(*_a):
            if overlay.parent:
                overlay.parent.remove_widget(overlay)

        def _do_connect(*_a):
            password = pwd_input.text.strip()
            _dismiss()
            self._connect_to_network(ssid, password=password or None)

        cancel_btn.bind(on_press=_dismiss)
        connect_btn.bind(on_press=_do_connect)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(connect_btn)
        card.add_widget(btn_row)

        overlay.add_widget(card)
        self.add_widget(overlay)

    def _connect_to_network(self, ssid, password=None):
        async def _connect():
            result: dict = {"status": "failed", "message": ""}
            try:
                if wifi_nmcli_local.has_nmcli():
                    result = wifi_nmcli_local.connect_wifi_network(ssid, password)
                if result.get("status") != "connected":
                    try:
                        result = await self.backend.connect_wifi(
                            ssid, password=password
                        )
                    except Exception as be:
                        logger.warning("WiFi connect (backend): %s", be)
                        result = {"status": "failed", "message": str(be)[:200]}
            except Exception as e:
                logger.warning("WiFi connect: %s", e)
                result = {"status": "failed", "message": str(e)[:200]}

            def _done(_dt):
                if result.get("status") == "connected":
                    self._load_networks(rescan=False)
                else:
                    msg = (result.get("message") or "").strip() or (
                        "Could not connect. Check the password and NetworkManager "
                        "permissions on this device."
                    )
                    self.add_widget(
                        ModalDialog(
                            title="Could not connect",
                            message=msg[:400],
                            confirm_text="OK",
                            cancel_text="",
                        )
                    )

            Clock.schedule_once(_done, 0)

        run_async(_connect())
