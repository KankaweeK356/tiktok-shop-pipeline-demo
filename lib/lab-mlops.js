/** Read-only MLOps evidence for one target month (Feature Store + Training Runs + Drift), read from the lab object storage.
 *  Mounted through lab-forecast (`/api/lab-batch-result?fc=mlops`), so no new Vercel Function. It never writes, retrains or touches a sealed forecast. */
export const ML_PREFIX = "vercel-lab/ml";
export const KINDS = { OFFICIAL_LINKED: "official_linked", HISTORICAL_EVALUATION: "historical_evaluation", EXPERIMENT_ONLY: "experiment_only" };

async function defaultStorage() {
  const { S3Client, GetObjectCommand, ListObjectsV2Command } = await import("@aws-sdk/client-s3");
  const s3 = new S3Client({ region: process.env.CLASSROOM_STORAGE_REGION || "auto", endpoint: process.env.CLASSROOM_STORAGE_ENDPOINT, forcePathStyle: true,
    credentials: { accessKeyId: process.env.CLASSROOM_STORAGE_KEY_ID, secretAccessKey: process.env.CLASSROOM_STORAGE_SECRET } });
  const Bucket = process.env.CLASSROOM_STORAGE_BUCKET;
  return {
    async list(prefix) {
      const out = []; let token;
      do { const r = await s3.send(new ListObjectsV2Command({ Bucket, Prefix: prefix, ContinuationToken: token })); out.push(...(r.Contents || []).map(o => o.Key)); token = r.IsTruncated ? r.NextContinuationToken : undefined; } while (token);
      return out;
    },
    async getJson(key) {
      try { const r = await s3.send(new GetObjectCommand({ Bucket, Key: key })); return JSON.parse(Buffer.from(await r.Body.transformToByteArray()).toString("utf8")); }
      catch (e) { if (e?.$metadata?.httpStatusCode === 404 || e?.name === "NoSuchKey") return null; throw e; }
    },
  };
}

/** Newest run of a kind for a month, with every stored artifact summary the UI shows. */
async function latestRun(store, kind, month) {
  const keys = (await store.list(`${ML_PREFIX}/index/${kind}/${month}/`)).filter(k => k.endsWith(".json"));
  if (!keys.length) return { count: 0, latest: null };
  const index = (await Promise.all(keys.map(k => store.getJson(k)))).filter(Boolean).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  const head = index[0], base = head.run_path;
  const [run, report, drift, status, params, evaluation] = await Promise.all(["run", "report", "drift", "status", "params", "evaluation"].map(n => store.getJson(`${base}/${n}.json`)));
  if (!run) return { count: index.length, latest: null };
  const manifest = run.feature_set_path ? await store.getJson(`${run.feature_set_path}/manifest.json`) : null;
  const final = evaluation?.final_predictions || {};
  return { count: index.length, latest: { training_run_id: head.training_run_id, kind, created_at: run.created_at, code_ref: run.code_ref, run, report, drift, status, params,
      feature_set: manifest && { path: run.feature_set_path, feature_version: manifest.feature_version, rows: manifest.rows, labelled_rows: manifest.labelled_rows, inference_rows: manifest.inference_rows,
        origins: manifest.origins, months: manifest.months, source: manifest.source, point_in_time: manifest.point_in_time, input_sha256: manifest.input_sha256,
        files: ["features.parquet", "feature_definitions.json", "manifest.json"].map(f => `${run.feature_set_path}/${f}`) },
      artifacts: run.artifacts || {}, shop_predictions: Object.fromEntries(Object.entries(final).map(([k, v]) => [k, v.shop_prediction ?? null])) } };
}

export async function readMlops(month, deps = {}) {
  const store = deps.mlopsStorage || await defaultStorage();
  const out = { month, official_linked: null, historical_evaluation: null, experiment_only: null };
  for (const [kind, key] of Object.entries(KINDS)) out[key] = await latestRun(store, kind, month);
  return out;
}
