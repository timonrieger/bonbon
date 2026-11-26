const interactionStyles =
  'rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50';

const standardStyles = `${interactionStyles} border px-4 py-2 text-sm font-medium`;

const textStyles = `${interactionStyles} text-sm underline`;

export const buttonStyles = {
  primary: `${standardStyles} border-transparent bg-black text-white enabled:hover:bg-gray-800`,

  secondary: `${standardStyles} border-gray-300 bg-white text-gray-700 enabled:hover:bg-gray-100`,

  danger: `${standardStyles} border-transparent bg-red-600 text-white enabled:hover:bg-red-700`,

  dangerOutline: `${standardStyles} border-red-300 bg-white text-red-700 enabled:hover:bg-red-50`,

  text: `${textStyles} text-gray-700 enabled:hover:text-black`,

  dangerText: `${textStyles} text-red-700 enabled:hover:text-red-900`,

  icon: `${interactionStyles} inline-flex size-9 items-center justify-center border border-gray-300 bg-white text-sm text-gray-700 enabled:hover:bg-gray-100`
} as const;
