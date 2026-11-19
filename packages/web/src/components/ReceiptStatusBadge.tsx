import { Status } from '@/api';

const statuses: Record<Status, { label: string; className: string }> = {
  [Status.Uploaded]: { label: 'In Bearbeitung', className: 'text-yellow-700 bg-yellow-50' },
  [Status.Done]: { label: 'Verarbeitet', className: 'text-green-700 bg-green-50' },
  [Status.Failed]: { label: 'Fehlgeschlagen', className: 'text-red-700 bg-red-50' },
  [Status.Duplicate]: { label: 'Duplikat', className: 'text-gray-600 bg-gray-100' }
};

export function ReceiptStatusBadge({ status }: { status: Status }) {
  const { label, className } = Object.hasOwn(statuses, status)
    ? statuses[status]
    : { label: 'Unbekannter Status', className: 'text-gray-600 bg-gray-100' };

  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}
