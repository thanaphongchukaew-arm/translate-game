"""Translation manager dialog (spec section 13.6): table of cached
translations you can edit into a permanent override, a glossary tab, and
a clear-cache button that never touches overrides/glossary (user data is
never silently deleted).
"""
from __future__ import annotations

from PySide6 import QtWidgets

from gametrans.store import Store


class ManagerDialog(QtWidgets.QDialog):
    def __init__(self, store: Store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("จัดการคำแปล")
        self.resize(640, 420)

        layout = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        self._build_cache_tab()
        self._build_glossary_tab()

        clear_button = QtWidgets.QPushButton("ล้าง cache (ไม่ล้าง override/glossary)")
        clear_button.clicked.connect(self._on_clear_cache)
        layout.addWidget(clear_button)

    # ------------------------------------------------------------ cache tab

    def _build_cache_tab(self) -> None:
        tab = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(tab)
        self.cache_table = QtWidgets.QTableWidget(0, 3)
        self.cache_table.setHorizontalHeaderLabels(["ต้นฉบับ", "คำแปล", "ชั้น"])
        self.cache_table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.cache_table)

        save_button = QtWidgets.QPushButton("จำถาวร (บันทึกแถวที่เลือกเป็น override)")
        save_button.clicked.connect(self._on_save_override)
        v.addWidget(save_button)

        self.tabs.addTab(tab, "คำแปลล่าสุด")

    def _on_save_override(self) -> None:
        row = self.cache_table.currentRow()
        if row < 0:
            return
        src_item = self.cache_table.item(row, 0)
        thai_item = self.cache_table.item(row, 1)
        if src_item is None or thai_item is None:
            return
        self.store.set_override(src_item.text(), thai_item.text())
        self.store.save()
        self.refresh()

    # --------------------------------------------------------- glossary tab

    def _build_glossary_tab(self) -> None:
        tab = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(tab)
        self.glossary_table = QtWidgets.QTableWidget(0, 2)
        self.glossary_table.setHorizontalHeaderLabels(["คำศัพท์", "คำแปล"])
        self.glossary_table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.glossary_table)

        form = QtWidgets.QHBoxLayout()
        self.term_input = QtWidgets.QLineEdit()
        self.term_input.setPlaceholderText("คำศัพท์ (อังกฤษ)")
        self.translation_input = QtWidgets.QLineEdit()
        self.translation_input.setPlaceholderText("คำแปล (ไทย)")
        add_button = QtWidgets.QPushButton("เพิ่ม/แก้ไข")
        add_button.clicked.connect(self._on_add_glossary_term)
        form.addWidget(self.term_input)
        form.addWidget(self.translation_input)
        form.addWidget(add_button)
        v.addLayout(form)

        self.tabs.addTab(tab, "Glossary")

    def _on_add_glossary_term(self) -> None:
        term = self.term_input.text().strip()
        translation = self.translation_input.text().strip()
        if not term or not translation:
            return
        self.store.set_glossary_term(term, translation)
        self.store.save()
        self.term_input.clear()
        self.translation_input.clear()
        self.refresh()

    # ------------------------------------------------------------------

    def _on_clear_cache(self) -> None:
        self.store.clear_cache()
        self.refresh()

    def refresh(self) -> None:
        self.cache_table.setRowCount(0)

        overrides = self.store.get_overrides()
        for text, thai in overrides.items():
            row = self.cache_table.rowCount()
            self.cache_table.insertRow(row)
            self.cache_table.setItem(row, 0, QtWidgets.QTableWidgetItem(text))
            self.cache_table.setItem(row, 1, QtWidgets.QTableWidgetItem(thai))
            self.cache_table.setItem(row, 2, QtWidgets.QTableWidgetItem("override"))

        for entry in self.store.list_recent(limit=200):
            if entry.text in overrides:
                continue  # already shown above, and overrides take priority anyway
            row = self.cache_table.rowCount()
            self.cache_table.insertRow(row)
            self.cache_table.setItem(row, 0, QtWidgets.QTableWidgetItem(entry.text))
            self.cache_table.setItem(row, 1, QtWidgets.QTableWidgetItem(entry.thai))
            tier_label = "final" if entry.final else f"tier {entry.tier}"
            self.cache_table.setItem(row, 2, QtWidgets.QTableWidgetItem(tier_label))

        self.glossary_table.setRowCount(0)
        for term, translation in self.store.get_glossary().items():
            row = self.glossary_table.rowCount()
            self.glossary_table.insertRow(row)
            self.glossary_table.setItem(row, 0, QtWidgets.QTableWidgetItem(term))
            self.glossary_table.setItem(row, 1, QtWidgets.QTableWidgetItem(translation))
