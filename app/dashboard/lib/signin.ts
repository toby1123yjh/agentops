const defaultMethods = 'email,magic,google,github';
export const signInMethods =
  process.env.NEXT_PUBLIC_AGENTOPS_LOCAL_MODE === 'true'
    ? ['email']
    : (process.env.NEXT_PUBLIC_SIGNIN_METHODS || defaultMethods).split(',');
