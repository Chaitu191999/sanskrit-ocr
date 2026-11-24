# Third-party software and fonts

Sanskrit OCR's own code is licensed under the GNU AGPL v3 (see `LICENSE`). The
built app bundles the following, each under its own license:

| Component | Used for | License |
|---|---|---|
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) 5.x | reading the text | Apache 2.0 |
| Libraries shipped with Tesseract (Leptonica, libjpeg-turbo, libpng, libtiff, libwebp, OpenJPEG, giflib, zlib) | image file formats | BSD / zlib-style permissive licenses |
| [tessdata_fast / tessdata_best](https://github.com/tesseract-ocr/tessdata_fast) models (`script/Devanagari`, `osd`) | Fast / Accurate reading, page orientation | Apache 2.0 |
| [Qt 6 / PySide6](https://doc.qt.io/qtforpython-6/) | the interface | LGPL v3 |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | opening PDFs | AGPL v3 |
| [python-docx](https://github.com/python-openxml/python-docx) | writing Word files | MIT |
| [Pillow](https://github.com/python-pillow/Pillow) | images | MIT-CMU (HPND) |
| [NumPy](https://numpy.org) | image processing | BSD 3-Clause |
| [Tiro Devanagari Sanskrit](https://github.com/TiroTypeworks/Indic) (Tiro Typeworks) | headings, Devanagari | SIL Open Font License 1.1 (`sanskritocr/assets/fonts/OFL.txt`) |
| [Hanken Grotesk](https://fonts.google.com/specimen/Hanken+Grotesk) (Hanken Design Co.) | body text | SIL Open Font License 1.1 |

The text shown on the welcome screen's manuscript leaf is from the Charaka
Saṃhitā and the Aṣṭāṅga Hṛdaya, which are in the public domain.
