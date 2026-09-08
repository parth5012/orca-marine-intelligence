/**
 * Frontend Structured Logging Utility
 * Technical Blueprint: US-LOG-001 (Logging Infrastructure)
 * Lane: M-E (Frontend Chat & App Shell)
 *
 * Isomorphic structured logger supporting both browser and Node/Next.js server environments.
 * - Log levels: debug, info, warn, error
 * - Timestamp formatting: ISO 8601 UTC
 * - Respects LOG_LEVEL and NEXT_PUBLIC_LOG_LEVEL environment variables
 * - Development browser: visually formatted console output ([TIMESTAMP] [LEVEL] message {context})
 * - Production / server: JSON structured emission ({"timestamp": "...", "level": "...", "message": "...", ...context})
 * - Scoped logging: logger.child(context), withRequestId(requestId)
 * - Request helpers: getLoggingHeaders / injectRequestId, fetchWithLogging / fetchWithRequestId
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogContext {
  [key: string]: unknown;
}

export interface LogEntryError {
  name: string;
  message: string;
  stack?: string;
}

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  logger?: string;
  context?: LogContext;
  requestId?: string;
  error?: LogEntryError;
  [key: string]: unknown;
}

const LEVEL_SEVERITY: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

/**
 * Detects whether execution is within a browser client runtime.
 */
function isBrowserRuntime(): boolean {
  return typeof window !== 'undefined' && typeof window.document !== 'undefined';
}

/**
 * Detects whether the environment is development mode.
 */
function isDevEnvironment(): boolean {
  if (typeof process !== 'undefined' && process.env) {
    if (process.env.NODE_ENV) {
      return process.env.NODE_ENV !== 'production';
    }
  }
  return true;
}

/**
 * Resolves configured log level from LOG_LEVEL or NEXT_PUBLIC_LOG_LEVEL.
 * Falls back to 'debug' in development, 'info' in production.
 */
export function getResolvedLogLevel(): LogLevel {
  let envLevel: string | undefined;

  if (typeof process !== 'undefined' && process.env) {
    envLevel = process.env.LOG_LEVEL || process.env.NEXT_PUBLIC_LOG_LEVEL;
  }

  if (envLevel) {
    const normalized = envLevel.trim().toLowerCase() as LogLevel;
    if (normalized in LEVEL_SEVERITY) {
      return normalized;
    }
  }

  return isDevEnvironment() ? 'debug' : 'info';
}

/**
 * Generates an RFC4122 v4 UUID for distributed request tracing.
 */
export function generateRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Normalizes an unknown error into a structured object with name, message, stack.
 */
function normalizeError(err: unknown): LogEntryError | undefined {
  if (!err) return undefined;
  if (err instanceof Error) {
    return {
      name: err.name,
      message: err.message,
      stack: err.stack,
    };
  }
  return {
    name: 'Error',
    message: typeof err === 'object' ? JSON.stringify(err) : String(err),
  };
}

/**
 * Core Isomorphic Logger class.
 */
export class Logger {
  private namespace: string;
  private boundContext: LogContext;

  constructor(namespace: string = 'orca.frontend', initialContext: LogContext = {}) {
    this.namespace = namespace;
    this.boundContext = { ...initialContext };
  }

  /**
   * Sets or updates persistent context variables for this logger instance.
   */
  public setContext(context: LogContext): void {
    this.boundContext = { ...this.boundContext, ...context };
  }

  /**
   * Returns a new child logger instance inheriting this instance's namespace
   * and merging additional context properties.
   */
  public child(context: Record<string, unknown>): Logger {
    return new Logger(this.namespace, {
      ...this.boundContext,
      ...context,
    });
  }

  /**
   * Returns a new child logger scoped to a specific request ID.
   */
  public withRequestId(requestId: string): Logger {
    return this.child({ requestId });
  }

  /**
   * Logs a debug level message.
   */
  public debug(message: string, context?: Record<string, unknown>): void {
    this.emit('debug', message, undefined, context);
  }

  /**
   * Logs an info level message.
   */
  public info(message: string, context?: Record<string, unknown>): void {
    this.emit('info', message, undefined, context);
  }

  /**
   * Logs a warn level message.
   */
  public warn(message: string, context?: Record<string, unknown>): void {
    this.emit('warn', message, undefined, context);
  }

  /**
   * Logs an error level message with optional Error object or additional context.
   */
  public error(message: string, context?: Record<string, unknown>): void;
  public error(message: string, error?: Error | unknown, context?: Record<string, unknown>): void;
  public error(
    message: string,
    errorOrContext?: Error | unknown | Record<string, unknown>,
    maybeContext?: Record<string, unknown>
  ): void {
    let err: unknown;
    let ctx: Record<string, unknown> | undefined;

    if (errorOrContext instanceof Error) {
      err = errorOrContext;
      ctx = maybeContext;
    } else if (
      errorOrContext !== null &&
      typeof errorOrContext === 'object' &&
      maybeContext === undefined
    ) {
      ctx = errorOrContext as Record<string, unknown>;
      err = undefined;
    } else {
      err = errorOrContext;
      ctx = maybeContext;
    }

    this.emit('error', message, err, ctx);
  }

