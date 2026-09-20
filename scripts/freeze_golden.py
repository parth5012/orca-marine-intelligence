#!/usr/bin/env python3
"""
scripts/freeze_golden.py

One-time Bhashini freeze script for ORCA Golden Multilingual Dataset.
Translates 66 canonical queries (3 per each of 22 Bhashini languages) and
persists frozen references to data/golden_v1.json.

Ticket: #179 (Map #182)
Owner: M-B (Data)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Ensure repository root is on sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv

    for _env_file in (BASE_DIR / ".env", BASE_DIR / "backend" / ".env", Path(".env")):
        if _env_file.is_file():
            load_dotenv(dotenv_path=_env_file, override=False)
            break
except ImportError:
    pass

from backend.core.bhashini import translate_from_english, TranslationResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("freeze_golden")

# 22 Scheduled Indian Languages supported by Bhashini
TARGET_LANGS: list[str] = [
    "as",   # Assamese
    "bn",   # Bengali
    "brx",  # Bodo
    "doi",  # Dogri
    "gu",   # Gujarati
    "hi",   # Hindi
    "kn",   # Kannada
    "ks",   # Kashmiri
    "gom",  # Konkani (Goan)
    "mai",  # Maithili
    "ml",   # Malayalam
    "mni",  # Manipuri (Meitei)
    "mr",   # Marathi
    "ne",   # Nepali
    "or",   # Odia
    "pa",   # Punjabi
    "sa",   # Sanskrit
    "sat",  # Santali
    "sd",   # Sindhi
    "ta",   # Tamil
    "te",   # Telugu
    "ur",   # Urdu
]

# Canonical vernacular queries for template/coastal languages
VERNACULAR_QUERIES: dict[str, dict[int, str]] = {
    "ml": {
        1: "കൊച്ചിക്ക് സമീപം സുരക്ഷിതമായി മീൻ പിടിക്കാമോ?",
        2: "മന്നാർ ഉൾക്കടൽ ദേശീയ പാർക്കിൽ മീൻ പിടിക്കാമോ?",
        3: "kochi kadalil innu meen pidikkan pattumo?",
    },
    "ta": {
        1: "கொச்சி அருகே இன்று மீன்பிடிக்க செல்வது பாதுகாப்பானதா?",
        2: "மன்னார் வளைகுடா தேசிய பூங்காவில் மீன்பிடிக்கலாமா?",
        3: "kochi kadalil innaiku meen pidika polaama?",
    },
    "te": {
        1: "కొచ్చి దగ్గర చేపల వేట సురక్షితమేనా?",
        2: "మన్నార్ గల్ఫ్ మెరైన్ పార్కులో చేపలు పట్టవచ్చా?",
        3: "kochi lo eeroju chepalu pattavacha?",
    },
    "hi": {
        1: "क्या कोच्चि के पास आज सुरक्षित रूप से मछली पकड़ सकते हैं?",
        2: "क्या मन्नार की खाड़ी समुद्री राष्ट्रीय उद्यान में मछली पकड़ सकते हैं?",
        3: "kochi ke paas machli pakadne ja sakte hain kya?",
    },
    "mr": {
        1: "कोची जवळ आज मासेमारी करणे सुरक्षित आहे का?",
        2: "मन्नारचे आखात राष्ट्रीय उद्यानात मासेमारी करता येईल का?",
        3: "kochi javal aaj masemari karta yeil ka?",
    },
    "gu": {
        1: "કોચી નજીક આજે માછીમારી કરવી સલામત છે?",
        2: "મન્નાર અખાત મરીન નેશનલ પાર્કમાં માછીમારી કરી શકાય?",
        3: "kochi ma aaje fishing kari sakay?",
    },
    "kn": {
        1: "ಕೊಚ್ಚಿ ಸಮೀಪ ಇಂದು ಮೀನುಗಾರಿಕೆ ಸುರಕ್ಷಿತವೇ?",
        2: "ಮನ್ನಾರ್ ಕೊಲ್ಲಿ ರಾಷ್ಟ್ರೀಯ ಉದ್ಯಾನದಲ್ಲಿ ಮೀನು ಹಿಡಿಯಬಹುದೇ?",
        3: "kochi hathira innu meenu hidiyoke aagutha?",
    },
    "bn": {
        1: "আজ কি কোচির কাছে মাছ ধরা নিরাপদ?",
        2: "মান্নার উপসাগর জাতীয় উদ্যানে মাছ ধরা যাবে কি?",
        3: "kochir kache aaj mach dhora jabe ki?",
    },
    "or": {
        1: "କୋଚି ନିକଟରେ ଆଜି ମାଛ ଧରିବା ସୁରକ୍ଷିତ କି?",
        2: "ମନ୍ନାର ଉପସାଗର ସାମୁଦ୍ରିକ ଜାତୀୟ ଉଦ୍ୟାନରେ ମାଛ ଧରାଯାଇପାରିବ କି?",
        3: "kochi re aaji machha dhariba safe ki?",
    },
}

# Pre-validated vernacular reference replies for the 5 core template languages
TEMPLATE_REPLIES: dict[str, dict[int, str]] = {
    "ml": {
        1: "കൊച്ചിക്ക് സമീപം ഇന്ന് കടലും കാലാവസ്ഥയും മത്സ്യബന്ധനത്തിന് അനുയോജ്യമാണ്. തിരമാലകളുടെ ഉയരം 1.4 മീറ്ററും കാറ്റിന്റെ വേഗത 11 നോട്ടിക്കൽ മൈലുമാണ്.",
        2: "യാത്ര ചെയ്യരുത് (DO NOT SAIL). നിയന്ത്രിത സമുദ്ര സംരക്ഷിത മേഖലയിലാണ് (MPA). ഇവിടെ മത്സ്യബന്ധനം കർശനമായി നിരോധിച്ചിരിക്കുന്നു.",
        3: "കൊച്ചിക്ക് 15 കി.മീ തെക്കുപടിഞ്ഞാറായി അനുകൂലമായ മത്സ്യബന്ധന മേഖലകൾ (PFZ) കണ്ടെത്തിയിട്ടുണ്ട്. തിരമാല ഉയരം 1.2 മീറ്ററാണ്.",
    },
    "ta": {
        1: "கொச்சி அருகே இன்று கடல் மற்றும் வானிலை மீன்பிடிக்க பாதுகாப்பானது. அலை உயரம் 1.4 மீ மற்றும் காற்றின் வேகம் 11 நாட்ஸ்.",
        2: "பயணம் செய்ய வேண்டாம் (DO NOT SAIL). பாதுகாக்கப்பட்ட கடல் பகுதியில் உள்ளீர்கள். மீன்பிடிப்பது தடை செய்யப்பட்டுள்ளது.",
        3: "கொச்சியிலிருந்து 15 கி.மீ தென்மேற்கே சாதகமான மீன்பிடி மண்டலங்கள் கண்டறியப்பட்டுள்ளன. அலை உயரம் 1.2 மீ.",
    },
    "te": {
        1: "కొచ్చి సమీపంలో నేడు సముద్రం మరియు వాతావరణం చేపల వేటకు అనుకూలంగా ఉన్నాయి. అలల ఎత్తు 1.4 మీ మరియు గాలి వేగం 11 నాట్స్.",
        2: "ప్రయాణించవద్దు (DO NOT SAIL). నిషేధిత మెరైన్ సంరక్షిత ప్రాంతం. చేపల వేట పూర్తిగా నిషేధించబడింది.",
        3: "కొచ్చికి 15 కి.మీ నైరుతిలో అనుకూలమైన చేపల వేట ప్రాంతాలు గుర్తించబడ్డాయి. అలల ఎత్తు 1.2 మీ.",
    },
    "hi": {
        1: "कोच्चि के पास आज समुद्र और मौसम मछली पकड़ने के लिए सुरक्षित हैं। लहरों की ऊंचाई 1.4 मीटर और हवा की गति 11 नॉट है।",
        2: "नाव न ले जाएं (DO NOT SAIL)। यह एक प्रतिबंधित समुद्री संरक्षित क्षेत्र (MPA) है। मछली पकड़ना सख्त वर्जित है।",
        3: "कोच्चि से 15 किमी दक्षिण-पश्चिम में मछली पकड़ने के संभावित क्षेत्र (PFZ) मिले हैं। लहरों की ऊंचाई 1.2 मीटर है।",
    },
    "mr": {
        1: "कोची जवळ आज समुद्राची स्थिती आणि हवामान मासेमारीसाठी सुरक्षित आहे. लाटांची उंची 1.4 मीटर आणि वाऱ्याचा वेग 11 नॉट्स आहे.",
        2: "समुद्रात जाऊ नका (DO NOT SAIL). हे प्रतिबंधित सागरी संरक्षित क्षेत्र (MPA) आहे. येथे मासेमारीस सक्त मनाई आहे.",
        3: "कोचीच्या नैऋत्येस 15 किमी अंतरावर अनुकूल मासेमारी क्षेत्रे आढळली आहेत. लाटांची उंची 1.2 मीटर आहे.",
    },
}

# 3 Canonical scenarios per language
SCENARIOS: list[dict[str, Any]] = [
    {
        "q_idx": 1,
        "type": "safe",
        "landing_center": "Kochi",
        "inputs": {"lat": 9.93, "lon": 76.26, "latitude": 9.93, "longitude": 76.26},
        "english_query": "Can I fish safely near Kochi?",
        "english_reply": "Sea and weather conditions are safe for fishing near Kochi today. Wave height is 1.4m and wind speed is 11 knots.",
        "reference": {
            "expected_safety_tier": "safe",
            "mandate_do_not_sail": False,
        },
        "invariants": {
            "safety_tier_same": True,
            "arabic_numerals_only": True,
            "do_not_sail_preserved": True,
        },
    },
    {
        "q_idx": 2,
        "type": "veto_mpa",
        "landing_center": "Gulf of Mannar",
        "inputs": {"lat": 9.20, "lon": 79.10, "latitude": 9.20, "longitude": 79.10},
        "english_query": "Can I fish inside Gulf of Mannar Marine National Park?",
        "english_reply": "DO NOT SAIL. The requested location is inside a restricted Marine Protected Area. Fishing is strictly prohibited.",
        "reference": {
            "expected_safety_tier": "danger",
            "mandate_do_not_sail": True,
            "is_mpa": True,
        },
        "invariants": {
            "safety_tier_same": True,
            "arabic_numerals_only": True,
            "do_not_sail_preserved": True,
        },
    },
    {
        "q_idx": 3,
        "type": "code_mix",
        "landing_center": "Kochi",
        "inputs": {"lat": 9.93, "lon": 76.26, "latitude": 9.93, "longitude": 76.26},
        "english_query": "Where can I find fishing zones today near Kochi?",
        "english_reply": "Potential fishing zones are identified 15 km southwest of Kochi with wave height 1.2m and favorable chlorophyll gradients.",
        "reference": {
            "expected_safety_tier": "safe",
            "mandate_do_not_sail": False,
        },
        "invariants": {
            "safety_tier_same": True,
            "arabic_numerals_only": True,
            "do_not_sail_preserved": True,
        },
    },
]


def verify_golden_file(file_path: str) -> tuple[bool, str]:
    """Verifies that the golden dataset file exists, has 66 records, and 22 languages with valid schema."""
    path = Path(file_path)
    if not path.exists():
        return False, f"File {file_path} does not exist"

    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)

        if not isinstance(records, list):
            return False, "Expected JSON array of records"

        if len(records) != 66:
            return False, f"Expected 66 records, found {len(records)}"

        required_keys = {"example_id", "language", "query_vernacular", "frozen_reply", "invariants", "needs_human_fix", "inputs", "reference"}
        lang_counts: dict[str, int] = {}
        for r in records:
            missing = required_keys - set(r.keys())
            if missing:
                return False, f"Record {r.get('example_id')} missing keys: {missing}"
            ref = r.get("reference", {})
            if "expected_safety_tier" not in ref or "mandate_do_not_sail" not in ref:
                return False, f"Record {r.get('example_id')} reference missing expected_safety_tier or mandate_do_not_sail"

            lang = r.get("language")
            if not lang:
                return False, f"Missing language in record {r.get('example_id')}"
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

        for lang in TARGET_LANGS:
            if lang not in lang_counts:
                return False, f"Missing target language: {lang}"
            if lang_counts[lang] != 3:
                return False, f"Expected 3 records for {lang}, found {lang_counts[lang]}"

        return True, ""
    except Exception as exc:
        return False, f"Error verifying {file_path}: {exc}"


async def freeze_dataset(
    output_path: str = "data/golden_v1.json",
    target_langs: Optional[list[str]] = None,
    force_retranslate: bool = False,
    use_templates: bool = True,
) -> int:
    """
    Translates canonical queries and replies via Bhashini and writes to output_path atomically.
    Preserves existing records where needs_human_fix is False unless force_retranslate is True.
    """
    langs = target_langs or TARGET_LANGS
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Freezing golden dataset: %d language(s), force_retranslate=%s, templates=%s → %s",
        len(langs), force_retranslate, use_templates, out_file,
    )

    # Load existing records if present
    records_map: dict[str, dict[str, Any]] = {}
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            if isinstance(existing_data, list):
                for item in existing_data:
                    eid = item.get("example_id")
                    if eid:
                        records_map[eid] = item
        except Exception as exc:
            logger.warning("Could not read existing file %s: %s", out_file, exc)

    for lang in langs:
        n_bhashini = n_template = n_fallback = n_skipped = 0
        for scen in SCENARIOS:
            q_idx = scen["q_idx"]
            example_id = f"GOLDEN_V1_{lang.upper()}_{q_idx:02d}"

            # Check if existing record is already human-fixed
            if not force_retranslate and example_id in records_map:
                rec = records_map[example_id]
                if rec.get("needs_human_fix") is False:
                    logger.debug("Skipping already human-fixed record: %s", example_id)
                    n_skipped += 1
                    continue

            # Query vernacular
            vernacular_q = (
                VERNACULAR_QUERIES.get(lang, {}).get(q_idx)
                or scen["english_query"]
            )

            # Translate reply via Bhashini
            english_reply = scen["english_reply"]
            logger.debug("Translating %s via Bhashini (%d chars)", example_id, len(english_reply))
            trans_res: TranslationResult = await translate_from_english(
                english_reply,
                target_lang=lang,
            )

            if trans_res.translated:
                frozen_reply = trans_res.text
                needs_human_fix = False
                n_bhashini += 1
                logger.debug("Bhashini translated %s (%d chars)", example_id, len(frozen_reply))
            elif use_templates and lang in TEMPLATE_REPLIES and q_idx in TEMPLATE_REPLIES[lang]:
                frozen_reply = TEMPLATE_REPLIES[lang][q_idx]
                needs_human_fix = False
                n_template += 1
                logger.debug("Template fallback for %s", example_id)
            else:
                # If translation failed or API key missing, keep English and mark for human review
                frozen_reply = english_reply
                needs_human_fix = True
                n_fallback += 1
                logger.warning("English fallback (needs_human_fix) for %s", example_id)

            record: dict[str, Any] = {
                "example_id": example_id,
                "language": lang,
                "landing_center": scen.get("landing_center", ""),
                "query_vernacular": vernacular_q,
                "frozen_reply": frozen_reply,
                "invariants": dict(scen["invariants"]),
                "needs_human_fix": needs_human_fix,
                "inputs": dict(scen["inputs"]),
                "reference": dict(scen["reference"]),
            }
            records_map[example_id] = record
            await asyncio.sleep(0.05)

        logger.info(
            "Language %s done: bhashini=%d template=%d english_fallback=%d skipped=%d",
            lang, n_bhashini, n_template, n_fallback, n_skipped,
        )

    records = list(records_map.values())
    tmp_file = out_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    tmp_file.replace(out_file)

    n_fix = sum(1 for r in records if r.get("needs_human_fix"))
    logger.info(
        "Successfully froze %d records to %s (%d marked needs_human_fix)",
        len(records), out_file, n_fix,
    )
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time Bhashini freeze script for ORCA Golden Multilingual Dataset."
    )
    parser.add_argument(
        "--lang",
        default="all",
        help="Language code to freeze or 'all' for 22 Scheduled Indian Languages",
    )
    parser.add_argument(
        "--out",
        default="data/golden_v1.json",
        help="Destination JSON path (default: data/golden_v1.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the frozen dataset structure without calling network",
    )
    parser.add_argument(
        "--force-retranslate",
        action="store_true",
        help="Force re-translation of records even if needs_human_fix is false",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default INFO; DEBUG shows per-record source).",
    )

    args = parser.parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level, logging.INFO))

    if args.check:
        valid, err = verify_golden_file(args.out)
        if valid:
            print(f"PASS: {args.out} contains 66 verified multilingual records.")
            sys.exit(0)
        else:
            print(f"FAIL: {err}", file=sys.stderr)
            sys.exit(1)

    target_langs = TARGET_LANGS if args.lang == "all" else [args.lang]
    asyncio.run(
        freeze_dataset(
            output_path=args.out,
            target_langs=target_langs,
            force_retranslate=args.force_retranslate,
        )
    )


if __name__ == "__main__":
    main()
