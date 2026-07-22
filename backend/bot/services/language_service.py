"""
Language detection for Bot Service — FR-11.1.
Supported: 12 Indian regional languages + English (BCP-47 codes).
Uses: langdetect library (probabilistic, trained on Wikipedia data).
Falls back to 'en' if detection fails or language unsupported.
"""
from langdetect import detect, LangDetectException

# Supported BCP-47 codes (from docs/api/case.md languageCode constraint)
_SUPPORTED_LANGS = {
    "hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "or", "as", "en",
}

# langdetect → BCP-47 mappings for languages that differ
_LANG_REMAP = {
    "zh-cn": "zh",  # not used, but defensive
    "or": "or",
}

_DEFAULT_LANG = "en"


def detect_language(text: str) -> str:
    """
    Detect the language of the input text.
    Returns BCP-47 code from supported list.
    Defaults to 'en' on failure or unsupported language.
    
    Args:
        text: user message (can be any length, but accuracy improves with ≥20 chars)
    
    Returns:
        BCP-47 language code (e.g. "hi", "en", "ta")
    """
    if not text or len(text.strip()) < 3:
        return _DEFAULT_LANG
    
    try:
        detected = detect(text)
        lang = _LANG_REMAP.get(detected, detected)
        return lang if lang in _SUPPORTED_LANGS else _DEFAULT_LANG
    except LangDetectException:
        return _DEFAULT_LANG


def is_supported_language(lang_code: str) -> bool:
    """Check if a BCP-47 code is in the supported set."""
    return lang_code in _SUPPORTED_LANGS
