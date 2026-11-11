import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { getHousehold } from '@/api';

function toMonthValue(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

export function DashboardPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  const [selectedMonth, setSelectedMonth] = useState(() => {
    return toMonthValue(new Date());
  });
  const [year, month] = selectedMonth.split('-').map(Number);
  const selectedMonthDate = new Date(year, month - 1, 1);
  const displayedMonth = new Intl.DateTimeFormat('de-CH', {
    month: 'long',
    year: 'numeric'
  }).format(selectedMonthDate);
  const currentMonth = toMonthValue(new Date());

  function changeMonth(offset: number) {
    setSelectedMonth(toMonthValue(new Date(year, month - 1 + offset, 1)));
  }

  const household = useQuery({
    queryKey: ['household', householdId],
    queryFn: () => getHousehold({ householdId })
  });

  if (household.isPending) return <p>Laden…</p>;
  if (household.isError) return <p className="text-red-600">{household.error.message}</p>;
  return (
    <main>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-600">{household.data.name}</p>
      </header>

      <div className="mb-6">
        <h2 className="mb-1 text-sm font-medium">Monat auswählen</h2>
        <nav aria-label="Monatsauswahl" className="flex items-center gap-3">
          <button
            type="button"
            aria-label="Vorheriger Monat"
            onClick={() => changeMonth(-1)}
            className="rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-100"
          >
            ←
          </button>
          <p aria-live="polite" className="min-w-36 text-center font-medium">
            {displayedMonth}
          </p>
          <button
            type="button"
            aria-label="Nächster Monat"
            onClick={() => changeMonth(1)}
            disabled={selectedMonth >= currentMonth}
            className="rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            →
          </button>
        </nav>
        <p className="mt-2 text-sm text-gray-600">
          Die Auswahl wird vorerst nur lokal übernommen. Auswertungsdaten werden noch nicht geladen.
        </p>
      </div>

      <section aria-label="Kennzahlen" className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <article className="rounded border border-gray-200 p-4">
          <h2 className="font-semibold">Gesamtausgaben</h2>
          <p className="mt-2 text-sm text-gray-600">Auswertungen sind noch nicht verfügbar.</p>
        </article>
        <article className="rounded border border-gray-200 p-4">
          <h2 className="font-semibold">Kassenzettel</h2>
          <p className="mt-2 text-sm text-gray-600">Auswertungen sind noch nicht verfügbar.</p>
        </article>
      </section>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <section aria-labelledby="category-spending" className="rounded border border-gray-200 p-4">
          <h2 id="category-spending" className="font-semibold">
            Ausgaben nach Kategorie
          </h2>
          <p className="mt-2 text-sm text-gray-600">Auswertungen sind noch nicht verfügbar.</p>
        </section>

        <section aria-labelledby="store-spending" className="rounded border border-gray-200 p-4">
          <h2 id="store-spending" className="font-semibold">
            Ausgaben nach Supermarkt
          </h2>
          <p className="mt-2 text-sm text-gray-600">Auswertungen sind noch nicht verfügbar.</p>
        </section>

        <section
          aria-labelledby="receipt-list"
          className="rounded border border-gray-200 p-4 md:col-span-2"
        >
          <h2 id="receipt-list" className="font-semibold">
            Kassenzettel
          </h2>
          <p className="mt-2 text-sm text-gray-600">
            Die Kassenzettelliste ist noch nicht verfügbar.
          </p>
        </section>
      </div>

      <Link to={`/households/${householdId}`} className="mt-6 inline-block text-sm underline">
        Zur Haushaltsseite
      </Link>
    </main>
  );
}
