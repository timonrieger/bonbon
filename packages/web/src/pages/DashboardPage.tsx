import { useQuery } from '@tanstack/react-query';
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
import { getHousehold, type MonthlyReport, type SpendingTrend } from '@/api';

function toMonthValue(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

const sampleReportData: Record<'current' | 'previous', Omit<MonthlyReport, 'month'>> = {
  current: {
    total_rappen: 13150,
    receipt_count: 4,
    previous_month_total_rappen: 8900,
    by_category: [
      { category: 'Getränke', total_rappen: 2500 },
      { category: 'Obst und Gemüse', total_rappen: 5150 },
      { category: 'Milchprodukte', total_rappen: 4200 },
      { category: 'Backwaren', total_rappen: 1300 }
    ],
    by_store: [
      { store: 'Coop', total_rappen: 6550 },
      { store: 'Migros', total_rappen: 6600 }
    ]
  },
  previous: {
    total_rappen: 8900,
    receipt_count: 3,
    previous_month_total_rappen: 12000,
    by_category: [
      { category: 'Backwaren', total_rappen: 1900 },
      { category: 'Milchprodukte', total_rappen: 3000 },
      { category: 'Obst und Gemüse', total_rappen: 2600 },
      { category: 'Haushalt', total_rappen: 1400 }
    ],
    by_store: [
      { store: 'Aldi Suisse', total_rappen: 3800 },
      { store: 'Migros', total_rappen: 5100 }
    ]
  }
};

function createSampleMonthlyReport(month: string, currentMonth: string): MonthlyReport | null {
  const [year, monthNumber] = currentMonth.split('-').map(Number);
  const previousMonth = toMonthValue(new Date(year, monthNumber - 2, 1));
  const reportData =
    month === currentMonth
      ? sampleReportData.current
      : month === previousMonth
        ? sampleReportData.previous
        : null;

  return reportData ? { month, ...reportData } : null;
}

function createSampleTrend(): SpendingTrend {
  const amountsRappen = [
    18450,
    0,
    26780,
    sampleReportData.previous.previous_month_total_rappen,
    sampleReportData.previous.total_rappen,
    sampleReportData.current.total_rappen
  ];
  const now = new Date();

  return {
    months: amountsRappen.map((total_rappen, index) => {
      const month = new Date(
        now.getFullYear(),
        now.getMonth() - amountsRappen.length + 1 + index,
        1
      );
      return { month: toMonthValue(month), total_rappen };
    })
  };
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

export function DashboardPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  const sampleTrend = import.meta.env.DEV ? createSampleTrend() : null;
  const [selectedMonth, setSelectedMonth] = useState(() => {
    return toMonthValue(new Date());
  });
  const currentMonth = toMonthValue(new Date());
  const sampleMonthlyReport = import.meta.env.DEV
    ? createSampleMonthlyReport(selectedMonth, currentMonth)
    : null;
  const categoryData = sampleMonthlyReport
    ? [...sampleMonthlyReport.by_category].sort((a, b) => b.total_rappen - a.total_rappen)
    : [];
  const storeData = sampleMonthlyReport
    ? [...sampleMonthlyReport.by_store].sort((a, b) => b.total_rappen - a.total_rappen)
    : [];
  const [year, month] = selectedMonth.split('-').map(Number);
  const selectedMonthDate = new Date(year, month - 1, 1);
  const displayedMonth = new Intl.DateTimeFormat('de-CH', {
    month: 'long',
    year: 'numeric'
  }).format(selectedMonthDate);

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
            {sampleTrend ? (
              <>
                <p className="mt-1 text-sm text-gray-600">
                  {formatMonth(sampleTrend.months[0].month, 'long')} bis{' '}
                  {formatMonth(sampleTrend.months[sampleTrend.months.length - 1].month, 'long')}
                </p>
                <p className="mt-1 text-sm font-medium text-amber-700">Beispieldaten</p>
              </>
            ) : null}
          </div>
          {sampleTrend ? (
            <div role="img" aria-label="Säulendiagramm mit Ausgaben pro Monat in CHF">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={sampleTrend.months}
                  margin={{ top: 8, right: 8, bottom: 8, left: 8 }}
                >
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
          ) : (
            <p className="text-sm text-gray-600">Der Monatsverlauf ist noch nicht verfügbar.</p>
          )}
        </section>

        <section aria-labelledby="category-spending" className="rounded border border-gray-200 p-4">
          <h2 id="category-spending" className="font-semibold">
            Ausgaben nach Kategorie
          </h2>
          {sampleMonthlyReport ? (
            <>
              <p className="mt-1 text-sm font-medium text-amber-700">Beispieldaten</p>
              <div
                role="img"
                aria-label={`Beispielausgaben nach Kategorie für ${displayedMonth}, in CHF`}
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
            </>
          ) : import.meta.env.DEV ? (
            <p className="mt-2 text-sm text-gray-600">
              Für diesen Monat sind keine Beispieldaten hinterlegt.
            </p>
          ) : (
            <p className="mt-2 text-sm text-gray-600">
              Die Kategorieauswertung ist noch nicht verfügbar.
            </p>
          )}
        </section>

        <section aria-labelledby="store-spending" className="rounded border border-gray-200 p-4">
          <h2 id="store-spending" className="font-semibold">
            Ausgaben nach Supermarkt
          </h2>
          {sampleMonthlyReport ? (
            <>
              <p className="mt-1 text-sm font-medium text-amber-700">Beispieldaten</p>
              <div
                role="img"
                aria-label={`Beispielausgaben nach Supermarkt für ${displayedMonth}, in CHF`}
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
            </>
          ) : import.meta.env.DEV ? (
            <p className="mt-2 text-sm text-gray-600">
              Für diesen Monat sind keine Beispieldaten hinterlegt.
            </p>
          ) : (
            <p className="mt-2 text-sm text-gray-600">
              Die Supermarktauswertung ist noch nicht verfügbar.
            </p>
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
