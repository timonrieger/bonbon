import { useIsMutating, useQueryClient } from '@tanstack/react-query';
import { useLayoutEffect, useRef, useState } from 'react';
import { ContentType, createReceipt } from '@/api';
import { requestPrivateResource } from '@/api/privateQuery';
import { uploadToS3 } from '@/api/receipts';
import { useSessionMutation, useSessionSignal } from '@/components/AuthenticatedSession';
import {
  handleHouseholdAccessError,
  householdAccessKey
} from '@/features/households/householdAccess';
import { prepareReceiptImage, validateReceiptImage } from './receiptImage';
import { isPdfCandidate, validateReceiptPdf } from './receiptPdf';

export function useReceiptUpload(householdId: string, isLeavePending: () => boolean) {
  const queryClient = useQueryClient();
  const getSessionSignal = useSessionSignal();
  const uploadKey = ['receiptUpload', householdId] as const;
  const activeUpload = useIsMutating({ mutationKey: uploadKey, exact: true }) > 0;
  const [file, setFile] = useState<File | null>(null);
  const [validatingPdf, setValidatingPdf] = useState(false);
  const [fileError, setFileError] = useState<string>();
  const selection = useRef<{ file: File; pdf: boolean } | null>(null);
  const validation = useRef<AbortController | null>(null);
  const [trackedUploads, setTrackedUploads] = useState<{ id: string; uploadedAt: string }[]>([]);
  const [preparing, setPreparing] = useState(false);
  const preparation = useRef<AbortController | null>(null);
  const submitting = useRef(false);

  useLayoutEffect(() => {
    const controller = new AbortController();
    preparation.current = controller;
    return () => {
      controller.abort();
      validation.current?.abort();
    };
  }, []);

  function ensureHouseholdAccess(id: string) {
    if (!queryClient.getQueryData(householdAccessKey(id))) {
      throw new Error('Du hast keinen Zugriff mehr auf diesen Haushalt.');
    }
  }

  const upload = useSessionMutation({
    mutationKey: uploadKey,
    retry: false,
    mutationFn: async ({
      householdId,
      file,
      pdf,
      preparationSignal
    }: {
      householdId: string;
      file: File;
      pdf: boolean;
      preparationSignal: AbortSignal;
    }) => {
      const signal = getSessionSignal();
      const prepared = pdf
        ? { file, contentType: ContentType.ApplicationPdf }
        : await prepareReceiptImage(file, preparationSignal);
      preparationSignal.throwIfAborted();
      ensureHouseholdAccess(householdId);
      setPreparing(false);

      // Sign the exact MIME type and size of the file sent to S3.
      const receiptUpload = await requestPrivateResource((options) =>
        createReceipt(
          {
            householdId,
            createReceiptRequest: {
              content_type: prepared.contentType,
              size_bytes: prepared.file.size
            }
          },
          options
        )
      );

      // Step 2: unauthenticated PUT — send raw bytes to S3 with all backend-supplied headers.
      preparationSignal.throwIfAborted();
      signal.throwIfAborted();
      ensureHouseholdAccess(householdId);
      await uploadToS3(receiptUpload, prepared.file, signal);
      return {
        id: receiptUpload.receipt_id,
        completedAt: Date.now(),
        originalSize: file.size,
        uploadedSize: prepared.file.size
      };
    },
    onSettled: () => {
      submitting.current = false;
      setPreparing(false);
    },
    onError: (error) =>
      handleHouseholdAccessError(queryClient, householdId, error, getSessionSignal()),
    onSuccess: ({ id, completedAt }, { householdId }) => {
      selection.current = null;
      setFile(null);
      setTrackedUploads((current) => [
        ...current,
        { id, uploadedAt: new Date(completedAt).toISOString() }
      ]);
      void queryClient.invalidateQueries({ queryKey: ['receipts', householdId] });
    }
  });

  function isUploadPending() {
    return (
      submitting.current || queryClient.isMutating({ mutationKey: uploadKey, exact: true }) > 0
    );
  }

  function handleUpload() {
    const selected = selection.current;
    if (!selected || !preparation.current || isUploadPending() || isLeavePending()) return;

    const signal = getSessionSignal();
    if (signal.aborted || preparation.current.signal.aborted) return;
    submitting.current = true;
    setPreparing(!selected.pdf);
    upload.mutate({
      householdId,
      ...selected,
      preparationSignal: AbortSignal.any([signal, preparation.current.signal])
    });
  }

  async function handleFileChange(next: File | null) {
    if (isUploadPending() || isLeavePending() || !preparation.current) return;
    validation.current?.abort();
    selection.current = null;
    upload.reset();
    setFile(null);
    setFileError(undefined);
    setValidatingPdf(false);
    if (!next) return;

    if (!isPdfCandidate(next)) {
      const result = validateReceiptImage(next);
      if ('error' in result) {
        setFileError(result.error);
        return;
      }
      selection.current = { file: next, pdf: false };
      setFile(next);
      return;
    }

    const controller = new AbortController();
    validation.current = controller;
    const signal = AbortSignal.any([
      controller.signal,
      getSessionSignal(),
      preparation.current.signal
    ]);
    setFile(next);
    setValidatingPdf(true);
    try {
      await validateReceiptPdf(next, signal);
      signal.throwIfAborted();
      ensureHouseholdAccess(householdId);
      selection.current = { file: next, pdf: true };
    } catch (error) {
      if (signal.aborted) return;
      setFileError(error instanceof Error ? error.message : 'Das PDF konnte nicht geprüft werden.');
    } finally {
      if (!signal.aborted) setValidatingPdf(false);
      if (validation.current === controller) validation.current = null;
    }
  }

  function abortPreparation() {
    preparation.current?.abort();
    validation.current?.abort();
  }

  return {
    file,
    fileError,
    validatingPdf,
    trackedUploads,
    preparing,
    upload,
    activeUpload,
    isUploadPending,
    abortPreparation,
    handleUpload,
    handleFileChange
  };
}
