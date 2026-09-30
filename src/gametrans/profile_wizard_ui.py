"""Thin UI wrapper around profile_wizard.py's analysis engine (spec
section 3E step 1/5: collect samples via button presses or a timed
auto-collect, then hand the proposal to ui_region_editor.py for the user
to adjust and save).

Dialog calls are behind plain instance methods (_show_info/_ask_save),
never called directly as PySide6 static methods -- see DECISIONS.md
phase 5B for why that matters (a directly-called Qt modal dialog can't be
substituted in tests and will hang the test process forever).
"""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets

from gametrans.platform_win import MonitorInfo, get_foreground_window_info
from gametrans.profile_wizard import WizardResult, analyze_samples
from gametrans.profiles import Profile

logger = logging.getLogger("gametrans.profile_wizard_ui")


class WizardDialog(QtWidgets.QDialog):
    def __init__(self, monitor: MonitorInfo, ocr_func=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("สร้างโปรไฟล์จากเกมนี้")
        self.monitor = monitor
        self._ocr_func = ocr_func or self._default_ocr_func
        self.samples: list = []
        self.result: WizardResult | None = None
        self._auto_timer = QtCore.QTimer(self)
        self._auto_timer.timeout.connect(self._collect_one_sample)

        self._build_ui()

    @staticmethod
    def _default_ocr_func(frame, cfg):
        from gametrans.ocr import run_ocr

        return run_ocr(frame, cfg)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "เก็บภาพตัวอย่างขณะเล่นฉากต่างๆ (แนะนำ 3-10 ภาพ) แล้วกด \"วิเคราะห์\""
        ))

        self.sample_count_label = QtWidgets.QLabel("เก็บแล้ว: 0 ภาพ")
        layout.addWidget(self.sample_count_label)

        collect_button = QtWidgets.QPushButton("เก็บตัวอย่างตอนนี้")
        collect_button.clicked.connect(self._collect_one_sample)
        layout.addWidget(collect_button)

        auto_row = QtWidgets.QHBoxLayout()
        self.auto_button = QtWidgets.QPushButton("เรียนรู้ 2 นาที (เก็บอัตโนมัติ)")
        self.auto_button.clicked.connect(self._toggle_auto_collect)
        auto_row.addWidget(self.auto_button)
        layout.addLayout(auto_row)

        analyze_button = QtWidgets.QPushButton("วิเคราะห์")
        analyze_button.clicked.connect(self._on_analyze)
        layout.addWidget(analyze_button)

        self.result_label = QtWidgets.QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        create_button = QtWidgets.QPushButton("สร้างโปรไฟล์ → เปิดตัวแก้ region")
        create_button.clicked.connect(self._on_create_profile)
        layout.addWidget(create_button)

    # ------------------------------------------------------------ actions

    def _collect_one_sample(self) -> None:
        try:
            from gametrans.capture import create_backend

            backend = create_backend("auto", monitor_index=self.monitor.index)
            try:
                frame = backend.grab(self.monitor.left, self.monitor.top, self.monitor.width, self.monitor.height)
            finally:
                backend.close()
        except Exception as exc:  # noqa: BLE001 - one failed capture must not crash the wizard
            logger.warning("profile_wizard_ui: sample capture failed (%s)", exc)
            frame = None

        if frame is not None:
            self.samples.append(frame)
        self.sample_count_label.setText(f"เก็บแล้ว: {len(self.samples)} ภาพ")

    def _toggle_auto_collect(self) -> None:
        if self._auto_timer.isActive():
            self._auto_timer.stop()
            self.auto_button.setText("เรียนรู้ 2 นาที (เก็บอัตโนมัติ)")
        else:
            self._auto_timer.start(2000)  # one sample every 2s for ~2 minutes = ~60 samples
            self.auto_button.setText("หยุดเก็บอัตโนมัติ")
            QtCore.QTimer.singleShot(120_000, self._stop_auto_collect_if_running)

    def _stop_auto_collect_if_running(self) -> None:
        if self._auto_timer.isActive():
            self._auto_timer.stop()
            self.auto_button.setText("เรียนรู้ 2 นาที (เก็บอัตโนมัติ)")

    def _on_analyze(self) -> None:
        if len(self.samples) < 1:
            self._show_info("ยังไม่มีตัวอย่าง", "กรุณาเก็บภาพตัวอย่างอย่างน้อย 1 ภาพก่อนวิเคราะห์")
            return

        self.result = analyze_samples(self.samples, self._ocr_func, cfg={})
        lines = [
            f"พบ {len(self.result.regions)} region ที่เป็นไปได้:",
        ]
        for pr in self.result.regions:
            lines.append(f"  - {pr.region.name}: พฤติกรรม={pr.behavior}, พรีเซ็ต={pr.region.preset}, พบใน {pr.sample_count}/{len(self.samples)} ภาพ")
        lines.append(f"ภาษาต้นทางที่ตรวจพบ: {self.result.source_lang}")
        if self.result.glossary_candidates:
            lines.append(f"คำที่อาจเป็นชื่อเฉพาะ: {', '.join(self.result.glossary_candidates[:15])}")
        self.result_label.setText("\n".join(lines))

    def build_profile(self, profile_id: str, display_name: str) -> Profile | None:
        """Builds a Profile from the last analysis, auto-filling `match`
        from the current foreground window. Returns None if analyze()
        hasn't run yet (nothing to build from)."""
        if self.result is None:
            return None
        process_name, window_title = get_foreground_window_info()
        return Profile(
            id=profile_id,
            display_name=display_name,
            match_process=process_name or None,
            match_window_title=window_title or None,
            risk_level="medium",
            source_lang=self.result.source_lang if self.result.source_lang != "other" else "auto",
            regions=tuple(pr.region for pr in self.result.regions),
            glossary_path=None,
            capture_target_type="auto",
            display_mode_default="auto",
            notes="สร้างโดย wizard จากตัวอย่าง "
            f"{len(self.samples)} ภาพ — ต้องตรวจสอบ/ปรับ region ก่อนใช้งานจริง",
        )

    def _on_create_profile(self) -> None:
        if self.result is None:
            self._show_info("ยังไม่ได้วิเคราะห์", "กรุณากด \"วิเคราะห์\" ก่อนสร้างโปรไฟล์")
            return

        answer = self._prompt_profile_name()
        if answer is None:
            return
        profile_id, display_name = answer

        profile = self.build_profile(profile_id, display_name)
        if profile is None:
            return

        from gametrans.profiles import save_profile

        save_profile(profile, profile_dir="profiles")
        self._open_region_editor_for(profile)

    def _prompt_profile_name(self) -> tuple[str, str] | None:
        profile_id, ok = QtWidgets.QInputDialog.getText(self, "รหัสโปรไฟล์", "รหัสโปรไฟล์ (ภาษาอังกฤษ, ไม่มีเว้นวรรค):")
        if not ok or not profile_id.strip():
            return None
        display_name, ok = QtWidgets.QInputDialog.getText(self, "ชื่อเกม", "ชื่อเกมที่จะแสดง:")
        if not ok or not display_name.strip():
            display_name = profile_id.strip()
        return profile_id.strip(), display_name.strip()

    def _open_region_editor_for(self, profile: Profile) -> None:
        """Opens the region editor pre-populated with the wizard's
        proposed regions, so the user reviews/adjusts before it's final
        (spec 3E step 5: "ผู้ใช้ปรับกรอบด้วย region editor แล้วบันทึก")."""
        from gametrans.ui_region_editor import RegionEditorWindow

        editor = RegionEditorWindow(profile, self.monitor, parent=self)
        editor.exec()

    def _show_info(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.information(self, title, message)
