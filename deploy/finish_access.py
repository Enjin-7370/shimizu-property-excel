"""Complete access setup for the already-deployed property service."""
import hashlib
import json
import subprocess
import time

PROJECT = "enjin-bpr-tools"
REGION = "asia-northeast1"
SERVICE = "shimizu-property"
SECRET = "shimizu-openai-api-key"
URL = "https://shimizu-property-554930818091.asia-northeast1.run.app"

def call(*args, retry=False):
    for delay in (2, 4, 8, 16, 32, 0):
        result = subprocess.run(["gcloud", *args, "--project", PROJECT, "--quiet"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        error = result.stderr.lower()
        if not retry or not delay or not any(token in error for token in ("service_disabled","has not been used","concurrent policy changes","etag")):
            raise SystemExit(result.stderr)
        time.sleep(delay)

def main():
    account = subprocess.check_output(["gcloud","config","get-value","account"],text=True).strip()
    if hashlib.sha256(account.encode()).hexdigest() != "195b34436e9b473a7d8bb373fc4e9cdb21c8802048ad73045e8d768344c954f5":
        raise SystemExit("Switch to the designated deployment account.")
    def describe():
        return json.loads(call("run","services","describe",SERVICE,"--region",REGION,"--format=json"))
    service = describe()
    spec = service["spec"]["template"]["spec"]
    sa = f"shimizu-runtime@{PROJECT}.iam.gserviceaccount.com"
    env = {v["name"]:v.get("value") for v in spec["containers"][0].get("env",[])}
    if (service["metadata"].get("labels",{}).get("app") != SERVICE or spec.get("serviceAccountName") != sa or
        env.get("AUTH_MODE") != "iap" or env.get("AI_POLICY_REF") != "shimizu-initial-3000jpy-v1"):
        raise SystemExit("Existing deployment does not match the approved configuration.")
    call("services","enable","cloudresourcemanager.googleapis.com")
    emails = sorted(env.get("ALLOWED_EMAILS","").split(","))
    if hashlib.sha256(",".join(emails).encode()).hexdigest() != "81119514c6cc8963be24beccbf2de5cfea53511557726b05f632d221165f8693":
        raise SystemExit("Unexpected access list.")
    for email in emails:
        call("iap","web","add-iam-policy-binding","--member=user:"+email,"--role=roles/iap.httpsResourceAccessor","--region",REGION,"--resource-type=cloud-run","--service",SERVICE,retry=True)
    call("secrets","add-iam-policy-binding",SECRET,"--member=serviceAccount:"+sa,"--role=roles/secretmanager.secretAccessor",retry=True)
    call("run","services","update",SERVICE,"--region",REGION,"--update-env-vars=PUBLIC_ORIGIN="+URL+",AI_ENABLED=1","--update-secrets=OPENAI_API_KEY="+SECRET+":latest")
    if not any(c.get("type")=="Ready" and c.get("status")=="True" for c in describe()["status"]["conditions"]):
        raise SystemExit("Revision readiness not confirmed.")
    print("清水さん用URL",URL)

if __name__=="__main__":
    main()
