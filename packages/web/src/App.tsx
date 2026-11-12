import { useAuthenticator } from '@aws-amplify/ui-react';
import { fetchUserAttributes } from 'aws-amplify/auth';
import { useEffect, useRef, useState } from 'react';
import { Link, Route, Routes } from 'react-router';
import { DeleteAccountDialog } from '@/components/DeleteAccountDialog';
import { DashboardPage } from '@/pages/DashboardPage';
import { HomePage } from '@/pages/HomePage';
import { HouseholdPage } from '@/pages/HouseholdPage';

export function App() {
  const { signOut } = useAuthenticator();
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [userEmail, setUserEmail] = useState('');

  // Ref to the trigger button so focus returns there when the dialog closes.
  const deleteButtonRef = useRef<HTMLButtonElement>(null);

  // Fetch the email once so the deletion dialog can display it.
  // fetchUserAttributes() is cheap (cached by Amplify).
  useEffect(() => {
    fetchUserAttributes()
      .then((attrs) => setUserEmail(attrs.email ?? ''))
      .catch(() => {
        // Non-critical: if this fails the dialog still works, email will be empty.
      });
  }, []);

  return (
    <div className="mx-auto max-w-3xl p-4">
      <header className="mb-6 flex items-center justify-between">
        <Link to="/" className="text-xl font-semibold">
          Bonbon
        </Link>
        <div className="flex items-center gap-4">
          <button
            ref={deleteButtonRef}
            type="button"
            onClick={() => setShowDeleteDialog(true)}
            className="text-sm text-gray-400 underline hover:text-gray-700"
          >
            Konto löschen
          </button>
          <button type="button" onClick={signOut} className="text-sm underline">
            Abmelden
          </button>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/households/:householdId" element={<HouseholdPage />} />
        <Route path="/households/:householdId/dashboard" element={<DashboardPage />} />
      </Routes>

      {showDeleteDialog && (
        <DeleteAccountDialog
          userEmail={userEmail}
          triggerRef={deleteButtonRef}
          onClose={() => setShowDeleteDialog(false)}
        />
      )}
    </div>
  );
}
