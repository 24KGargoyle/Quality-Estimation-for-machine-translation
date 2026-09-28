from importlib.util import find_spec

from meeting_intel.config import get_settings
from meeting_intel.ingestion.parsers import SUPPORTED_EXTENSIONS
from meeting_intel.ingestion.parsers.extended import MEDIA_EXTENSIONS, LEGACY_EXTENSIONS, office_executable
from meeting_intel.security.file_safety import MAX_FILE_SIZE_BYTES

MAX_MEDIA_BYTES = 500 * 1024 * 1024


def file_limit(filename):
    extension = filename.rsplit('.', 1)[-1].lower()
    return MAX_MEDIA_BYTES if extension in MEDIA_EXTENSIONS else MAX_FILE_SIZE_BYTES


def capabilities():
    settings = get_settings()
    office = bool(office_executable())
    formats = []
    for ext in sorted([*SUPPORTED_EXTENSIONS, 'zip']):
        note = None
        if ext in LEGACY_EXTENSIONS and not office:
            note = 'LibreOffice conversion is not configured on this server.'
        elif ext in MEDIA_EXTENSIONS and (not settings.media_transcription_enabled or find_spec('faster_whisper') is None):
            note = 'Audio/video transcription is not enabled on this server.'
        elif ext == 'msg' and find_spec('extract_msg') is None:
            note = 'Outlook message extraction is not installed on this server.'
        formats.append({'extension': ext, 'ready': note is None, 'note': note, 'max_bytes': file_limit('file.' + ext)})
    return {'formats': formats}
