/**
 * /demo redirect route.
 *
 * Sends anyone opening `/demo` to the public demo video:
 * https://youtu.be/pew44mcyDdc
 */

import { NextRequest, NextResponse } from 'next/server';

const DEMO_TARGET_URL = 'https://youtu.be/pew44mcyDdc';

export function GET(_request: NextRequest) {
  return NextResponse.redirect(DEMO_TARGET_URL, 307);
}

export function HEAD(request: NextRequest) {
  return GET(request);
}
