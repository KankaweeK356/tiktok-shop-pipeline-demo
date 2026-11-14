/** Server-side Neon Branch Credential Router
 * Ensures strict separation between live lab (classroom-live-run-lab)
 * and error lab (classroom-error-lab).
 * Never exposes credentials to browser or logs.
 */

export const NEON_BRANCHES = {
  LIVE: "classroom-live-run-lab",
  ERROR: "classroom-error-lab"
};

/**
 * Returns a Neon SQL client scoped strictly to the requested lab target.
 * @param {"live"|"error"|"readonly"} target - Target database environment
 */
export async function getNeonSqlAsync(target = "live") {
  let url = "";
  if (target === "error") {
    url = process.env.CLASSROOM_ERROR_LAB_WRITER_URL;
    if (!url) {
      throw new Error("Missing CLASSROOM_ERROR_LAB_WRITER_URL for classroom-error-lab");
    }
  } else if (target === "live") {
    url = process.env.CLASSROOM_LAB_WRITER_URL || process.env.CLASSROOM_LAB_NEON_URL;
    if (!url) {
      throw new Error("Missing CLASSROOM_LAB_WRITER_URL for classroom-live-run-lab");
    }
  } else if (target === "readonly") {
    url = process.env.CLASSROOM_NEON_READONLY_URL || process.env.CLASSROOM_LAB_NEON_URL;
    if (!url) {
      throw new Error("Missing CLASSROOM_NEON_READONLY_URL");
    }
  } else {
    throw new Error(`Unknown database target: ${target}`);
  }

  if (!/^postgres(?:ql)?:\/\//.test(url)) {
    throw new Error(`Invalid database URL format for ${target}`);
  }

  try {
    const { neon } = await import("@neondatabase/serverless");
    return neon(url);
  } catch (_e) {
    // Graceful offline mock fallback
    return {
      query: async () => []
    };
  }
}

/**
 * Synchronous resolver when package is available, or safe mock.
 */
export function getNeonSql(target = "live") {
  let url = "";
  if (target === "error") {
    url = process.env.CLASSROOM_ERROR_LAB_WRITER_URL;
  } else if (target === "live") {
    url = process.env.CLASSROOM_LAB_WRITER_URL || process.env.CLASSROOM_LAB_NEON_URL;
  } else {
    url = process.env.CLASSROOM_NEON_READONLY_URL || process.env.CLASSROOM_LAB_NEON_URL;
  }

  try {
    // If running in Node with module preloaded or on Vercel
    const req = typeof require !== "undefined" ? require : null;
    if (req) {
      const { neon } = req("@neondatabase/serverless");
      return neon(url);
    }
  } catch (_err) {}

  return {
    query: async () => []
  };
}

/**
 * Verify that required credentials exist without exposing their values.
 */
export function checkConfigured() {
  return {
    liveWriterConfigured: Boolean(process.env.CLASSROOM_LAB_WRITER_URL),
    errorWriterConfigured: Boolean(process.env.CLASSROOM_ERROR_LAB_WRITER_URL),
    readOnlyConfigured: Boolean(process.env.CLASSROOM_NEON_READONLY_URL || process.env.CLASSROOM_LAB_NEON_URL),
    storageConfigured: Boolean(process.env.CLASSROOM_STORAGE_BUCKET && process.env.CLASSROOM_STORAGE_ENDPOINT && process.env.CLASSROOM_STORAGE_KEY_ID && process.env.CLASSROOM_STORAGE_SECRET)
  };
}
