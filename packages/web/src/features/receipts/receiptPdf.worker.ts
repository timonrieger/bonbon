import { EncryptedPDFError, PDFDocument } from '@pdfme/pdf-lib';
import { assertCompletePdf } from './pdfCompletion';

self.onmessage = async ({ data: file }: MessageEvent<File>) => {
  let error: string | null = null;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (
      !bytes.subarray(0, 5).every((byte, index) => byte === '%PDF-'.charCodeAt(index)) ||
      bytes.length < 5
    ) {
      throw new Error('Missing PDF header');
    }
    assertCompletePdf(bytes);
    const document = await PDFDocument.load(bytes, {
      ignoreEncryption: false,
      updateMetadata: false,
      throwOnInvalidObject: true
    });
    const pages = document.getPageCount();
    if (pages === 0) error = 'Das PDF enthält keine Seite.';
    if (pages > 1) error = 'Das PDF darf nur eine Seite enthalten.';
  } catch (cause) {
    error =
      cause instanceof EncryptedPDFError
        ? 'Verschlüsselte oder passwortgeschützte PDFs werden nicht unterstützt.'
        : 'Das PDF konnte nicht gelesen werden. Bitte wähle ein gültiges PDF.';
  }
  self.postMessage(error);
};
