import { HttpError } from '@oazapfts/runtime';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  type TooltipValueType,
  XAxis,
  YAxis
} from 'recharts';
import { getMonthlyReport, getSpendingTrend } from '@/api';
import { readHouseholdResource } from '@/features/households/householdAccess';
import { useHouseholdAccess } from '@/features/households/useHouseholdAccess';

function toMonthValue(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function formatMonth(month: string, style: 'short' | 'long' = 'short') {
  const [year, value] = month.split('-').map(Number);
  return new Intl.DateTimeFormat('de-CH', {
    month: style,
    year: style === 'long' ? 'numeric' : undefined
  }).format(new Date(year, value - 1, 1));
}

function formatRappenAsChf(value: TooltipValueType | undefined) {
  if (typeof value !== 'number' && typeof value !== 'string') return '';

  return new Intl.NumberFormat('de-CH', {
    style: 'currency',
    currency: 'CHF'
  }).format(Number(value) / 100);
}

function reportErrorMessage(error: Error) {
  return error instanceof HttpError && error.status === 501
    ? 'Diese Auswertung ist derzeit nicht verfügbar.'
    : error.message;
}

function shouldRetryReport(failureCount: number, error: Error) {
  return !(error instanceof HttpError && error.status === 501) && failureCount < 3;
}

export function DashboardPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  return <DashboardContent key={householdId} householdId={householdId} />;
}

