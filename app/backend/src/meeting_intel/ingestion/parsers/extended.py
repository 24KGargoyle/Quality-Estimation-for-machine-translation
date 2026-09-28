"""Additional formats feeding the existing normalized-document pipeline."""
from __future__ import annotations

from email import policy
from email.parser import BytesParser
from functools import lru_cache
from html.parser import HTMLParser
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import Lock

from meeting_intel.config import get_settings
from meeting_intel.ingestion.documents import NormalizedDocument, ParseResult, UnsupportedFileError
from .base import DocumentParser
from .textutil import split_text

MEDIA_EXTENSIONS = {'mp3', 'mp4', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'wma', 'webm', 'mov', 'mkv', 'avi', 'wmv', 'm4v'}
LEGACY_EXTENSIONS = {'doc': 'docx', 'ppt': 'pptx', 'pps': 'pptx', 'odt': 'docx', 'odp': 'pptx', 'ods': 'xlsx'}


def text_result(text, kwargs, kind='supporting_document'):
    extension = Path(kwargs['filename']).suffix.lower().lstrip('.')
    docs = [NormalizedDocument(document_id=f"{kwargs['document_id_prefix']}:{i}",
        tenant_id=kwargs['tenant_id'], meeting_id=kwargs['meeting_id'], title=kwargs['title'],
        source_file=kwargs['filename'], relative_path=kwargs['relative_path'], file_type=extension,
        document_type=kind, content=piece) for i, piece in enumerate(split_text(text))]
    return ParseResult(documents=docs, warnings=[] if docs else ['No extractable text found.'])


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'br', 'div', 'tr', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_text(text):
    parser = _HTMLText()
    parser.feed(text)
    return ''.join(parser.parts)


class RichTextParser(DocumentParser):
    def parse(self, *, content, **kwargs):
        text = content.decode('utf-8-sig', errors='replace')
        extension = Path(kwargs['filename']).suffix.lower()
        if extension in ('.html', '.htm'):
            text = html_text(text)
        elif extension == '.rtf':
            try:
                from striprtf.striprtf import rtf_to_text
            except ImportError:
                raise UnsupportedFileError('RTF extraction requires striprtf.') from None
            text = rtf_to_text(text)
        return text_result(text, kwargs)


class EmailParser(DocumentParser):
    def parse(self, *, content, **kwargs):
        if kwargs['filename'].lower().endswith('.eml'):
            message = BytesParser(policy=policy.default).parsebytes(content)
            body = message.get_body(preferencelist=('plain', 'html'))
            text = body.get_content() if body else ''
            if body and body.get_content_type() == 'text/html':
                text = html_text(text)
            headers = '\n'.join(f'{key}: {message.get(key, "")}' for key in ('Subject', 'From', 'To', 'Cc', 'Date'))
            attachments = [(p.get_filename() or 'attachment', p.get_payload(decode=True)) for p in message.iter_attachments()]
        else:
            try:
                import extract_msg
            except ImportError:
                raise UnsupportedFileError('Outlook MSG extraction requires extract-msg.') from None
            try:
                with extract_msg.openMsg(content) as message:
                    headers = '\n'.join(f'{label}: {getattr(message, attr, "") or ""}' for label, attr in
                        [('Subject', 'subject'), ('From', 'sender'), ('To', 'to'), ('Cc', 'cc'), ('Date', 'date')])
                    text = message.body or html_text((message.htmlBody or b'').decode('utf-8', errors='replace'))
                    attachments = [(a.longFilename or a.shortFilename or 'attachment', a.data) for a in message.attachments]
            except Exception as exc:
                raise UnsupportedFileError('Could not read this Outlook MSG file.') from exc
        result = text_result(headers + '\n\n' + str(text), kwargs, kind='email')
        from . import ParserFactory
        from meeting_intel.security.file_safety import sanitize_filename, MAX_FILE_SIZE_BYTES
        total = 0
        for index, (name, data) in enumerate(attachments):
            if index >= 100:
                result.warnings.append('Attachment limit reached (100).')
                break
            name = sanitize_filename(name)
            ext = Path(name).suffix.lstrip('.').lower()
            total += len(data) if isinstance(data, bytes) else 0
            parser = ParserFactory.get_parser(ext)
            if not isinstance(data, bytes) or total > MAX_FILE_SIZE_BYTES or ext in {'msg', 'eml', 'zip'} or ext in MEDIA_EXTENSIONS or parser is None:
                result.warnings.append(f'Attachment {name}: upload separately for processing.')
                continue
            try:
                parsed = parser.parse(content=data, **(kwargs | {'filename': name,
                    'relative_path': kwargs['relative_path'] + '/' + name,
                    'document_id_prefix': kwargs['document_id_prefix'] + f':attachment{index}'}))
                for doc in parsed.documents:
                    doc.source_file = kwargs['filename'] + ' / ' + name
                result.documents.extend(parsed.documents)
                result.warnings.extend(parsed.warnings)
            except UnsupportedFileError:
                result.warnings.append(f'Attachment {name}: could not extract; upload separately.')
        return result


