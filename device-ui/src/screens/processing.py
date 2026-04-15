"""
Processing screen aligned to Figma "Processing Complete (S-05)".

Flow:
- User presses End Meeting -> app navigates here.
- While backend runs, stage list updates from progress/status events.
- When summary is ready, CTA enables and user can open meeting summary.
"""

import logging
import time

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from config import COLORS, DISPLAY_WIDTH, FONT_SIZES
from screens.base_screen import BaseScreen

logger = logging.getLogger(__name__)

_BG = (13 / 255.0, 17 / 255.0, 23 / 255.0, 1)
_BORDER = (30 / 255.0, 41 / 255.0, 59 / 255.0, 1)
_MUTED = (148 / 255.0, 163 / 255.0, 184 / 255.0, 1)
_SUCCESS = (34 / 255.0, 197 / 255.0, 94 / 255.0, 1)
_CTA = (74 / 255.0, 143 / 255.0, 217 / 255.0, 1)


class _StageRow(BoxLayout):
    """Single timeline stage row with indicator, optional connector, title, subtitle."""

    def __init__(self, title: str, subtitle: str, show_connector: bool, parent_screen, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint", (1, None))
        kwargs.setdefault("height", parent_screen.suv(82 if show_connector else 52))
        kwargs.setdefault("spacing", parent_screen.suh(14))
        super().__init__(**kwargs)
        self._show_connector = show_connector
        self._state = "pending"  # pending | active | done
        self._screen = parent_screen

        left = BoxLayout(
            orientation="vertical",
            size_hint=(None, 1),
            width=parent_screen.suh(24),
            spacing=0,
        )
        self.dot = Label(
            text="○",
            font_size=parent_screen.suf(18),
            color=_MUTED,
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=parent_screen.suv(22),
        )
        self.dot.bind(size=self.dot.setter("text_size"))
        left.add_widget(self.dot)
        if show_connector:
            self.connector = Widget(size_hint=(1, 1))
            with self.connector.canvas:
                Color(*_BORDER)
                self._connector_line = Rectangle(pos=self.connector.pos, size=self.connector.size)
            self.connector.bind(
                pos=lambda w, *_: setattr(self._connector_line, "pos", (w.center_x - 0.5, w.y + parent_screen.suv(2))),
                size=lambda w, *_: setattr(
                    self._connector_line, "size", (1, max(1, w.height - parent_screen.suv(8)))
                ),
            )
            left.add_widget(self.connector)
        self.add_widget(left)

        txt = BoxLayout(orientation="vertical", size_hint=(1, 1), spacing=parent_screen.suv(2))
        self.title = Label(
            text=title,
            font_size=parent_screen.suf(16),
            bold=True,
            color=COLORS["white"],
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=parent_screen.suv(24),
        )
        self.title.bind(size=self.title.setter("text_size"))
        txt.add_widget(self.title)
        self.subtitle = Label(
            text=subtitle,
            font_size=parent_screen.suf(FONT_SIZES["small"] + 1),
            color=_MUTED,
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=parent_screen.suv(22),
        )
        self.subtitle.bind(size=self.subtitle.setter("text_size"))
        txt.add_widget(self.subtitle)
        self.add_widget(txt)

    def set_state(self, state: str):
        self._state = state
        if state == "done":
            self.dot.text = "●"
            self.dot.color = _SUCCESS
            if self._show_connector:
                self._connector_line.size = (1, self._connector_line.size[1])
        elif state == "active":
            self.dot.text = "◉"
            self.dot.color = _SUCCESS
        else:
            self.dot.text = "○"
            self.dot.color = _MUTED


class ProcessingScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._started_ts = None
        self._meeting_id = None
        self._summary_data = None
        self._summary_ready = False
        self._pulse_event = None
        self._pulse_alpha = 0.20
        self._pulse_dir = 1
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*_BG)
            self._bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda w, *_: setattr(self._bg_rect, "pos", w.pos),
            size=lambda w, *_: setattr(self._bg_rect, "size", w.size),
        )

        # Header
        header = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=self.suv(58),
            padding=[self.suh(20), self.suv(10), self.suh(20), self.suv(10)],
        )
        with header.canvas.after:
            Color(*_BORDER)
            self._header_line = Rectangle(pos=(header.x, header.y), size=(header.width, 1))
        header.bind(
            pos=lambda w, *_: setattr(self._header_line, "pos", (w.x, w.y)),
            size=lambda w, *_: setattr(self._header_line, "size", (w.width, 1)),
        )
        left = BoxLayout(orientation="horizontal", size_hint=(None, 1), width=self.suh(200), spacing=self.suh(8))
        logo = Label(
            text="◈",
            font_size=self.suf(18),
            color=_CTA,
            halign="center",
            valign="middle",
            size_hint=(None, 1),
            width=self.suh(20),
        )
        logo.bind(size=logo.setter("text_size"))
        left.add_widget(logo)
        brand = Label(
            text="MeetingBox",
            font_size=self.suf(FONT_SIZES["medium"]),
            bold=True,
            color=COLORS["white"],
            halign="left",
            valign="middle",
            size_hint=(1, 1),
        )
        brand.bind(size=brand.setter("text_size"))
        left.add_widget(brand)
        header.add_widget(left)
        header.add_widget(Widget())
        right = BoxLayout(orientation="horizontal", size_hint=(None, 1), width=self.suh(132), spacing=self.suh(8))
        for sym in ("⚙", "?", "◉"):
            b = Label(
                text=sym,
                font_size=self.suf(FONT_SIZES["small"] + 1),
                color=(200 / 255.0, 213 / 255.0, 230 / 255.0, 1),
                halign="center",
                valign="middle",
                size_hint=(None, None),
                size=(self.suh(34), self.suv(34)),
            )
            b.bind(size=b.setter("text_size"))
            with b.canvas.before:
                Color(*COLORS["surface"])
                rr = RoundedRectangle(pos=b.pos, size=b.size, radius=[999])
            b.bind(
                pos=lambda w, _, r=rr: setattr(r, "pos", w.pos),
                size=lambda w, _, r=rr: setattr(r, "size", w.size),
            )
            right.add_widget(b)
        header.add_widget(right)
        root.add_widget(header)

        body = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(1, 1))
        col = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            width=min(self.suh(760), max(self.suh(520), int(DISPLAY_WIDTH * 0.92))),
            height=self.suv(690),
            spacing=self.suv(14),
        )

        # Hero
        hero = AnchorLayout(size_hint=(1, None), height=self.suv(258), anchor_x="center", anchor_y="center")
        with hero.canvas.before:
            Color(34 / 255.0, 197 / 255.0, 94 / 255.0, 0.18)
            self._hero_glow = Ellipse(
                pos=(hero.center_x - self.suh(170), hero.center_y - self.suv(120)),
                size=(self.suh(340), self.suv(240)),
            )
        hero.bind(
            pos=lambda w, *_: setattr(
                self._hero_glow,
                "pos",
                (w.center_x - self.suh(170), w.center_y - self.suv(120)),
            ),
            size=lambda w, *_: setattr(self._hero_glow, "size", (self.suh(340), self.suv(240))),
        )
        hero_col = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            width=self.suh(560),
            height=self.suv(258),
            spacing=self.suv(8),
        )

        check_wrap = AnchorLayout(size_hint=(1, None), height=self.suv(126), anchor_x="center", anchor_y="center")
        check = Label(
            text="✓",
            font_size=self.suf(52),
            color=_SUCCESS,
            halign="center",
            valign="middle",
            size_hint=(None, None),
            size=(self.suh(128), self.suv(128)),
        )
        check.bind(size=check.setter("text_size"))
        with check.canvas.before:
            Color(34 / 255.0, 197 / 255.0, 94 / 255.0, 0.12)
            self._check_ring = Ellipse(pos=check.pos, size=check.size)
            Color(34 / 255.0, 197 / 255.0, 94 / 255.0, 0.35)
            self._check_border = Line(circle=(check.center_x, check.center_y, check.width / 2), width=2)
        check.bind(
            pos=lambda w, *_: setattr(self._check_ring, "pos", w.pos),
            size=lambda w, *_: setattr(self._check_ring, "size", w.size),
        )
        check.bind(
            center=lambda w, *_: setattr(self._check_border, "circle", (w.center_x, w.center_y, max(1, w.width / 2 - 1))),
            size=lambda w, *_: setattr(self._check_border, "circle", (w.center_x, w.center_y, max(1, w.width / 2 - 1))),
        )
        check_wrap.add_widget(check)
        hero_col.add_widget(check_wrap)

        self.success_badge = Label(
            text="Success",
            font_size=self.suf(FONT_SIZES["tiny"]),
            color=_SUCCESS,
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=self.suv(20),
        )
        self.success_badge.bind(size=self.success_badge.setter("text_size"))
        hero_col.add_widget(self.success_badge)

        self.title_label = Label(
            text="Preparing Analysis...",
            font_size=self.suf(48),
            bold=True,
            color=COLORS["white"],
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=self.suv(56),
        )
        self.title_label.bind(size=self.title_label.setter("text_size"))
        hero_col.add_widget(self.title_label)

        self.subtitle_label = Label(
            text="Please wait while transcript and action items are prepared.",
            font_size=self.suf(FONT_SIZES["body"] + 2),
            color=_MUTED,
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=self.suv(52),
        )
        self.subtitle_label.bind(size=self.subtitle_label.setter("text_size"))
        hero_col.add_widget(self.subtitle_label)

        hero.add_widget(hero_col)
        col.add_widget(hero)

        # Stage card
        card_wrap = AnchorLayout(size_hint=(1, None), height=self.suv(282), anchor_x="center", anchor_y="center")
        card = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            width=self.suh(672),
            height=self.suv(252),
            padding=[self.suh(26), self.suv(24), self.suh(26), self.suv(18)],
            spacing=self.suv(16),
        )
        with card.canvas.before:
            Color(15 / 255.0, 23 / 255.0, 42 / 255.0, 0.50)
            self._card_bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[16])
        with card.canvas.after:
            Color(*_BORDER)
            self._card_border = Line(
                rounded_rectangle=(card.x, card.y, card.width, card.height, 16),
                width=1.1,
            )
        card.bind(
            pos=lambda w, *_: setattr(self._card_bg, "pos", w.pos),
            size=lambda w, *_: setattr(self._card_bg, "size", w.size),
        )
        card.bind(
            pos=lambda w, *_: setattr(self._card_border, "rounded_rectangle", (w.x, w.y, w.width, w.height, 16)),
            size=lambda w, *_: setattr(self._card_border, "rounded_rectangle", (w.x, w.y, w.width, w.height, 16)),
        )

        self.stage_1 = _StageRow("Transcribing", "Voice data converted to text format", True, self)
        self.stage_2 = _StageRow("Analysing", "Key insights and action items extracted", True, self)
        self.stage_3 = _StageRow("Ready", "Summary generated and dashboard updated", False, self)
        card.add_widget(self.stage_1)
        card.add_widget(self.stage_2)
        card.add_widget(self.stage_3)
        card_wrap.add_widget(card)
        col.add_widget(card_wrap)

        col.add_widget(Widget(size_hint=(1, None), height=self.suv(4)))

        # CTA
        cta_wrap = AnchorLayout(size_hint=(1, None), height=self.suv(62), anchor_x="center", anchor_y="center")
        self.summary_btn = Button(
            text="View Meeting Summary →",
            font_size=self.suf(FONT_SIZES["medium"] + 1),
            bold=True,
            color=COLORS["white"],
            size_hint=(None, None),
            size=(self.suh(448), self.suv(56)),
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            disabled=True,
            opacity=0.60,
        )
        with self.summary_btn.canvas.before:
            self._cta_color = Color(*_CTA, self.summary_btn.opacity)
            self._cta_bg = RoundedRectangle(
                pos=self.summary_btn.pos,
                size=self.summary_btn.size,
                radius=[999],
            )
        self.summary_btn.bind(
            pos=lambda w, *_: setattr(self._cta_bg, "pos", w.pos),
            size=lambda w, *_: setattr(self._cta_bg, "size", w.size),
            opacity=lambda _, a: setattr(self._cta_color, "rgba", (*_CTA[:3], a)),
        )
        self.summary_btn.bind(on_press=self._open_summary)
        cta_wrap.add_widget(self.summary_btn)
        col.add_widget(cta_wrap)

        self.home_link = Label(
            text="Back to Home",
            font_size=self.suf(FONT_SIZES["small"] + 1),
            color=_MUTED,
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=self.suv(24),
        )
        self.home_link.bind(size=self.home_link.setter("text_size"))
        col.add_widget(self.home_link)

        body.add_widget(col)
        root.add_widget(body)

        # Footer
        footer = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=self.suv(56),
            padding=[self.suh(20), self.suv(8), self.suh(20), self.suv(8)],
        )
        with footer.canvas.before:
            Color(*_BG)
            self._footer_bg = Rectangle(pos=footer.pos, size=footer.size)
            Color(*_BORDER)
            self._footer_top = Rectangle(pos=(footer.x, footer.top - 1), size=(footer.width, 1))
        footer.bind(
            pos=lambda w, *_: setattr(self._footer_bg, "pos", w.pos),
            size=lambda w, *_: setattr(self._footer_bg, "size", w.size),
        )
        footer.bind(
            pos=lambda w, *_: setattr(self._footer_top, "pos", (w.x, w.top - 1)),
            size=lambda w, *_: setattr(self._footer_top, "size", (w.width, 1)),
        )
        self.footer_left = Label(
            text="●  SYSTEM ONLINE",
            font_size=self.suf(FONT_SIZES["tiny"]),
            color=_MUTED,
            halign="left",
            valign="middle",
            size_hint=(0.6, 1),
        )
        self.footer_left.bind(size=self.footer_left.setter("text_size"))
        footer.add_widget(self.footer_left)
        self.footer_right = Label(
            text="Analysis in progress...",
            font_size=self.suf(FONT_SIZES["small"]),
            color=_MUTED,
            halign="right",
            valign="middle",
            size_hint=(0.4, 1),
        )
        self.footer_right.bind(size=self.footer_right.setter("text_size"))
        footer.add_widget(self.footer_right)
        root.add_widget(footer)

        self.add_widget(root)
        self._set_stage(0, "active")
        self._set_stage(1, "pending")
        self._set_stage(2, "pending")

    def _set_stage(self, idx: int, state: str):
        row = (self.stage_1, self.stage_2, self.stage_3)[idx]
        row.set_state(state)

    def _set_stage_progress(self, active_idx: int, ready: bool = False):
        for i in range(3):
            if ready:
                self._set_stage(i, "done")
                continue
            if i < active_idx:
                self._set_stage(i, "done")
            elif i == active_idx:
                self._set_stage(i, "active")
            else:
                self._set_stage(i, "pending")

    def _start_pulse(self):
        self._stop_pulse()
        self._pulse_event = Clock.schedule_interval(self._tick_pulse, 0.08)

    def _stop_pulse(self):
        if self._pulse_event:
            self._pulse_event.cancel()
            self._pulse_event = None

    def _tick_pulse(self, _dt):
        if self._summary_ready:
            self.success_badge.opacity = 1.0
            return
        self._pulse_alpha += 0.03 * self._pulse_dir
        if self._pulse_alpha >= 1.0:
            self._pulse_alpha = 1.0
            self._pulse_dir = -1
        elif self._pulse_alpha <= 0.35:
            self._pulse_alpha = 0.35
            self._pulse_dir = 1
        self.success_badge.opacity = self._pulse_alpha

    def on_processing_started(self, data):
        title = (data.get("title") or "Untitled").strip()
        dur_min = int((data.get("duration", 0) or 0) / 60)
        self.subtitle_label.text = (
            f"Meeting '{title}' ({dur_min} min) is being transcribed and analysed."
        )

    def set_processing_status(self, text: str):
        if not text:
            return
        low = text.lower()
        if "transcription done" in low or "building" in low:
            self._set_stage_progress(1)
        elif "updating report" in low or "finishing report" in low:
            self._set_stage_progress(1)
        elif "transcribing" in low:
            self._set_stage_progress(0)

    def on_backend_progress(self, progress: int, status: str, eta: int):
        if status:
            self.set_processing_status(status)
        eta = int(eta or 0)
        if eta > 0:
            if eta < 60:
                self.footer_right.text = "Analysis took less than 1 min"
            else:
                self.footer_right.text = f"Analysis ETA {eta // 60} min"

        p = max(0, min(100, int(progress or 0)))
        if p < 34:
            self._set_stage_progress(0)
        elif p < 84:
            self._set_stage_progress(1)
        elif not self._summary_ready:
            self._set_stage_progress(2)

    def on_summary_ready(self, meeting_id: str, summary_data: dict):
        self._meeting_id = meeting_id
        self._summary_data = summary_data or {}
        self._summary_ready = True
        self._set_stage_progress(2, ready=True)
        self._stop_pulse()
        self.success_badge.opacity = 1.0
        self.title_label.text = "Analysis Complete!"
        self.subtitle_label.text = (
            "Your meeting highlights, transcript, and AI-generated action\n"
            "items are now ready for review."
        )
        elapsed = max(1, int(time.monotonic() - (self._started_ts or time.monotonic())))
        mins, secs = divmod(elapsed, 60)
        self.footer_right.text = f"Analysis took {mins}m {secs:02d}s"
        self.summary_btn.disabled = False
        self.summary_btn.opacity = 1.0

    def _open_summary(self, _inst):
        if not self._summary_ready or not self._meeting_id:
            return
        scr = self.app.screen_manager.get_screen("summary_review")
        if hasattr(scr, "set_meeting_data"):
            scr.set_meeting_data(self._meeting_id, self._summary_data or {})
        self.goto("summary_review", transition="fade")

    def on_enter(self):
        self._started_ts = time.monotonic()
        self._meeting_id = None
        self._summary_data = None
        self._summary_ready = False
        self.title_label.text = "Preparing Analysis..."
        self.subtitle_label.text = "Please wait while transcript and action items are prepared."
        self.footer_right.text = "Analysis in progress..."
        self.summary_btn.disabled = True
        self.summary_btn.opacity = 0.60
        self._set_stage_progress(0)
        self._pulse_alpha = 0.20
        self._pulse_dir = 1
        self._start_pulse()

    def on_leave(self):
        self._stop_pulse()
