"""Executive briefing screen for the device UI."""

from __future__ import annotations

import re

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from async_helper import run_async
from components.button import PrimaryButton, SecondaryButton
from config import COLORS, FONT_SIZES, SPACING, display_now
from screens.base_screen import BaseScreen

_BULLET_RE = re.compile(r"^\s*[-•]\s+")


def _clean_for_device(text: str) -> str:
    """Keep briefing readable on a room display; no markdown decoration."""
    t = (text or "").strip()
    if not t:
        return "No briefing content returned."
    t = t.replace("**", "")
    lines = []
    for raw in t.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        line = _BULLET_RE.sub("• ", line)
        lines.append(line)
    # Collapse excessive blank lines.
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out[:4500]


class BriefingScreen(BaseScreen):
    """Calm, executive-readable briefing view."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loading = False
        self._briefing_text = ""
        self._build_ui()

    def _build_ui(self):
        sv = self.suv
        sf = self.suf
        root = BoxLayout(
            orientation="vertical",
            padding=[sv(SPACING["screen_padding"]), sv(14), sv(SPACING["screen_padding"]), 0],
            spacing=sv(12),
        )
        self.make_dark_bg(root)

        header = BoxLayout(orientation="horizontal", size_hint=(1, None), height=sv(64), spacing=sv(10))
        title_col = BoxLayout(orientation="vertical", spacing=sv(2))
        self.kicker = Label(
            text="EXECUTIVE BRIEFING",
            font_size=sf(FONT_SIZES["tiny"]),
            color=COLORS["blue"],
            bold=True,
            halign="left",
            valign="bottom",
            size_hint=(1, 0.38),
        )
        self.kicker.bind(size=self.kicker.setter("text_size"))
        title_col.add_widget(self.kicker)
        self.title = Label(
            text="Start your day calmly",
            font_size=sf(FONT_SIZES["large"]),
            color=COLORS["white"],
            bold=True,
            halign="left",
            valign="top",
            size_hint=(1, 0.62),
        )
        self.title.bind(size=self.title.setter("text_size"))
        title_col.add_widget(self.title)
        header.add_widget(title_col)

        back = SecondaryButton(text="Back", size_hint=(None, None), width=sv(110), height=sv(52))
        back.bind(on_release=lambda *_: self.go_back())
        header.add_widget(back)
        root.add_widget(header)

        card = BoxLayout(orientation="vertical", padding=[sv(18), sv(16)], spacing=sv(10))
        with card.canvas.before:
            Color(*COLORS["surface"])
            self._card_bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[sv(24)])
        card.bind(pos=lambda w, *_: setattr(self._card_bg, "pos", w.pos))
        card.bind(size=lambda w, *_: setattr(self._card_bg, "size", w.size))

        self.status_label = Label(
            text="Preparing your briefing…",
            font_size=sf(FONT_SIZES["body"]),
            color=COLORS["gray_300"],
            size_hint=(1, None),
            height=sv(28),
            halign="left",
            valign="middle",
        )
        self.status_label.bind(size=self.status_label.setter("text_size"))
        card.add_widget(self.status_label)

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self.briefing_label = Label(
            text="",
            markup=False,
            font_size=sf(FONT_SIZES["body"]),
            color=COLORS["white"],
            halign="left",
            valign="top",
            size_hint=(1, None),
            line_height=1.18,
        )
        self.briefing_label.bind(
            width=lambda w, width: setattr(w, "text_size", (width, None)),
            texture_size=lambda w, size: setattr(w, "height", size[1]),
        )
        scroll.add_widget(self.briefing_label)
        card.add_widget(scroll)
        root.add_widget(card)

        actions = BoxLayout(orientation="horizontal", size_hint=(1, None), height=sv(62), spacing=sv(12))
        self.refresh_btn = PrimaryButton(text="Refresh Briefing", size_hint=(0.58, 1))
        self.refresh_btn.bind(on_release=lambda *_: self.load_briefing(force=True))
        actions.add_widget(self.refresh_btn)
        meetings_btn = SecondaryButton(text="Meetings", size_hint=(0.42, 1))
        meetings_btn.bind(on_release=lambda *_: self.goto("meetings", transition="slide_left"))
        actions.add_widget(meetings_btn)
        root.add_widget(actions)

        hint = Label(
            text="Uses Calendar, Gmail, and MeetingBox memory. Email/calendar writes still require approval on web.",
            font_size=sf(FONT_SIZES["tiny"]),
            color=COLORS["gray_500"],
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=sv(24),
        )
        hint.bind(size=hint.setter("text_size"))
        root.add_widget(hint)
        root.add_widget(self.build_footer())
        self.add_widget(root)

    def on_enter(self):
        self.title.text = f"{display_now().strftime('%A')} briefing"
        if not self._briefing_text:
            self.load_briefing(force=False)

    def load_briefing(self, force: bool = False):
        if self._loading:
            return
        if self._briefing_text and not force:
            return
        self._loading = True
        self.refresh_btn.disabled = True
        self.status_label.text = "Preparing your briefing…"
        self.briefing_label.text = ""

        async def _fetch():
            try:
                data = await self.backend.post_assistant_intent(
                    "Give me my executive morning briefing for today."
                )
                text = _clean_for_device(data.get("assistant_message") or "")
                agent = data.get("routed_agent_id") or "assistant"

                def _apply(_dt):
                    self._briefing_text = text
                    self.status_label.text = f"Ready · {str(agent).replace('_', ' ')}"
                    self.briefing_label.text = text
                    self._loading = False
                    self.refresh_btn.disabled = False

                Clock.schedule_once(_apply, 0)
            except Exception as exc:
                msg = str(exc).strip()[:240] or "Unable to reach the assistant."

                def _error(_dt):
                    self.status_label.text = "Briefing unavailable"
                    self.briefing_label.text = (
                        "I couldn't prepare the briefing on this device yet.\n\n"
                        f"Reason: {msg}\n\n"
                        "Check that this device is paired and the backend is reachable."
                    )
                    self._loading = False
                    self.refresh_btn.disabled = False

                Clock.schedule_once(_error, 0)

        run_async(_fetch())
