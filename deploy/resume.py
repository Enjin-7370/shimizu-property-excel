"""Resume the existing Cloud Shell deployment with optional billing notifications."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

archive = Path.home() / 'Shimizu_Cloud_Deploy.pyz'
if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != '1b9e7cb0211f41062ceae4c5621989bbceb1c0a56207ca0381ef6318dada8f79':
    sys.exit('Expected the original Shimizu_Cloud_Deploy.pyz in the Cloud Shell home directory.')
patch = "--- service/deploy/budget_alert.py\n+++ service/deploy/budget_alert.py\n@@ -11 +11 @@\n- if account.status_code!=200:raise RuntimeError('請求アカウントの通貨を確認できません。')\n+ if account.status_code!=200:raise RuntimeError(f'請求先の通貨照会がHTTP {account.status_code}を返しました。')\n@@ -24 +24,9 @@\n- if result.status_code!=200:raise RuntimeError('基盤費用の予算通知を設定できません。サービス公開へ進んでいません。')\n+ if result.status_code!=200:raise RuntimeError('基盤費用の予算通知を設定できません。')\n+\n+\n+def try_configure(project, billing_name):\n+    try:\n+        configure(project, billing_name)\n+    except (RuntimeError, requests.RequestException, ValueError, subprocess.CalledProcessError) as exc:\n+        print('基盤費用の予算通知は未確認です。', str(exc), flush=True)\n+        print('利用額はCloud Billingで確認してください。AI共有台帳の初期化へ進みます。', flush=True)\n--- service/deploy/gcp_deploy.py\n+++ service/deploy/gcp_deploy.py\n@@ -26 +26 @@\n- run('services','enable','run.googleapis.com','cloudbuild.googleapis.com','artifactregistry.googleapis.com','firestore.googleapis.com','iap.googleapis.com','secretmanager.googleapis.com','billingbudgets.googleapis.com',*common)\n+ run('services','enable','run.googleapis.com','cloudbuild.googleapis.com','artifactregistry.googleapis.com','firestore.googleapis.com','iap.googleapis.com','secretmanager.googleapis.com',*common)\n@@ -43,3 +43,2 @@\n- run('services','enable','run.googleapis.com','cloudbuild.googleapis.com','artifactregistry.googleapis.com','firestore.googleapis.com','iap.googleapis.com','secretmanager.googleapis.com','billingbudgets.googleapis.com',*common)\n- from budget_alert import configure\n- configure(a.project,billing['billingAccountName'])\n+ from budget_alert import try_configure\n+ try_configure(a.project,billing['billingAccountName'])\n"
patch += "--- service/deploy/gcp_deploy.py\n+++ service/deploy/gcp_deploy.py\n@@ -10,4 +10,17 @@\n def run(*args,read=False):\n- p=subprocess.run(['gcloud',*args],check=True,text=True,stdout=subprocess.PIPE if read else None)\n- return p.stdout.strip() if read else None\n+ if 'add-iam-policy-binding' not in args:\n+  p=subprocess.run(['gcloud',*args],check=True,text=True,stdout=subprocess.PIPE if read else None)\n+  return p.stdout.strip() if read else None\n+ import random,time\n+ for attempt in range(6):\n+  p=subprocess.run(['gcloud',*args],text=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)\n+  if p.returncode==0:return\n+  sys.stderr.write(p.stderr)\n+  message=p.stderr.lower()\n+  conflict='concurrent policy changes' in message or ('etag' in message and 'did not match' in message)\n+  if not conflict or attempt==5:p.check_returncode()\n+  delay=2**attempt+random.random()\n+  print(f'IAMの同時更新。{delay:.1f}秒後に最新ポリシーから再試行します。',flush=True)\n+  time.sleep(delay)\n+\n \n"
with tempfile.TemporaryDirectory(prefix='shimizu-resume-') as tmp:
    with zipfile.ZipFile(archive) as app:
        app.extractall(tmp)
    subprocess.run(['patch', '--batch', '-p0'], cwd=tmp, input=patch, text=True, check=True)
    deploy = Path(tmp) / 'service' / 'deploy' / 'gcp_deploy.py'
    for options in ([], ['--enable-ai']):
        subprocess.run([sys.executable, str(deploy), '--project', 'enjin-bpr-tools', *options], check=True)
    url = subprocess.check_output(['gcloud','run','services','describe','shimizu-property','--project=enjin-bpr-tools','--region=asia-northeast1','--format=value(status.url)'],text=True)
    print('清水さん用URL', url.strip())

