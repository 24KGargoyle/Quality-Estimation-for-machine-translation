"""Conservative acronym evidence checks; prior model answers are never evidence."""
import re


def requested_acronym(question):
    match = re.fullmatch(r'\s*(?i:what|wht)\s+(?i:is|does)\s+([A-Z][A-Z0-9-]{1,11})(?:\s+(?:mean|stand for))?\s*[?.!]*', question)
    return match.group(1) if match else None


def definition_sentences(text, acronym):
    token = re.escape(acronym)
    patterns = [rf'\b{token}\s*\([^)]{{3,120}}\)',
                rf'\b{token}\s+(?:stands for|means|is short for)\s+[^.\n]{{3,120}}',
                rf'\b[A-Za-z][A-Za-z /&-]{{3,100}}\s*\({token}\)']
    return [m.group(0).strip() for pattern in patterns for m in re.finditer(pattern, text)]


def unsupported_expansions(answer, evidence):
    """Check common generated 'ACRONYM (expanded name)' constructions."""
    for match in re.finditer(r'\b([A-Z][A-Z0-9-]{1,11})\s*\(([A-Za-z][A-Za-z /&-]{3,100})\)', answer):
        acronym, expansion = match.groups()
        normalized = re.sub(r'\s+', ' ', expansion).strip().casefold()
        supported = definition_sentences(evidence, acronym)
        if not any(normalized in re.sub(r'\s+', ' ', item).casefold() for item in supported):
            return True
    return False
