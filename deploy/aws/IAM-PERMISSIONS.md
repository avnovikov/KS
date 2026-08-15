# IAM permissions required for AWS CLI user `aaaa137`

The access keys work (`sts get-caller-identity` succeeds), but the user currently has **no Lightsail/EC2 policies**, so provisioning fails with `AccessDenied`.

## Fix (use root or an admin IAM user in the AWS Console)

1. Sign in to AWS Console as **root** (or an admin).
2. Open **IAM → Users → `aaaa137`**.
3. Tab **Permissions** → **Add permissions** → **Attach policies directly**.
4. Attach at least:
   - **`AmazonLightsailFullAccess`** (enough for this deploy)
5. Optional (broader, personal account OK):
   - **`AdministratorAccess`**
6. **Next → Add permissions**.

## Verify from this Mac

```bash
export PATH="/opt/homebrew/bin:$PATH"
aws sts get-caller-identity
aws lightsail get-bundles --region eu-west-1 --query 'bundles[0].bundleId' --output text
```

If the second command prints a bundle id (e.g. `nano_3_0`), permissions are good — say **retry Lightsail**.
