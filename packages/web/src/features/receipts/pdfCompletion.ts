import {
  decodePDFRawStream,
  PDFArray,
  PDFContext,
  PDFDict,
  PDFName,
  PDFNumber,
  PDFObjectParser,
  PDFRawStream
} from '@pdfme/pdf-lib';

function isWhitespace(byte: number) {
  return byte === 0 || byte === 9 || byte === 10 || byte === 12 || byte === 13 || byte === 32;
}

function incomplete(): never {
  throw new Error('Incomplete PDF revision');
}

function integer(value: string | number): number {
  const number = typeof value === 'number' ? value : /^\d+$/.test(value) ? Number(value) : NaN;
  if (!Number.isSafeInteger(number) || number < 0) incomplete();
  return number;
}

// Read just the cross-reference section framing. Delegate PDF object syntax
// and stream decoding to pdf-lib, then let its document parser read the page tree.
class CrossReferenceParser extends PDFObjectParser {
  static fromSection(bytes: Uint8Array) {
    const context = PDFContext.create();
    const parser = PDFObjectParser.forBytes(bytes, context) as CrossReferenceParser;
    return new CrossReferenceParser(parser.bytes, context);
  }

  token() {
    this.skipWhitespaceAndComments();
    let token = '';
    while (!this.bytes.done()) {
      const byte = this.bytes.peek();
      if (isWhitespace(byte) || '()<>[]{}/%'.includes(String.fromCharCode(byte))) break;
      if (token.length === 24) incomplete();
      token += String.fromCharCode(this.bytes.next());
    }
    return token;
  }

  atEnd() {
    this.skipWhitespaceAndComments();
    return this.bytes.done();
  }
}

function readSection(bytes: Uint8Array, offset: number, footer: number) {
  const parser = CrossReferenceParser.fromSection(bytes.subarray(offset, footer));
  const first = parser.token();
  let trailer: PDFDict;
  if (first === 'xref') {
    let maxObject = 0;
    for (let start = parser.token(); start !== 'trailer'; start = parser.token()) {
      const firstObject = integer(start);
      const count = integer(parser.token());
      maxObject = Math.max(maxObject, integer(firstObject + count));
      for (let index = 0; index < count; index++) {
        const address = integer(parser.token());
        integer(parser.token());
        const kind = parser.token();
        if ((kind !== 'n' && kind !== 'f') || (kind === 'n' && address >= footer)) incomplete();
      }
    }
    const object = parser.parseObject();
    if (!(object instanceof PDFDict) || maxObject === 0) incomplete();
    trailer = object;
    if (maxObject > trailerInteger(trailer, 'Size')) incomplete();
  } else {
    if (!integer(first)) incomplete();
    integer(parser.token());
    if (parser.token() !== 'obj') incomplete();
    const stream = parser.parseObject();
    if (
      !(stream instanceof PDFRawStream) ||
      stream.dict.get(PDFName.of('Type')) !== PDFName.of('XRef') ||
      parser.token() !== 'endobj'
    ) {
      incomplete();
    }
    trailer = stream.dict;
    const width = trailer.lookupMaybe(PDFName.of('W'), PDFArray);
    if (width?.size() !== 3) incomplete();
    const rowSize = width.asArray().reduce((total, value) => {
      if (!(value instanceof PDFNumber)) incomplete();
      return total + integer(value.asNumber());
    }, 0);
    const size = trailerInteger(trailer, 'Size');
    const ranges = trailer.lookupMaybe(PDFName.of('Index'), PDFArray);
    let rows = size;
    if (ranges) {
      if (!ranges.size() || ranges.size() % 2 !== 0) incomplete();
      rows = 0;
      for (let index = 0; index < ranges.size(); index += 2) {
        const start = integer(ranges.lookup(index, PDFNumber).asNumber());
        const count = integer(ranges.lookup(index + 1, PDFNumber).asNumber());
        if (start + count > size) incomplete();
        rows += count;
      }
    }
    const length = trailer.get(PDFName.of('Length'));
    if (length instanceof PDFNumber && length.asNumber() !== stream.getContentsSize()) incomplete();
    if (!rowSize || !rows || decodePDFRawStream(stream).decode().length !== rowSize * rows)
      incomplete();
  }
  const prev = trailer.get(PDFName.of('Prev'));
  if (prev !== undefined && !(prev instanceof PDFNumber)) incomplete();
  const previous = prev instanceof PDFNumber ? integer(prev.asNumber()) : undefined;
  if (previous !== undefined && (previous === offset || previous >= footer)) incomplete();
  return { atEnd: parser.atEnd(), previous };
}

function trailerInteger(dict: PDFDict, key: string): number {
  const value = dict.get(PDFName.of(key));
  if (!(value instanceof PDFNumber)) incomplete();
  return integer(value.asNumber());
}

export function assertCompletePdf(bytes: Uint8Array) {
  let end = bytes.length;
  function previousToken() {
    while (end > 0 && isWhitespace(bytes[end - 1])) end--;
    const tokenEnd = end;
    while (end > 0 && !isWhitespace(bytes[end - 1])) {
      if (tokenEnd - end === 24) incomplete();
      end--;
    }
    return String.fromCharCode(...bytes.subarray(end, tokenEnd));
  }

  if (previousToken() !== '%%EOF') incomplete();
  const offset = integer(previousToken());
  if (previousToken() !== 'startxref' || offset <= 0 || offset >= end) incomplete();

  const section = readSection(bytes, offset, end);
  if (section.atEnd) {
    if (section.previous !== undefined) {
      if (section.previous >= offset) incomplete();
      readSection(bytes, section.previous, offset);
    }
    return;
  }
  // Linearized files can point to a first-page xref near the beginning, whose
  // forward /Prev points to the main xref at the physical end of the file.
  if (
    section.previous &&
    section.previous > offset &&
    readSection(bytes, section.previous, end).atEnd
  )
    return;
  incomplete();
}
