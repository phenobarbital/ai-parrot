// src/routes/auth/callback/[provider]/+page.server.ts

import type { PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';

export const load: PageServerLoad = async ({ params, url }) => {
  const { provider } = params;

  // Para SSO genérico, token viene en query params
  if (provider === 'sso') {
    const token = url.searchParams.get('token');
    const type = url.searchParams.get('type');

    if (token && type === 'bearer') {
      // Redirigir al cliente con token para que el store lo procese
      return { provider, token, success: true };
    }
  }

  // Google/Microsoft manejan su propio flow client-side
  return { provider, params: Object.fromEntries(url.searchParams) };
};
