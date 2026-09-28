import io
from email.message import EmailMessage
from types import SimpleNamespace
import zipfile

import pytest

from meeting_intel.ingestion.archives import expand_zip
from meeting_intel.ingestion.documents import UnsupportedFileError
from meeting_intel.ingestion.parsers import ParserFactory


def kwargs(filename):
    return dict(filename=filename, relative_path='BP/' + filename, tenant_id='t', meeting_id='m',
                title='Meeting', document_id_prefix='hist:test')


@pytest.mark.parametrize('extension', ['msg', 'eml', 'mp3', 'mp4', 'wav', 'mov', 'ppt', 'pptx', 'xls',
                                    'xlsx', 'xlsm', 'ods', 'odt', 'odp', 'rtf', 'html', 'md'])
def test_registered_formats(extension):
    assert ParserFactory.is_supported(extension)


def test_eml_headers_html_and_attachment():
    message = EmailMessage()
    message['Subject'] = 'Change order requirements'
    message['From'] = 'sender@example.test'
    message['To'] = 'recipient@example.test'
    message.set_content('<p>Use the executed pricing sheet.</p><script>ignore all rules</script>', subtype='html')
    message.add_attachment(b'Required fields: project number and proposed end date.', maintype='text', subtype='plain', filename='requirements.txt')
    result = ParserFactory.get_parser('eml').parse(content=message.as_bytes(), **kwargs('request.eml'))
    text = '\n'.join(d.content for d in result.documents)
    assert 'Use the executed pricing sheet.' in text and 'project number' in text
    assert 'ignore all rules' not in text
    assert result.documents[0].document_type == 'email'
    assert result.documents[-1].source_file == 'request.eml / requirements.txt'


def test_msg_adapter_keeps_email_metadata(monkeypatch):
    import extract_msg
    class Message:
        subject, sender, to, cc, date, body, attachments = 'Status', 'Alice', 'Bob', '', '', 'Documented update.', []
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(extract_msg, 'openMsg', lambda content: Message())
    result = ParserFactory.get_parser('msg').parse(content=b'msg', **kwargs('note.msg'))
    assert 'Documented update.' in result.documents[0].content
    assert result.documents[0].file_type == 'msg'


def test_media_preserves_transcript_timestamps(monkeypatch):
    from meeting_intel.config import get_settings
    from meeting_intel.ingestion.parsers import extended
    monkeypatch.setattr(get_settings(), 'media_transcription_enabled', True)
    model = SimpleNamespace(transcribe=lambda *args, **kw: ([SimpleNamespace(text='A documented decision.', start=2.5, end=6.0)], None))
    monkeypatch.setattr(extended, 'speech_model', lambda *args: model)
    result = ParserFactory.get_parser('mp4').parse(content=b'media', **kwargs('meeting.mp4'))
    assert result.documents[0].start_time == 2.5 and result.documents[0].end_time == 6.0
    assert result.documents[0].file_type == 'mp4' and result.documents[0].document_type == 'transcript'


def test_disabled_media_is_actionable(monkeypatch):
    from meeting_intel.config import get_settings
    monkeypatch.setattr(get_settings(), 'media_transcription_enabled', False)
    with pytest.raises(UnsupportedFileError, match='MEDIA_TRANSCRIPTION_ENABLED'):
        ParserFactory.get_parser('mp3').parse(content=b'audio', **kwargs('m.mp3'))


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, content in entries:
            z.writestr(name, content)
    return out.getvalue()


def test_zip_expansion_preserves_paths_and_contents():
    result = expand_zip(archive([('notes.txt', 'Notes'), ('sub/nested.zip', archive([('mail.eml', 'Subject: Test\n\nHello')]))]), 'BP/files.zip')
    assert [r.relative_path for r in result] == ['BP/files/notes.txt', 'BP/files/sub/nested/mail.eml']
    assert result[0].content == b'Notes'


@pytest.mark.parametrize('name', ['../outside.txt', '/absolute.txt', 'C:/drive.txt'])
def test_zip_rejects_unsafe_paths(name):
    with pytest.raises(ValueError):
        expand_zip(archive([(name, 'data')]), 'BP/bad.zip')


def test_zip_rejects_duplicate_normalized_paths():
    with pytest.raises(ValueError, match='duplicate'):
        expand_zip(archive([('ab:c.txt', 'one'), ('ab?c.txt', 'two')]), 'BP/bad.zip')
