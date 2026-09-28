# Extended historical imports

The existing import API, background jobs, tenant authorization, duplicate detection,
storage, parsers, search index and citations are reused. The UI reads format and
size capabilities from authenticated `GET /api/historical-imports/capabilities`.
It distinguishes acceptance for upload from successful extraction/indexing.

| Format | Processing |
|---|---|
| DOCX, PDF, PPTX, XLSX, CSV, TXT, VTT | Existing parsers |
| MSG, EML | Email headers and body; supported document attachments extracted with their original source names |
| XLS | Native xlrd extraction, including sheet names and Excel dates |
| XLSM, PPTM, PPSX | Existing Office parsers; macros are not executed |
| DOC, PPT, PPS, ODT, ODP, ODS | Headless LibreOffice conversion, then existing parsers |
| MP3, MP4, WAV, M4A, AAC, FLAC, OGG, OPUS, WMA, WEBM, MOV, MKV, AVI, WMV, M4V | Local speech transcription with timestamped source sections |
| MD, MARKDOWN, HTML, HTM, RTF, JSON, XML, LOG | Text extraction; HTML scripts/styles omitted |
| ZIP | Bounded expansion followed by individual child-file imports |

This is an explicit list, not a claim to decode every file format. Unknown formats
remain clearly reported. Encrypted/corrupt files cannot be made searchable merely
by accepting their extension. Images and scanned PDFs require a separate OCR
integration; video frames, slides visible only in video, and embedded Office images
are not visually analyzed. Email media attachments, nested messages and archives
must be uploaded separately; the result records a warning instead of silently
pretending they were indexed.

## Setup

Install `app/backend/requirements.txt` into the backend environment. For recordings:

```dotenv
MEDIA_TRANSCRIPTION_ENABLED=true
MEDIA_TRANSCRIPTION_MODEL=base
```

The model setting also accepts a local faster-whisper model directory. Named models
download their weights on first use; provision a local model directory for offline
deployments. Audio decoding uses PyAV's bundled codecs. The implementation follows
the [faster-whisper project documentation](https://github.com/SYSTRAN/faster-whisper).
No uploaded recording is sent to a speech API. Transcription runs on CPU, one file
at a time, outside the request event loop. Long recordings can take substantial time.
Text embeddings and answers still use the application's existing configured services.

For legacy Office/OpenDocument files, install LibreOffice and set:

```dotenv
OFFICE_CONVERTER_PATH=/path/to/soffice
```

The application also detects standard Windows LibreOffice installations or a
`soffice` executable on PATH. Conversion uses a separate temporary profile, disables
macros, hides its window, and imposes a 120-second timeout. See the official
[LibreOffice command-line documentation](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html).
Restart the backend after changing environment settings. The local workspace was
configured with a downloaded model and workspace-local converter; these binaries
are ignored by Git and must be provisioned separately on other deployments.

## Limits and reporting

- Documents and archives: 50 MB per uploaded file; audio/video: 500 MB per file.
- Import: 2 GB total and 2,000 files, including expanded archive entries.
- ZIP expansion: 250 MB, maximum depth 3, bounded compression ratio, no traversal,
  symlinks, encrypted entries or colliding normalized paths. Entries are read in
  memory, never extracted to uploaded filesystem paths.
- Email extraction: at most 100 attachments / 50 MB of attachment bytes; unsupported
  attachments are recorded in the import result's warning text.
- Speech recognition is probabilistic: verify important wording against the
  recording. Silence/no audio track is reported; it is not fabricated into text.
- Parsing runs in worker threads. Background jobs remain process-local, as before;
  restarting the backend interrupts an in-flight import.

Skipped files from an earlier upload must be selected and uploaded again. The old
frontend never sent them to the backend, so the application cannot recover those
bytes retroactively. Successfully imported duplicates are still detected.

Customer ownership remains separate from file decoding: uploading a file does not
automatically mark it as an approved SOP or assign another customer's records to BP.
