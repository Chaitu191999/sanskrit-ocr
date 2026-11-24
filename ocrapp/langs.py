"""Languages offered in the app and how each maps onto Tesseract models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    code: str
    name: str
    native: str
    script: str
    model: str | None      # Tesseract model(s); None = no model exists
    rtl: bool = False
    font: str = "Calibri"  # Word font with full coverage of the script


_NIRMALA = "Nirmala UI"

LANGS: list[Lang] = [
    Lang("eng", "English", "English", "Latin", "eng"),
    Lang("rus", "Russian", "Русский", "Cyrillic", "rus"),
    Lang("fra", "French", "Français", "Latin", "fra"),
    Lang("deu", "German", "Deutsch", "Latin", "deu"),
    Lang("spa", "Spanish", "Español", "Latin", "spa"),
    # Script names for CJK are the ones Tesseract's OSD reports.
    Lang("zho", "Chinese (Simplified)", "简体中文", "Han", "chi_sim", font="SimSun"),
    Lang("zho_tra", "Chinese (Traditional)", "繁體中文", "Han", "chi_tra",
         font="Microsoft JhengHei"),
    Lang("jpn", "Japanese", "日本語", "Japanese", "jpn", font="Yu Gothic"),
    Lang("kor", "Korean", "한국어", "Korean", "kor", font="Malgun Gothic"),
    Lang("hin", "Hindi", "हिन्दी", "Devanagari", "hin", font=_NIRMALA),
    Lang("mar", "Marathi", "मराठी", "Devanagari", "mar", font=_NIRMALA),
    Lang("nep", "Nepali", "नेपाली", "Devanagari", "nep", font=_NIRMALA),
    Lang("san", "Sanskrit", "संस्कृतम्", "Devanagari", "san", font=_NIRMALA),
    Lang("kok", "Konkani", "कोंकणी", "Devanagari", "script/Devanagari", font=_NIRMALA),
    Lang("mai", "Maithili", "मैथिली", "Devanagari", "script/Devanagari", font=_NIRMALA),
    Lang("brx", "Bodo", "बड़ो", "Devanagari", "script/Devanagari", font=_NIRMALA),
    Lang("doi", "Dogri", "डोगरी", "Devanagari", "script/Devanagari", font=_NIRMALA),
    Lang("ben", "Bengali", "বাংলা", "Bengali", "ben", font=_NIRMALA),
    Lang("asm", "Assamese", "অসমীয়া", "Bengali", "asm", font=_NIRMALA),
    Lang("mni", "Manipuri (Bengali script)", "মণিপুরী", "Bengali", "ben", font=_NIRMALA),
    Lang("pan", "Punjabi", "ਪੰਜਾਬੀ", "Gurmukhi", "pan", font=_NIRMALA),
    Lang("guj", "Gujarati", "ગુજરાતી", "Gujarati", "guj", font=_NIRMALA),
    Lang("ori", "Odia", "ଓଡ଼ିଆ", "Oriya", "ori", font=_NIRMALA),
    Lang("tam", "Tamil", "தமிழ்", "Tamil", "tam", font=_NIRMALA),
    Lang("tel", "Telugu", "తెలుగు", "Telugu", "tel", font=_NIRMALA),
    Lang("kan", "Kannada", "ಕನ್ನಡ", "Kannada", "kan", font=_NIRMALA),
    Lang("mal", "Malayalam", "മലയാളം", "Malayalam", "mal", font=_NIRMALA),
    Lang("sin", "Sinhala", "සිංහල", "Sinhala", "sin", font=_NIRMALA),
    Lang("ara", "Arabic", "العربية", "Arabic", "ara", rtl=True, font="Arial"),
    Lang("fas", "Persian / Dari", "فارسی", "Arabic", "fas", rtl=True, font="Arial"),
    Lang("urd", "Urdu", "اردو", "Arabic", "urd", rtl=True, font="Arial"),
    Lang("pus", "Pashto", "پښتو", "Arabic", "pus", rtl=True, font="Arial"),
    Lang("snd", "Sindhi (Arabic script)", "سنڌي", "Arabic", "snd", rtl=True, font="Arial"),
    Lang("snd_deva", "Sindhi (Devanagari)", "सिन्धी", "Devanagari", "script/Devanagari",
         font=_NIRMALA),
    Lang("kas", "Kashmiri", "کٲشُر", "Arabic", "script/Arabic", rtl=True, font="Arial"),
    Lang("div", "Dhivehi", "ދިވެހި", "Thaana", "div", rtl=True, font="MV Boli"),
    Lang("mya", "Burmese", "မြန်မာ", "Myanmar", "mya", font="Myanmar Text"),
    Lang("sat", "Santali (Ol Chiki)", "ᱥᱟᱱᱛᱟᱲᱤ", "Ol Chiki", None, font=_NIRMALA),
    Lang("mni_mtei", "Manipuri (Meetei Mayek)", "ꯃꯤꯇꯩꯂꯣꯟ", "Meetei Mayek", None, font=_NIRMALA),
]

BY_CODE = {lang.code: lang for lang in LANGS}

#: Tesseract OSD script name -> script model used in automatic mode.
OSD_SCRIPT_MODEL = {
    # Latin: English plus the accented European languages offered. Measured
    # on real forms: chrF +4 to +8 for French, German, Spanish over eng alone,
    # no loss on English, about 1.5x the time. (script/Latin is as good but
    # adds 89 MB.)
    "Latin": "eng+fra+deu+spa", "Cyrillic": "rus", "Arabic": "script/Arabic",
    "Devanagari": "script/Devanagari", "Bengali": "script/Bengali",
    "Gurmukhi": "script/Gurmukhi", "Gujarati": "script/Gujarati",
    "Oriya": "script/Oriya", "Tamil": "script/Tamil", "Telugu": "script/Telugu",
    "Kannada": "script/Kannada", "Malayalam": "script/Malayalam",
    "Sinhala": "script/Sinhala", "Myanmar": "script/Myanmar", "Thaana": "script/Thaana",
    # OSD folds kana into "Japanese" and Hangul into "Korean", but often
    # reports kanji-heavy Japanese as "Han": chi_sim+jpn reads both (Japanese
    # forms chrF 18 -> 58, Chinese unchanged).
    "Han": "chi_sim+jpn", "Japanese": "jpn", "Korean": "kor",
    "Hiragana": "jpn", "Katakana": "jpn", "Hangul": "kor",
}
RTL_SCRIPTS = {"Arabic", "Thaana", "Hebrew", "Syriac"}
SCRIPT_FONT = {
    "Arabic": "Arial", "Thaana": "MV Boli", "Myanmar": "Myanmar Text",
    "Latin": "Calibri", "Cyrillic": "Calibri",
    "Han": "SimSun", "Japanese": "Yu Gothic", "Hiragana": "Yu Gothic",
    "Katakana": "Yu Gothic", "Korean": "Malgun Gothic", "Hangul": "Malgun Gothic",
}

#: Scripts written without spaces between words.
UNSPACED_SCRIPTS = {"Han", "Japanese", "Hiragana", "Katakana"}


def model_for(codes: list[str]) -> str | None:
    """Tesseract -l argument for a set of chosen languages (English always added)."""
    parts: list[str] = []
    for code in codes:
        lang = BY_CODE.get(code)
        if lang and lang.model:
            for m in lang.model.split("+"):
                if m not in parts:
                    parts.append(m)
    if not parts:
        return None
    if "eng" not in parts:
        parts.append("eng")   # real documents embed English constantly
    return "+".join(parts)


#: Picker group headings where the OSD script name is not what people expect.
SCRIPT_LABEL = {"Han": "Chinese", "Japanese": "Japanese", "Korean": "Hangul"}


def ui_list() -> list[dict]:
    return [
        {"code": l.code, "name": l.name, "native": l.native,
         "script": SCRIPT_LABEL.get(l.script, l.script),
         "supported": True, "rtl": l.rtl}
        for l in LANGS if l.model is not None   # languages with no model are not offered
    ]
