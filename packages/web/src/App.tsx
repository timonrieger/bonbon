import { useAuthenticator } from '@aws-amplify/ui-react';
import { Link, Route, Routes } from 'react-router';
import { HomePage } from '@/pages/HomePage';
import { HouseholdPage } from '@/pages/HouseholdPage';

export function App() {
  const { signOut } = useAuthenticator();
  return (
    <div className="mx-auto max-w-3xl p-4">
      <header className="mb-6 flex items-center justify-between">
        <Link to="/" className="text-xl font-semibold">
          Bonbon
        </Link>
        <button type="button" onClick={signOut} className="text-sm underline">
          Abmelden
        </button>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/households/:householdId" element={<HouseholdPage />} />
      </Routes>
    </div>
  );
}
