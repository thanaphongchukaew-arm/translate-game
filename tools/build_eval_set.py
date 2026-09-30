"""Build tests/eval/en_th.jsonl: the English->Thai evaluation set for the
tier-1/tier-2 model bake-off (spec section 12, sentences drawn from
Appendix A's categories).

The Thai `ref` translations here are drafted by Claude Code (this tool),
NOT reviewed by a human translator. Every record is tagged
`"ref_source": "draft-by-llm"` per spec section 12's explicit requirement
-- these are a reasonable starting point, not a certified-correct
reference. The user should review/edit them (tools/bakeoff.py --add lets
them add more from real gameplay).
"""
import json
from pathlib import Path

# (src, ref, category)
ENTRIES: list[tuple[str, str, str]] = [
    # --- UI สั้น ---
    ("Start Game", "เริ่มเกม", "ui_short"),
    ("Options", "ตั้งค่า", "ui_short"),
    ("Save and Quit", "บันทึกและออก", "ui_short"),
    ("Inventory", "กระเป๋าไอเทม", "ui_short"),
    ("Press E to interact", "กด E เพื่อโต้ตอบ", "ui_short"),
    ("Continue", "ดำเนินการต่อ", "ui_short"),
    ("Are you sure?", "แน่ใจหรือไม่?", "ui_short"),
    ("New Game", "เกมใหม่", "ui_short"),
    ("Load Game", "โหลดเกม", "ui_short"),
    ("Settings", "การตั้งค่า", "ui_short"),
    ("Back", "ย้อนกลับ", "ui_short"),
    ("Confirm", "ยืนยัน", "ui_short"),
    ("Cancel", "ยกเลิก", "ui_short"),
    # --- ไอเทม/สกิล ---
    ("Iron Sword (+3)", "ดาบเหล็ก (+3)", "item_skill"),
    ("Potion of Minor Healing", "ยาฟื้นฟูเล็กน้อย", "item_skill"),
    ("Ancient Key", "กุญแจโบราณ", "item_skill"),
    ("Critical Hit: 150% damage", "โจมตีคริติคอล: ดาเมจ 150%", "item_skill"),
    ("Wooden Shield", "โล่ไม้", "item_skill"),
    ("Fire Resistance +10%", "ต้านทานไฟ +10%", "item_skill"),
    # --- ระบบ/เควสต์ ---
    ("Quest updated: Find the missing merchant", "อัปเดตเควสต์: ตามหาพ่อค้าที่หายไป", "quest_system"),
    ("Your inventory is full.", "กระเป๋าไอเทมของคุณเต็มแล้ว", "quest_system"),
    ("You have learned a new skill.", "คุณได้เรียนรู้สกิลใหม่", "quest_system"),
    ("Quest complete!", "ทำเควสต์สำเร็จ!", "quest_system"),
    ("New area discovered.", "ค้นพบพื้นที่ใหม่", "quest_system"),
    # --- บทสนทนา ---
    ("You shouldn't have come here, traveler. The forest remembers everything.",
     "คุณไม่ควรมาที่นี่เลย นักเดินทาง ป่าแห่งนี้จดจำทุกสิ่งเอาไว้", "dialogue"),
    ("I'll meet you at the old mill after sunset, and don't tell anyone.",
     "ฉันจะไปเจอเธอที่โรงสีเก่าหลังพระอาทิตย์ตก และอย่าบอกใครเชียว", "dialogue"),
    ("Wait... did you hear that?", "เดี๋ยวก่อน... ได้ยินเสียงนั้นไหม?", "dialogue"),
    ("We've been waiting for you for a long time.", "พวกเรารอคุณมานานแล้ว", "dialogue"),
    ("This is the last time I'm warning you.", "นี่เป็นครั้งสุดท้ายที่ฉันจะเตือนเธอ", "dialogue"),
    # --- ชื่อเฉพาะ ---
    ("Lord Aldric of Stormwatch", "ลอร์ดอัลดริกแห่งสตอร์มวอตช์", "proper_noun"),
    ("The Whispering Caverns", "ถ้ำเสียงกระซิบ", "proper_noun"),
    # --- รูปแบบพิเศษ ---
    ("HP 120/200", "HP 120/200", "special_format"),
    ("Deal {0} damage", "สร้างความเสียหาย {0}", "special_format"),
    ("You found %d gold.", "คุณพบทอง %d เหรียญ", "special_format"),
    ("GAME OVER", "เกมโอเวอร์", "special_format"),
    ("LEVEL UP!", "เลเวลอัป!", "special_format"),
    # --- กรณียาก ---
    ("The ancient door slowly opened, revealing a passage that led deep into",
     "ประตูโบราณค่อยๆ เปิดออก เผยให้เห็นทางเดินที่นำลึกเข้าไปสู่", "hard_case_cutoff"),
    ("Save", "บันทึก / ช่วยชีวิต", "hard_case_ambiguous"),
    ("Yeah, whatever you say, boss.", "อือ แล้วแต่หัวหน้าจะว่ายังไงก็ได้", "hard_case_slang"),
    (
        "After years of searching, the old scholar finally found the lost manuscript hidden beneath "
        "the temple ruins, its pages worn but its secrets still intact, waiting for someone brave "
        "enough to uncover the truth within.",
        "หลังจากค้นหามาหลายปี นักปราชญ์ชราในที่สุดก็พบต้นฉบับที่สูญหายซึ่งซ่อนอยู่ใต้ซากปรักหักพังของวิหาร "
        "หน้ากระดาษเก่าโทรมแต่ความลับยังคงสมบูรณ์ รอคอยผู้กล้าที่จะเปิดเผยความจริงภายใน",
        "hard_case_long",
    ),
    # --- UI แนว gacha/เกมมือถือ ---
    ("Summon", "สุ่มเรียก", "gacha_ui"),
    ("Rate-Up", "เพิ่มอัตรา", "gacha_ui"),
    ("Pity", "การันตี", "gacha_ui"),
    ("Daily Quest", "เควสต์ประจำวัน", "gacha_ui"),
    ("Stamina", "พลังงาน", "gacha_ui"),
    ("Battle Pass", "แบทเทิลพาส", "gacha_ui"),
    ("Limited Banner", "แบนเนอร์จำกัดเวลา", "gacha_ui"),
    ("Tap to continue", "แตะเพื่อดำเนินการต่อ", "gacha_ui"),
    ("Skip", "ข้าม", "gacha_ui"),
    ("Auto", "อัตโนมัติ", "gacha_ui"),
    ("Log", "บันทึก", "gacha_ui"),
    ("Claim All", "รับทั้งหมด", "gacha_ui"),
    ("Insufficient resources", "ทรัพยากรไม่เพียงพอ", "gacha_ui"),
    # --- แชต/ระบบออนไลน์ ---
    ("[Guild] Alice: anyone up for the raid tonight?", "[กิลด์] Alice: มีใครว่างตีเรดคืนนี้ไหม?", "chat_online"),
    ("You have joined the party.", "คุณได้เข้าร่วมปาร์ตี้แล้ว", "chat_online"),
    ("Connection lost. Reconnecting...", "การเชื่อมต่อขาดหาย กำลังเชื่อมต่อใหม่...", "chat_online"),
    # --- ซับไตเติล/คัตซีน ---
    ("(whispering) They're coming.", "(กระซิบ) พวกมันมาแล้ว", "subtitle"),
    ("We don't have much time.", "เราไม่มีเวลามากนัก", "subtitle"),
    # --- เกมกลยุทธ์/จำลอง ---
    ("Research complete: Iron Working", "วิจัยสำเร็จ: การตีเหล็ก", "strategy_sim"),
    ("Not enough gold.", "ทองไม่พอ", "strategy_sim"),
    ("Build a granary (12 turns)", "สร้างยุ้งฉาง (12 เทิร์น)", "strategy_sim"),
    # --- เกมยิง/แอคชัน ---
    ("Hold F to revive", "กดค้าง F เพื่อช่วยชุบชีวิต", "shooter_action"),
    ("Enemy spotted", "พบศัตรู", "shooter_action"),
    ("Objective updated", "อัปเดตเป้าหมาย", "shooter_action"),
]


def main() -> None:
    out_path = Path(__file__).resolve().parent.parent / "tests" / "eval" / "en_th.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for src, ref, category in ENTRIES:
            f.write(json.dumps({"src": src, "ref": ref, "category": category, "ref_source": "draft-by-llm"}, ensure_ascii=False) + "\n")
    print(f"เขียน {len(ENTRIES)} ประโยคไปที่ {out_path}")


if __name__ == "__main__":
    main()
