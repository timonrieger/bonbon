import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { getReceipt, Status } from '@/api';
import { readPrivateResource } from '@/api/privateQuery';
import {
  isReceiptProcessing,
  RECEIPT_POLL_ERROR_INTERVAL,
  RECEIPT_POLL_INTERVAL
} from '@/api/receipts';
import { householdAccessKey } from '@/features/households/householdAccess';

export function ReceiptProcessingNotice({
  householdId,
  receiptId,
  uploadedAt
}: {
  householdId: string;
  receiptId: string;
  uploadedAt: string;
}) {
  const queryClient = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ['receipt', householdId, receiptId, 'processingStatus'],
    queryFn: async ({ signal }) => {
      const receipt = await readPrivateResource(
        (options) => getReceipt({ householdId, receiptId }, options),
        signal
      );
      signal.throwIfAborted();
      if (!receipt) {
        // A missing receipt and lost household access can both return 404.
        void queryClient.invalidateQueries({ queryKey: householdAccessKey(householdId) });
      } else if (receipt.status !== Status.Uploaded) {
        // Extraction can move the receipt to a different month.
        void queryClient.invalidateQueries({ queryKey: ['receipts', householdId] });
      }
      return receipt?.status ?? null;
    },
    enabled: ({ state }) =>
      (state.data === undefined || state.data === Status.Uploaded) &&
      isReceiptProcessing({ status: Status.Uploaded, created_at: uploadedAt }),
    retry: false,
    refetchIntervalInBackground: false,
    refetchInterval: ({ state }) =>
      state.status === 'error' ? RECEIPT_POLL_ERROR_INTERVAL : RECEIPT_POLL_INTERVAL
  });

  const receiptUrl = `/households/${householdId}/receipts/${receiptId}`;
  return (
    <div>
      <div role="status">
        {status === Status.Done && (
          <p className="mt-2 rounded bg-green-50 p-3 text-sm text-green-800">
            Der Kassenzettel wurde erfolgreich verarbeitet.{' '}
            <Link to={receiptUrl} className="underline">
              Kassenzettel ansehen
            </Link>
          </p>
        )}
        {status === Status.Duplicate && (
          <p className="mt-2 rounded bg-gray-100 p-3 text-sm text-gray-700">
            Der Kassenzettel wurde bereits hochgeladen und als Duplikat erkannt.{' '}
            <Link to={receiptUrl} className="underline">
              Kassenzettel ansehen
            </Link>
          </p>
        )}
      </div>
      <div role="alert">
        {status === Status.Failed && (
          <p className="mt-2 rounded bg-red-50 p-3 text-sm text-red-800">
            Der Kassenzettel konnte nicht verarbeitet werden.{' '}
            <Link to={receiptUrl} className="underline">
              Kassenzettel ansehen
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}
