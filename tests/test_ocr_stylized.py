from pathlib import Path

import pytest

from gametrans.layout import OcrLine
from gametrans.ocr import _attach_drop_caps

FIXTURE = Path(__file__).parent / "fixtures" / "p5_title_card.png"


def test_attach_drop_cap_to_word_on_its_right():
    cap = OcrLine(x1=350, y1=80, x2=380, y2=130, text="A", score=0.95)
    word = OcrLine(x1=382, y1=85, x2=500, y2=160, text="rrived!", score=0.99)
    out = _attach_drop_caps([cap], [word])
    assert out[0].text == "Arrived!"
    assert out[0].x1 == 350


def test_drop_cap_ignored_when_word_already_has_it():
    cap = OcrLine(x1=300, y1=20, x2=330, y2=70, text="P", score=0.95)
    word = OcrLine(x1=295, y1=19, x2=488, y2=96, text="Phantom", score=0.99)
    assert _attach_drop_caps([cap], [word])[0].text == "Phantom"


@pytest.mark.skipif(not Path("models/ocr/en/en_PP-OCRv3_rec_infer.onnx").exists(), reason="OCR model missing")
def test_title_card_reads_every_word():
    cv2 = pytest.importorskip("cv2")
    from gametrans.ocr import run_ocr
    from gametrans.ocr_post import clean_text

    text = " ".join(clean_text(ln.text) for ln in run_ocr(cv2.imread(str(FIXTURE)), {}))
    for word in ("The New", "Phantom", "Have", "Thieves", "Arrived!"):
        assert word in text


@pytest.mark.skipif(not Path("models/ocr/en/en_PP-OCRv3_rec_infer.onnx").exists(), reason="OCR model missing")
@pytest.mark.parametrize("color", [(255, 200, 40), (40, 220, 255), (60, 230, 90), (230, 30, 30)])
def test_drop_cap_found_in_any_accent_color(color):
    """The big first letter may be any saturated color, not just red."""
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    PIL = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw, ImageFont

    from gametrans.ocr import _accent_drop_caps, get_engine

    font_path = Path("C:/Windows/Fonts/arialbd.ttf")
    if not font_path.exists():
        pytest.skip("font missing")
    im = PIL.new("RGB", (300, 220), (20, 20, 28))
    ImageDraw.Draw(im).text((40, 20), "S", font=ImageFont.truetype(str(font_path), 150), fill=color)
    engine, _ = get_engine("cpu")
    caps = _accent_drop_caps(engine, cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR))
    assert [c.text for c in caps] == ["S"]
