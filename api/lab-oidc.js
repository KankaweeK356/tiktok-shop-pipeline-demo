/** Exchange verified, short-lived GitHub Actions OIDC identity for a LAB-ONLY
 * Neon connection. Never returns credentials to a user/browser or an unverified
 * GitHub workflow. This removes NEON_LAB_DATABASE_URL GitHub secret dependency.
 */
import { createRemoteJWKSet, jwtVerify } from "jose";

const ISSUER = "https://token.actions.githubusercontent.com";
const AUDIENCE = "classroom-neon-lab-v1";
const REPOSITORY = "KankaweeK356/tiktok-shop-pipeline-demo";
const REPOSITORY_ID = "1449281299";
const REF = "refs/heads/feature/classroom-demo-evidence-foundation";
const WORKFLOW_PATH = REPOSITORY + "/.github/workflows/classroom-real-step.yml@" + REF;
const SMOKE_PATH = REPOSITORY + "/.github/workflows/classroom-oidc-smoke.yml@" + REF;
const PUSH_PATH = REPOSITORY + "/.github/workflows/classroom-push-step.yml@" + REF;
const RESET_PATH = REPOSITORY + "/.github/workflows/classroom-live-reset.yml@" + REF;
const BATCH_PATH = REPOSITORY + "/.github/workflows/classroom-live-batch.yml@" + REF;
const ERROR_PATH = REPOSITORY + "/.github/workflows/classroom-live-error.yml@" + REF;
const JWKS = createRemoteJWKSet(new URL(ISSUER + "/.well-known/jwks"));

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "POST only" });
  }
  const authorization = req.headers.authorization;
  const token = typeof authorization === "string" &&
    /^Bearer [A-Za-z0-9_.-]+$/.test(authorization) ?
    authorization.substring(7) : "";
  if (!token || token.length > 8000)
    return res.status(401).json({ error: "Missing GitHub OIDC identity" });
  try {
    const { payload } = await jwtVerify(token, JWKS, {
      issuer: ISSUER, audience: AUDIENCE,
      algorithms: ["RS256"], clockTolerance: 10,
      maxTokenAge: "5m"
    });
    const allow = payload.repository === REPOSITORY &&
      String(payload.repository_id) === REPOSITORY_ID &&
      payload.ref === REF &&
      payload.ref_type === "branch" &&
      [WORKFLOW_PATH, SMOKE_PATH, PUSH_PATH, RESET_PATH, BATCH_PATH, ERROR_PATH].includes(payload.workflow_ref) &&
      (payload.workflow_ref === SMOKE_PATH || payload.workflow_ref === PUSH_PATH ?
        payload.event_name === "push" : payload.event_name === "workflow_dispatch") &&
      payload.runner_environment === "github-hosted" &&
      /^[1-9][0-9]{3,19}$/.test(String(payload.run_id || ""));
    if (!allow)
      return res.status(403).json({ error: "GitHub OIDC policy rejected this workflow" });
    const connection = payload.workflow_ref === ERROR_PATH ?
      process.env.CLASSROOM_ERROR_LAB_WRITER_URL :
      process.env.CLASSROOM_LAB_WRITER_URL;
    if (!connection || !/^postgres(?:ql)?:\/\//.test(connection))
      return res.status(503).json({ error: "Isolated Neon lab credential not configured" });
    return res.status(200).json({
      database_url: connection,
      scope: "NEON_CLASSROOM_STEP_LAB_ONLY",
      expires_note: "GitHub OIDC identity accepted; do not log or persist connection"
    });
  } catch (error) {
    console.error("OIDC exchange refused", error?.code || error?.name || "UNKNOWN");
    return res.status(403).json({ error: "Unverified GitHub identity" });
  }
}
