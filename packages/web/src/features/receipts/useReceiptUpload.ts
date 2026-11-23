import { useIsMutating, useQueryClient } from '@tanstack/react-query';
import { useLayoutEffect, useRef, useState } from 'react';
import { createReceipt } from '@/api';
import { requestPrivateResource } from '@/api/privateQuery';
import { uploadToS3 } from '@/api/receipts';
import { useSessionMutation, useSessionSignal } from '@/components/AuthenticatedSession';
import {
  handleHouseholdAccessError,
  householdAccessKey
} from '@/features/households/householdAccess';
import { prepareReceiptImage } from './receiptImage';

export function useReceiptUpload(householdId: string, isLeavePending: () => boolean) {
  const queryClient = useQueryClient();
  const getSessionSignal = useSessionSignal();
  const uploadKey = ['receiptUpload', householdId] as const;
  const activeUpload = useIsMutating({ mutationKey: uploadKey, exact: true }) > 0;
  const [file, setFile] = useState<File | null>(null);
  const [trackedUploads, setTrackedUploads] = useState<{ id: string; uploadedAt: string }[]>([]);
  const [preparing, setPreparing] = useState(false);
  const preparation = useRef<AbortController | null>(null);
  const submitting = useRef(false);

  useLayoutEffect(() => {
    const controller = new AbortController();
    preparation.current = controller;
    return () => controller.abort();
  }, []);

  function ensureHouseholdAccess(id: string) {
    if (!queryClient.getQueryData(householdAccessKey(id))) {
      throw new Error('Du hast keinen Zugriff mehr auf diesen Haushalt.');
    }
  }

  const upload = useSessionMutation({
    mutationKey: uploadKey,
    mutationFn: async ({
      householdId,
      file,
      preparationSignal
    }: {
      householdId: string;
      file: File;
      preparationSignal: AbortSignal;
    }) => {
      const signal = getSessionSignal();
      const prepared = await prepareReceiptImage(file, preparationSignal);
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
    if (!file || !preparation.current || isUploadPending() || isLeavePending()) return;

    const signal = getSessionSignal();
    submitting.current = true;
    setPreparing(true);
    upload.mutate({
      householdId,
      file,
      preparationSignal: AbortSignal.any([signal, preparation.current.signal])
    });
  }

  function handleFileChange(next: File | null) {
    upload.reset();
    setFile(next);
  }

  function abortPreparation() {
    preparation.current?.abort();
  }

  return {
    file,
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