  /**
   * Central log emission pipeline.
   * Handles level gating, ISO 8601 UTC timestamp formatting,
   * environment-specific formatting (browser dev visual vs. server/prod JSON).
   */
  private emit(
    level: LogLevel,
    message: string,
    error?: unknown,
    context?: Record<string, unknown>
  ): void {
    const minLevel = getResolvedLogLevel();
    if (LEVEL_SEVERITY[level] < LEVEL_SEVERITY[minLevel]) {
      return;
    }

    const timestamp = new Date().toISOString();
    const mergedContext: LogContext = {
      ...this.boundContext,
      ...(context || {}),
    };

    const isBrowser = isBrowserRuntime();
    const isDev = isDevEnvironment();

    if (isBrowser && isDev) {
      // Development browser: visually formatted console output
      const prefix = `[${timestamp}] [${level.toUpperCase()}]`;
      const formattedMessage = this.namespace
        ? `${prefix} [${this.namespace}] ${message}`
        : `${prefix} ${message}`;

      const args: unknown[] = [formattedMessage];
      if (error) {
        args.push(error);
      }
      if (Object.keys(mergedContext).length > 0) {
        args.push(mergedContext);
      }

      switch (level) {
        case 'debug':
          console.debug(...args);
          break;
        case 'info':
          console.info(...args);
          break;
        case 'warn':
          console.warn(...args);
          break;
        case 'error':
          console.error(...args);
          break;
      }
    } else {
      // Production / server: JSON structured emission
      const entry: Record<string, unknown> = {
        timestamp,
        level,
        message,
        logger: this.namespace,
        ...mergedContext,
      };

      const normError = normalizeError(error);
      if (normError) {
        entry.error = normError;
      }

      let jsonString: string;
      try {
        jsonString = JSON.stringify(entry);
      } catch {
        const seen = new WeakSet();
        try {
          jsonString = JSON.stringify(entry, (_k, v) => {
            if (typeof v === 'object' && v !== null) {
              if (seen.has(v)) return '[Circular]';
              seen.add(v);
            }
            if (v instanceof Error) return String(v);
            if (typeof v === 'bigint') return String(v);
            if (typeof v === 'function') return '[Function]';
            return v;
          });
        } catch {
          jsonString = JSON.stringify({ timestamp, level, message, logger: this.namespace, error: 'unserializable-context' });
        }
      }
      switch (level) {
        case 'debug':
          console.debug(jsonString);
          break;
        case 'info':
          console.info(jsonString);
          break;
        case 'warn':
          console.warn(jsonString);
          break;
        case 'error':
          console.error(jsonString);
          break;
      }
    }
  }
}

/**
 * Shared singleton logger instance.
 */
export const logger = new Logger('orca.frontend');

/**
 * Propagates or generates the X-Request-ID header on HTTP headers.
 * Accepts standard Fetch HeadersInit types (Headers, Array, or Record).
 */
export function getLoggingHeaders(
  existingHeaders?: HeadersInit,
  requestId?: string
): Record<string, string> {
  const headers: Record<string, string> = {};

  if (existingHeaders) {
    if (typeof Headers !== 'undefined' && existingHeaders instanceof Headers) {
      existingHeaders.forEach((value, key) => {
        headers[key] = value;
      });
    } else if (Array.isArray(existingHeaders)) {
      for (const [key, value] of existingHeaders) {
        headers[key] = value;
      }
    } else if (typeof existingHeaders === 'object') {
      Object.assign(headers, existingHeaders);
    }
  }

  // Check for existing request ID regardless of casing
  const existingId =
    headers['X-Request-ID'] ||
    headers['x-request-id'] ||
    headers['X-Request-Id'];

  const finalId = requestId || existingId || generateRequestId();

  // Clean casing variations and set canonical header
  delete headers['x-request-id'];
  delete headers['X-Request-Id'];
  headers['X-Request-ID'] = finalId;

  return headers;
}

/**
 * Blueprint alias for getLoggingHeaders.
 */
export const injectRequestId = getLoggingHeaders;

/**
 * Wraps global fetch to automatically:
 * 1. Inject or propagate X-Request-ID
 * 2. Measure fetch duration (ms)
 * 3. Log fetch completion or failure with structured metadata
 */
export async function fetchWithLogging(
  input: RequestInfo | URL | string,
  options?: RequestInit
): Promise<Response> {
  const startTime =
    typeof performance !== 'undefined' && performance.now
      ? performance.now()
      : Date.now();

  let urlStr: string;
  if (typeof input === 'string') {
    urlStr = input;
  } else if (typeof URL !== 'undefined' && input instanceof URL) {
    urlStr = input.toString();
  } else if (typeof input === 'object' && 'url' in input) {
    urlStr = (input as Request).url;
  } else {
    urlStr = String(input);
  }

  const method =
    options?.method ||
    (typeof input === 'object' && 'method' in input
      ? (input as Request).method
      : 'GET');

  const headers = getLoggingHeaders(options?.headers);
  const requestId = headers['X-Request-ID'];

  const requestOptions: RequestInit = {
    ...options,
    headers,
  };

  try {
    const response = await fetch(input as RequestInfo | URL, requestOptions);
    const duration = Math.round(
      (typeof performance !== 'undefined' && performance.now
        ? performance.now()
        : Date.now()) - startTime
    );

    if (response.ok) {
      logger.info(`Fetch completed: ${method} ${urlStr}`, {
        requestId,
        status: response.status,
        duration_ms: duration,
        url: urlStr,
        method,
      });
    } else {
      logger.warn(`Fetch HTTP error: ${method} ${urlStr}`, {
        requestId,
        status: response.status,
        statusText: response.statusText,
        duration_ms: duration,
        url: urlStr,
        method,
      });
    }

    return response;
  } catch (error) {
    const duration = Math.round(
      (typeof performance !== 'undefined' && performance.now
        ? performance.now()
        : Date.now()) - startTime
    );

    logger.error(`Fetch failed: ${method} ${urlStr}`, error, {
      requestId,
      duration_ms: duration,
      url: urlStr,
      method,
    });

    throw error;
  }
}

/**
 * Blueprint alias for fetchWithLogging.
 */
export const fetchWithRequestId = fetchWithLogging;

export default logger;
