import { NextRequest, NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_AGENTOPS_LOCAL_MODE !== 'true') return NextResponse.next();
  const pathname = request.nextUrl.pathname;
  const disabled = [
    '/ingest',
    '/monitoring-tunnel',
    '/functions',
    '/api/survey-submission',
    '/api/image-proxy',
    '/deploy',
    '/mcp',
    '/timetravel',
    '/signup',
    '/simple-login',
    '/welcome',
    '/logs',
    '/settings/organization',
  ];
  if (disabled.some((prefix) => pathname === prefix || pathname.startsWith(prefix + '/'))) {
    return new NextResponse('This cloud feature is unavailable in local mode.', { status: 404 });
  }
  return NextResponse.next();
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
