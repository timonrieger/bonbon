import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { createHousehold } from '@/api';

export function HomePage() {
  const [name, setName] = useState('');
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () => createHousehold({ createHouseholdRequest: { name } }),
    onSuccess: (household) => navigate(`/households/${household.id}`)
  });

  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name des Haushalts"
        className="flex-1 rounded border px-3 py-2"
      />
      <button
        type="submit"
        disabled={create.isPending}
        className="rounded bg-black px-4 py-2 text-white"
      >
        Haushalt erstellen
      </button>
      {create.isError && <p className="text-red-600">{create.error.message}</p>}
    </form>
  );
}
