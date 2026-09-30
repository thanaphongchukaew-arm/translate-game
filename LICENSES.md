# LICENSES.md — โมเดลและไลบรารีทั้งหมดที่ใช้ + ข้อจำกัด

อัปเดตล่าสุด: 2026-09-30 (เฟส 3)

## โมเดล

### 1. OCR ตัวตรวจจับข้อความ (detector) — `ch_PP-OCRv4_det_infer.onnx`
- **มาจาก**: แถมมากับ `rapidocr-onnxruntime==1.4.4` (PaddleOCR PP-OCRv4)
- **ใบอนุญาต**: Apache-2.0
- **การใช้งาน**: ตรวจกล่องข้อความ (script-agnostic ใช้ได้กับทุกภาษา)

### 2. OCR ตัวอ่านข้อความภาษาอังกฤษ (recognizer) — `en_PP-OCRv3_rec_infer.onnx`
- **มาจาก**: https://huggingface.co/SWHL/RapidOCR (PP-OCRv3/en_PP-OCRv3_rec_infer.onnx)
- **ต้นทางจริง**: PaddleOCR (PaddlePaddle) — SWHL/RapidOCR เป็นที่เก็บไฟล์ ONNX ที่แปลงมาจากโมเดลทางการ
- **ใบอนุญาต**: Apache-2.0
- **การใช้งาน**: อ่านข้อความภาษาอังกฤษ (แทนที่ตัว `ch` ที่แถมมาเพราะตัดช่องว่างคำอังกฤษทิ้ง — ดู DECISIONS.md เฟส 2)
- **บันทึกใน**: `models/MANIFEST.json`, sha256 ตรวจแล้ว

### 3. ชั้น 1 (แปลเร็ว) — NLLB-200-distilled-600M แปลงเป็น CTranslate2 int8
- **โมเดลต้นทาง**: `facebook/nllb-200-distilled-600M` (Meta AI)
- **ใบอนุญาต**: **CC-BY-NC-4.0 (ห้ามใช้เชิงพาณิชย์)** — เหมาะกับการใช้งานส่วนตัวเท่านั้นตามที่โปรเจกต์นี้ออกแบบไว้ **ห้ามแจกจ่าย/ให้บริการเชิงพาณิชย์โดยใช้โมเดลนี้**
- **ไฟล์ที่ใช้จริง (แปลง int8 แล้ว)**: มาจาก `mijuanlo/nllb-200-distilled-600M-ct2-int8` บน Hugging Face (แปลงโดยบุคคลที่สามด้วย `ct2-transformers-converter --quantization int8` จากโมเดลทางการ — README ของ repo ระบุที่มาและใบอนุญาตตรงกับต้นฉบับ)
- **Tokenizer**: `sentencepiece.bpe.model` + ไฟล์ config ดาวน์โหลดแยกจาก `facebook/nllb-200-distilled-600M` ทางการโดยตรง (ไม่ใช่จากที่แปลงแล้ว) เพื่อยืนยันแหล่งที่มาที่เชื่อถือได้
- **เหตุผลที่เลือกไฟล์แปลงแล้วแทนแปลงเอง**: การแปลงเองต้องติดตั้ง `transformers` + `torch` (หลาย GB) ซึ่งเป็น build-time dependency ที่ใหญ่เกินความจำเป็นเมื่อเทียบกับการใช้ไฟล์ที่แปลงแล้วและตรวจ sha256 ได้
- **บันทึกใน**: `models/MANIFEST.json`, sha256 ตรวจแล้วทุกไฟล์

### 4. ชั้น 2 (LLM ปรับคำแปล)
**ยังไม่ได้เลือก/ดาวน์โหลด** — ตามหัวข้อ 3 ของสเปก ชั้น 2 เป็นทางเลือก จะตัดสินใจตอนเฟส 4 (ดู DECISIONS.md)

## ไลบรารี (requirements.lock)

| ไลบรารี | ใบอนุญาต |
|---|---|
| rapidocr-onnxruntime | Apache-2.0 |
| onnxruntime-directml | MIT |
| ctranslate2 | MIT |
| sentencepiece | Apache-2.0 |
| sacrebleu | Apache-2.0 |
| dxcam, mss | MIT |
| opencv-python(-headless) | Apache-2.0 |
| numpy, pillow | BSD-3-Clause / HPND |
| pytest | MIT |

ไม่มีไลบรารีที่เรียกบริการคลาวด์เสียเงินใดๆ (ตรวจแล้วตามหัวข้อ 16 — ดู `tests/test_offline.py` เมื่อเขียนในเฟส 7)

## สรุปข้อจำกัดการใช้งาน

**โปรเจกต์นี้และโมเดลทั้งหมดที่เลือกใช้เหมาะสำหรับการใช้งานส่วนตัวเท่านั้น** เพราะ NLLB-200 มีเงื่อนไข non-commercial (CC-BY-NC-4.0) ห้ามนำไปใช้ในผลิตภัณฑ์/บริการเชิงพาณิชย์โดยไม่เปลี่ยนไปใช้โมเดลอื่นที่มีใบอนุญาตอนุญาตเชิงพาณิชย์