function DashboardContent({ householdId }: { householdId: string }) {
  const queryClient = useQueryClient();
  const [selectedMonth, setSelectedMonth] = useState(() => {
    return toMonthValue(new Date());
  });
  const currentMonth = toMonthValue(new Date());
  const [year, month] = selectedMonth.split('-').map(Number);
  const selectedMonthDate = new Date(year, month - 1, 1);
  const displayedMonth = new Intl.DateTimeFormat('de-CH', {
    month: 'long',
    year: 'numeric'
  }).format(selectedMonthDate);

  const household = useHouseholdAccess(householdId);
  const accessVerified = household.isFetchedAfterMount && household.isSuccess && !!household.data;

  const monthlyReport = useQuery({
    queryKey: ['monthlyReport', householdId, selectedMonth],
    queryFn: ({ signal }) =>
      readHouseholdResource(
        queryClient,
        householdId,
        (options) => getMonthlyReport({ householdId, month: selectedMonth }, options),
        signal
      ),
    enabled: accessVerified,
    retry: shouldRetryReport
  });
  const spendingTrend = useQuery({
    queryKey: ['spendingTrend', householdId, 6],
    queryFn: ({ signal }) =>
      readHouseholdResource(
        queryClient,
        householdId,
        (options) => getSpendingTrend({ householdId, months: 6 }, options),
        signal
      ),
    enabled: accessVerified,
    retry: shouldRetryReport
  });
  const categoryData = [...(monthlyReport.data?.by_category ?? [])].sort(
    (a, b) => b.total_rappen - a.total_rappen
  );
  const storeData = [...(monthlyReport.data?.by_store ?? [])].sort(
    (a, b) => b.total_rappen - a.total_rappen
  );
  const trendMonths = spendingTrend.data?.months ?? [];

  function changeMonth(offset: number) {
    setSelectedMonth(toMonthValue(new Date(year, month - 1 + offset, 1)));
  }

  if (household.data === null) {
    return (
      <div className="text-red-600">
        <p role="alert">Dieser Haushalt ist nicht verfügbar.</p>
        <Link to="/" className="underline">
          Zu meinen Haushalten
        </Link>
      </div>
    );
  }
  if (!household.isFetchedAfterMount || household.isPending) return <p>Laden…</p>;
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
          Die Auswahl steuert Kategorie- und Supermarktansicht. Der Monatsverlauf zeigt unabhängig
          davon sechs Monate.
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
        <section
          aria-labelledby="monthly-spending"
          className="rounded border border-gray-200 p-4 md:col-span-2"
        >
          <div className="mb-4">
            <h2 id="monthly-spending" className="font-semibold">
              Ausgaben pro Monat
            </h2>
            {spendingTrend.isSuccess && trendMonths.length > 0 ? (
              <p className="mt-1 text-sm text-gray-600">
                {formatMonth(trendMonths[0].month, 'long')} bis{' '}
                {formatMonth(trendMonths[trendMonths.length - 1].month, 'long')}
              </p>
            ) : null}
          </div>
          {spendingTrend.isPending ? (
            <p className="text-sm text-gray-600">Monatsverlauf wird geladen…</p>
          ) : spendingTrend.isError ? (
            <p className="text-sm text-red-600">{reportErrorMessage(spendingTrend.error)}</p>
          ) : trendMonths.every(({ total_rappen }) => total_rappen === 0) ? (
            <p className="text-sm text-gray-600">
              Für diesen Zeitraum liegen keine Auswertungsdaten vor.
            </p>
          ) : (
            <div role="img" aria-label="Säulendiagramm mit Ausgaben pro Monat in CHF">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={trendMonths} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tickFormatter={(month: string) => formatMonth(month)} />
                  <YAxis tickFormatter={formatRappenAsChf} width={90} />
                  <Tooltip
                    labelFormatter={(month) => formatMonth(String(month), 'long')}
                    formatter={(value) => formatRappenAsChf(value)}
                  />
                  <Bar dataKey="total_rappen" fill="#2563eb" name="Ausgaben" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section aria-labelledby="category-spending" className="rounded border border-gray-200 p-4">
          <h2 id="category-spending" className="font-semibold">
            Ausgaben nach Kategorie
          </h2>
          {monthlyReport.isPending ? (
            <p className="mt-2 text-sm text-gray-600">Kategorieauswertung wird geladen…</p>
          ) : monthlyReport.isError ? (
            <p className="mt-2 text-sm text-red-600">{reportErrorMessage(monthlyReport.error)}</p>
          ) : categoryData.length === 0 ? (
            <p className="mt-2 text-sm text-gray-600">
              Für {displayedMonth} liegen keine Auswertungsdaten vor.
            </p>
          ) : (
            <div
              role="img"
              aria-label={`Ausgaben nach Kategorie für ${displayedMonth}, in CHF`}
              className="mt-3"
            >
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={categoryData}
                  layout="vertical"
                  margin={{ top: 4, right: 12, bottom: 4, left: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" tickFormatter={formatRappenAsChf} />
                  <YAxis type="category" dataKey="category" width={112} />
                  <Tooltip formatter={(value) => formatRappenAsChf(value)} />
                  <Bar dataKey="total_rappen" fill="#16a34a" name="Ausgaben" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section aria-labelledby="store-spending" className="rounded border border-gray-200 p-4">
          <h2 id="store-spending" className="font-semibold">
            Ausgaben nach Supermarkt
          </h2>
          {monthlyReport.isPending ? (
            <p className="mt-2 text-sm text-gray-600">Supermarktauswertung wird geladen…</p>
          ) : monthlyReport.isError ? (
            <p className="mt-2 text-sm text-red-600">{reportErrorMessage(monthlyReport.error)}</p>
          ) : storeData.length === 0 ? (
            <p className="mt-2 text-sm text-gray-600">
              Für {displayedMonth} liegen keine Auswertungsdaten vor.
            </p>
          ) : (
            <div
              role="img"
              aria-label={`Ausgaben nach Supermarkt für ${displayedMonth}, in CHF`}
              className="mt-3"
            >
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={storeData}
                  layout="vertical"
                  margin={{ top: 4, right: 12, bottom: 4, left: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" tickFormatter={formatRappenAsChf} />
                  <YAxis type="category" dataKey="store" width={112} />
                  <Tooltip formatter={(value) => formatRappenAsChf(value)} />
                  <Bar dataKey="total_rappen" fill="#f97316" name="Ausgaben" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
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
