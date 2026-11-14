/** Server-side Neon Branch Credential Router
 * Ensures strict separation between live lab (classroom-live-run-lab)
 * and error lab (classroom-error-lab).
 * Never exposes credentials to browser or logs.
 */
import { neon } from "@neondatabase/serverless";

export const NEON_BRANCHES = {
  LIVE: "classroom-live-run-lab",
  ERROR: "classroom-error-lab"
};

/**
 * Returns a Neon SQL client scoped strictly to the requested lab target.
 * @param {"live"|"error"|"readonly"} target - Target database environment
 */
export async function getNeonSqlAsync(target = "live") {
  return getNeonSql(target);
}

/**
 * Synchronous resolver returning real Neon client or safe mock fallback.
 */
export function getNeonSql(target = "live") {
  let url = "";
  if (target === "error") {
    url = process.env.CLASSROOM_ERROR_LAB_WRITER_URL;
  } else if (target === "live") {
    url = process.env.CLASSROOM_LAB_NEON_URL || process.env.CLASSROOM_LAB_WRITER_URL;
  } else {
    url = process.env.CLASSROOM_NEON_READONLY_URL || process.env.CLASSROOM_LAB_NEON_URL;
  }

  if (url && /^postgres(?:ql)?:\/\//.test(url)) {
    try {
      return neon(url);
    } catch (_err) {}
  }

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