class LegacyExcelParser(DocumentParser):
    def parse(self, *, content, **kwargs):
        try:
            import xlrd
        except ImportError:
            raise UnsupportedFileError('Legacy .xls extraction requires xlrd.') from None
        try:
            book = xlrd.open_workbook(file_contents=content, on_demand=True)
        except Exception as exc:
            raise UnsupportedFileError('Legacy .xls file is corrupt or encrypted.') from exc
        result = ParseResult()
        try:
            for sheet in book.sheets():
                rows = []
                for row in range(sheet.nrows):
                    values = []
                    for col in range(sheet.ncols):
                        cell = sheet.cell(row, col)
                        value = xlrd.xldate.xldate_as_datetime(cell.value, book.datemode).isoformat() if cell.ctype == xlrd.XL_CELL_DATE else cell.value
                        values.append(str(value))
                    rows.append(' | '.join(values))
                parsed = text_result('\n'.join(rows), kwargs, kind='spreadsheet')
                for doc in parsed.documents:
                    doc.document_id = f"{kwargs['document_id_prefix']}:{len(result.documents)}"
                    doc.sheet_name = sheet.name
                    result.documents.append(doc)
        finally:
            book.release_resources()
        return result


def office_executable():
    configured = get_settings().office_converter_path
    if configured:
        return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    return shutil.which('soffice') or next((str(p) for p in [Path('C:/Program Files/LibreOffice/program/soffice.exe'),
        Path('C:/Program Files (x86)/LibreOffice/program/soffice.exe')] if p.is_file()), None)


class OfficeConversionParser(DocumentParser):
    def parse(self, *, content, **kwargs):
        extension = Path(kwargs['filename']).suffix.lstrip('.').lower()
        executable = office_executable()
        if not executable:
            raise UnsupportedFileError(f'Legacy .{extension} / OpenDocument conversion requires LibreOffice; configure OFFICE_CONVERTER_PATH.')
        target = LEGACY_EXTENSIONS[extension]
        with tempfile.TemporaryDirectory(prefix='meeting-office-') as temp:
            root = Path(temp)
            source = root / f'input.{extension}'
            source.write_bytes(content)
            # Isolated profile with macros disabled; no shell, fixed generated filenames.
            profile = root / 'profile'
            (profile / 'user').mkdir(parents=True)
            (profile / 'user/registrymodifications.xcu').write_text(
                '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
                '<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>')
            try:
                subprocess.run([executable, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo',
                    '--nodefault', '--nofirststartwizard', '--convert-to', target, '--outdir', str(root), str(source)],
                    capture_output=True, timeout=120, check=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.SubprocessError) as exc:
                raise UnsupportedFileError('Office conversion failed or timed out.') from exc
            output = root / f'input.{target}'
            if not output.is_file():
                raise UnsupportedFileError('Office conversion produced no readable document.')
            from . import ParserFactory
            result = ParserFactory.get_parser(target).parse(content=output.read_bytes(), **(kwargs | {'filename': f'input.{target}'}))
            for doc in result.documents:
                doc.source_file, doc.file_type = kwargs['filename'], extension
            return result


_transcription_lock = Lock()


@lru_cache(maxsize=1)
def speech_model(model_name):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise UnsupportedFileError('Audio/video transcription requires faster-whisper.') from None
    return WhisperModel(model_name, device='cpu', compute_type='int8')


class MediaParser(DocumentParser):
    def parse(self, *, content, **kwargs):
        settings = get_settings()
        if not settings.media_transcription_enabled:
            raise UnsupportedFileError('Enable MEDIA_TRANSCRIPTION_ENABLED to transcribe audio/video files.')
        try:
            with _transcription_lock:
                model = speech_model(settings.media_transcription_model)
                segments, _ = model.transcribe(io.BytesIO(content), beam_size=5, vad_filter=True)
                documents = []
                for segment in segments:
                    if not segment.text.strip():
                        continue
                    for doc in text_result(segment.text.strip(), kwargs, kind='transcript').documents:
                        doc.document_id = f"{kwargs['document_id_prefix']}:{len(documents)}"
                        doc.start_time, doc.end_time = segment.start, segment.end
                        doc.section = f'Audio {segment.start:.1f}s–{segment.end:.1f}s'
                        documents.append(doc)
                return ParseResult(documents=documents, warnings=[] if documents else ['No intelligible speech was detected.'])
        except UnsupportedFileError:
            raise
        except Exception as exc:
            raise UnsupportedFileError('Audio/video transcription failed. Check the model installation and that the file has a readable audio track.') from exc
