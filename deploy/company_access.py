"""Complete access setup for the already-deployed property service."""
import hashlib
import tempfile
import zipfile
from pathlib import Path
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
    archive = Path.home() / "Shimizu_Cloud_Deploy.pyz"
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != "1b9e7cb0211f41062ceae4c5621989bbceb1c0a56207ca0381ef6318dada8f79":
        raise SystemExit("Expected the original deployment archive in Cloud Shell home.")
    with tempfile.TemporaryDirectory(prefix="shimizu-domain-") as tmp:
        with zipfile.ZipFile(archive) as package:
            package.extractall(tmp)
        root = Path(tmp) / "service"
        server = root / "server.py"
        old = "return claims['email'].lower() in os.environ['ALLOWED_EMAILS'].lower().split(',')"
        new = "return is_company_email(claims['email'])"
        source = server.read_text()
        if source.count(old) != 1:raise SystemExit("Unexpected authentication code.")
        predicate = """def is_company_email(email):
    if not isinstance(email, str) or email.count('@') != 1:
        return False
    local, domain = email.rsplit('@', 1)
    return bool(local) and domain.lower() == 'enjin-group.com'

"""
        source=source.replace("class Handler(",predicate+"class Handler(").replace(old,new)
        compile(source,str(server),"exec")
        server.write_text(source)
        call("iap","web","add-iam-policy-binding","--member=domain:enjin-group.com","--role=roles/iap.httpsResourceAccessor","--region",REGION,"--resource-type=cloud-run","--service",SERVICE,retry=True)
        call("secrets","add-iam-policy-binding",SECRET,"--member=serviceAccount:"+sa,"--role=roles/secretmanager.secretAccessor",retry=True)
        builder=f"projects/{PROJECT}/serviceAccounts/shimizu-build@{PROJECT}.iam.gserviceaccount.com"
        call("run","deploy",SERVICE,"--source",str(root),"--region",REGION,"--build-service-account="+builder,"--service-account="+sa,"--iap","--no-allow-unauthenticated","--min=0","--max=1","--concurrency=1","--update-env-vars=PUBLIC_ORIGIN="+URL+",AI_ENABLED=1","--update-secrets=OPENAI_API_KEY="+SECRET+":latest")
    if not any(c.get("type")=="Ready" and c.get("status")=="True" for c in describe()["status"]["conditions"]):
        raise SystemExit("Revision readiness not confirmed.")
    print("清水さん用URL",URL)

if __name__=="__main__":
    main()
