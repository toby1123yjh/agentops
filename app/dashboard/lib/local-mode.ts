/** Build-time UI mode; backend authorization never depends on this flag. */
export const isLocalMode = process.env.NEXT_PUBLIC_AGENTOPS_LOCAL_MODE === 'true';
