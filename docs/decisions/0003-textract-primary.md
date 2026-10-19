# 0003 Textract AnalyzeExpense as primary extraction

**Status:** accepted · Details: proposal chapter 2, "Texterkennung mit AnalyzeExpense"

## Context

Swiss receipts have abbreviated item names. Textract AnalyzeExpense returns normalized header fields and line items. An external AI API was the alternative.

## Decision

Textract AnalyzeExpense (synchronous, single-page documents only). The external AI API stays a fallback only if the ~20-receipt test set shows insufficient quality.

## Consequences

- One synchronous processing path; multi-page PDFs are rejected at upload.
- Textract's 5 calls/s limit: the worker is capped at reserved concurrency 10, and SQS buffers the rest.
