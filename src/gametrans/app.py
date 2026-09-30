"""Entry point: QApplication + main window. Run with `python -m gametrans`.

Loads config.default.json + config.user.json (never crashes on bad
config -- see config.py), sets up logging, then shows the main control
window. autostart=true (the default) then starts translating on its own
once the event loop runs (see ui_main.MainWindow).

`python -m gametrans --offline-check` runs the same network-block check
as tests/test_offline.py against a real OCR + translation call and prints
a Thai pass/fail report instead of opening the GUI (spec section 16).
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gametrans.config import load_config
from gametrans.log import setup_logging

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _run_offline_check() -> int:
    import os

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    violations: list[str] = []
    original_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _ALLOWED_HOSTS:
            violations.append(str(address))
            raise RuntimeError(f"blocked outbound connection to {address!r}")
        return original_connect(self, address, *args, **kwargs)

    socket.socket.connect = guarded_connect
    print("กำลังตรวจสอบว่าแอปทำงานออฟไลน์จริง (บล็อกการเชื่อมต่อออกนอกเครื่องทั้งหมด)...\n")

    ok = True
    try:
        from PIL import Image
        import numpy as np

        from gametrans.ocr import run_ocr

        fixture = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "synthetic" / "03_dialogue_box.png"
        if fixture.exists():
            img = np.array(Image.open(fixture).convert("RGB"))[:, :, ::-1]
            run_ocr(img, cfg={"ocr": {"min_score": 0.3, "min_box_h": 5}})
            print("OCR: ผ่าน (ทำงานโดยไม่ต่อเน็ต)")
        else:
            print("OCR: ข้าม (ไม่พบภาพทดสอบ)")
    except Exception as exc:  # noqa: BLE001
        print(f"OCR: ล้มเหลว ({exc})")
        ok = False

    try:
        from gametrans.translate_fast import NllbCTranslator

        model_dir = Path(__file__).resolve().parent.parent.parent / "models" / "fast" / "nllb200-600m-int8"
        if (model_dir / "model.bin").exists():
            translator = NllbCTranslator(model_dir=str(model_dir))
            translator.translate(["Hello"])
            print("แปลภาษา (ชั้น 1): ผ่าน (ทำงานโดยไม่ต่อเน็ต)")
        else:
            print("แปลภาษา (ชั้น 1): ข้าม (ยังไม่ได้ดาวน์โหลดโมเดล — รัน scripts\\download_models.ps1 ก่อน)")
    except Exception as exc:  # noqa: BLE001
        print(f"แปลภาษา (ชั้น 1): ล้มเหลว ({exc})")
        ok = False
    finally:
        socket.socket.connect = original_connect

    print()
    if violations:
        print(f"พบความพยายามเชื่อมต่อออกนอกเครื่อง {len(violations)} ครั้ง: {violations}")
        ok = False

    print("ผลรวม: ผ่าน ✅ (ออฟไลน์จริง)" if ok else "ผลรวม: ไม่ผ่าน ❌")
    return 0 if ok else 1


def main() -> int:
    if "--offline-check" in sys.argv:
        return _run_offline_check()

    cfg = load_config(user_path="config.user.json", default_path="config.default.json")
    setup_logging(cfg)

    from PySide6 import QtWidgets

    from gametrans.ui_main import MainWindow

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(cfg)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
