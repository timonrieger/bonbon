import { ContentType } from '@/api';

export const RECEIPT_IMAGE_TYPES = [ContentType.ImageJpeg, ContentType.ImagePng] as const;
type ReceiptImageType = (typeof RECEIPT_IMAGE_TYPES)[number];

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const TARGET_BYTES = 500 * 1024;
const TARGET_LONG_EDGE = 2800;
const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const JPEG_SIGNATURE = [0xff, 0xd8, 0xff];

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function validateReceiptImage(
  file: File
): { contentType: ReceiptImageType } | { error: string } {
  const contentType = RECEIPT_IMAGE_TYPES.find((type) => type === file.type);
  if (!contentType) return { error: 'Erlaubt sind JPG, PNG und einseitige PDFs.' };
  if (file.size === 0) return { error: 'Die Datei ist leer.' };
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      error: `Die Datei ist zu gross (${formatBytes(file.size)}). Bitte wähle ein Foto mit höchstens 5 MB.`
    };
  }
  return { contentType };
}

function encodeJpeg(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob?.type === ContentType.ImageJpeg && blob.size > 0) {
          resolve(blob);
        } else {
          reject(new Error('JPEG encoding failed'));
        }
      },
      ContentType.ImageJpeg,
      quality
    );
  });
}

export async function prepareReceiptImage(
  file: File,
  signal: AbortSignal
): Promise<{ file: File; contentType: ReceiptImageType }> {
  signal.throwIfAborted();
  const validation = validateReceiptImage(file);
  if ('error' in validation) throw new Error(validation.error);

  const { contentType } = validation;
  const signature = contentType === ContentType.ImagePng ? PNG_SIGNATURE : JPEG_SIGNATURE;
  const header = new Uint8Array(await file.slice(0, signature.length).arrayBuffer());
  signal.throwIfAborted();
  if (!signature.every((byte, index) => header[index] === byte)) {
    throw new Error(
      'Der Dateiinhalt entspricht keinem gültigen JPG oder PNG des gewählten Dateityps.'
    );
  }

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  } catch {
    signal.throwIfAborted();
    throw new Error('Das Bild konnte nicht gelesen werden. Bitte wähle ein gültiges JPG oder PNG.');
  }

  try {
    signal.throwIfAborted();
    if (file.size <= TARGET_BYTES) return { file, contentType };

    const longEdge = Math.max(bitmap.width, bitmap.height);
    const shortEdge = Math.min(bitmap.width, bitmap.height);
    // Cap the width loss on narrow receipts instead of requiring a fixed 1400 px short edge.
    const preferredShortEdge = Math.min(1400, Math.max(640, shortEdge * 0.85));
    const minimumShortEdge = Math.min(1100, Math.max(480, shortEdge * 0.75));
    const scale = Math.min(
      1,
      Math.max(TARGET_LONG_EDGE / longEdge, preferredShortEdge / shortEdge)
    );
    const smallerScale = Math.min(scale, Math.max(scale * 0.8, minimumShortEdge / shortEdge));
    const canvas = document.createElement('canvas');
    try {
      function draw(atScale: number) {
        canvas.width = Math.max(1, Math.round(bitmap.width * atScale));
        canvas.height = Math.max(1, Math.round(bitmap.height * atScale));
        const context = canvas.getContext('2d', { alpha: false });
        if (!context) throw new Error('Canvas unavailable');

        // JPEG cannot store transparency. Composite transparent areas over white.
        context.fillStyle = '#fff';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.imageSmoothingQuality = 'high';
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      }

      draw(scale);
      let output = await encodeJpeg(canvas, 0.9);
      signal.throwIfAborted();
      if (output.size > TARGET_BYTES) {
        // Encode from the same pixels to avoid accumulating JPEG artifacts.
        const candidate = await encodeJpeg(canvas, 0.84);
        signal.throwIfAborted();
        if (candidate.size < output.size) output = candidate;
      }
      if (output.size > TARGET_BYTES && smallerScale <= scale * 0.95) {
        // Resize from the oriented original, never from a previously encoded JPEG.
        draw(smallerScale);
        const candidate = await encodeJpeg(canvas, 0.86);
        signal.throwIfAborted();
        if (candidate.size < output.size) output = candidate;
      }

      // A small saving does not justify replacing a validated original.
      if (output.size >= file.size * 0.9) return { file, contentType };
      const compressed = new File([output], `${file.name.replace(/\.[^.]+$/, '')}.jpg`, {
        type: ContentType.ImageJpeg
      });
      const compressedValidation = validateReceiptImage(compressed);
      if ('error' in compressedValidation) throw new Error(compressedValidation.error);
      return { file: compressed, contentType: compressedValidation.contentType };
    } catch {
      signal.throwIfAborted();
      throw new Error('Das Bild konnte nicht verkleinert werden. Bitte wähle ein anderes Foto.');
    } finally {
      canvas.width = 0;
      canvas.height = 0;
    }
  } finally {
    bitmap.close();
  }
}
