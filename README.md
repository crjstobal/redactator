<p align="center"><img src="docs/logo.png" width="220" alt="Redactator, a small robot holding a big black marker"></p>

# Redactator

**Drop photos, PDFs or screen recordings, tick what to hide, get back clean copies with solid black boxes.** Everything runs on your own computer: open-weight models (Gemma 4 and GLiNER2-PII) read the text, nothing is uploaded, and there is no per-file bill.

Made for freelancers and small teams who share client material all day: video editors cutting tutorials from a client's dashboard, support agents sending screenshots, consultants forwarding invoices.

## What it does

- **Photos and screenshots**: finds the private text and faces, paints opaque boxes (never blur, which can be reversed), and strips EXIF and GPS data.
- **PDFs**: true redaction. The text under each box is deleted from the file, not just covered, so it cannot be copied or searched. Clickable `mailto:` links under a box and document metadata are removed too. Scanned pages and screenshots pasted into a PDF are read with OCR.
- **Videos**: samples a few frames per second, skips frames that did not change, and re-renders the video with the boxes following text while it scrolls. Audio is kept.
- **Tick what to hide**: names, faces, emails, phone numbers, addresses, birth dates, ID numbers, card and bank details, passwords and API keys, licence plates, company names, IP addresses.
- **Your own list**: type exact text the tools could never guess (your car's plate `9256YT`, a project codename). Matching tolerates spacing and one OCR slip. Short descriptions like "my client's company" are handed to Gemma.
- **Keep visible**: your own studio name or email stays untouched.
- **Many files at once**: drop a folder's worth of PDFs, photos and videos, check them in one go, export them all.
- **You stay in charge**: every finding is listed with a checkbox. Untick what should stay visible, draw extra boxes by hand, then export. The original files are never modified.

## How it works

```
file ──► OCR (RapidOCR, ONNX) ──► lines of words with boxes ──┬─► fixed patterns ────┐
     │                                                        ├─► GLiNER2-PII ───────┤
     │                                                        └─► Gemma 4 ───────────┤
     └─► face detector (YuNet) ──────────────────────────────────────────────────────┤
                                                                                     ▼
                                                      findings ──► your review ──► export
```

Three independent detectors read every line, and their results are merged, so a miss by one is caught by another:

1. **Fixed patterns** for data with a known shape: emails, phone numbers, card numbers (with a Luhn check), IBANs, licence plates, API keys and tokens, passwords next to a label. They never depend on a model.
2. **[GLiNER2-PII](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi)**, a 0.2B open model (Apache 2.0) trained only to spot personal data in 7 languages. Very high recall on names, birth dates and ID numbers.
3. **Gemma 4 E4B** via [Ollama](https://ollama.com), for anything that needs judgement: full postal addresses, company names, or whatever you describe in your own list.

Anything a model recognises once is hidden everywhere it appears in the file. PDFs without a text layer (scans, photos of documents) are read with OCR automatically.

## Install

1. Install [Ollama](https://ollama.com/download) and pull the model (about 9.5 GB, once):
   ```bash
   ollama pull gemma4:e4b
   ```
2. Install Redactator (Python 3.10 or newer):
   ```bash
   pip install git+https://github.com/crjstobal/redactator
   ```

The PII model (about 1.2 GB) downloads itself from Hugging Face on first use. Without Ollama, Redactator still works with the fixed patterns and the PII model.

## Use

Desktop app (macOS, Windows, Linux):

```bash
redactator-app
```

Command line:

```bash
redactator invoice.pdf                                     # default categories
redactator recording.mov --also "9256YT" --keep "BrightDesk" -o clean.mp4
redactator *.png --hide faces,phones --dry-run             # list findings only
redactator scans/*.pdf --hide all
```

Use a different local model with `REDACTATOR_MODEL=gemma4:12b`.

## Why open models

The files people need to redact are, by definition, the ones they should not upload. A cloud API would mean sending a client's invoice to a third party in order to hide the client's data from a third party. With an open-weight model running locally:

- the file never leaves the machine, which is the only honest privacy promise;
- each file costs nothing to process, so a freelancer can run it on every export without watching a meter;
- it works offline, on a train, or inside a client's locked-down network;
- the model can be swapped or fine-tuned for a niche (medical forms, legal discovery) without asking anyone.

## Try it

```bash
python samples/make_samples.py     # fictional CRM screenshot, invoice PDF and screen recording
redactator samples/invoice.pdf --also "Brightlane"
```

All names, emails and numbers in the samples are made up.

## Development

```bash
pip install -e ".[dev]"
pytest
python -m redactator.app --debug
```

## License

AGPL-3.0-or-later (Redactator uses PyMuPDF, which is AGPL). The interface font, Bricolage Grotesque, is under the SIL Open Font License.
