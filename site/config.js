// Local-dev defaults: the dev server supplies the manifest, and login is left
// unconfigured (login.html shows a disabled button).
// This file is committed with placeholders and stays that way.
// scripts/deploy_site.sh generates the deployed one from Terraform's outputs
// into build/ and uploads that -- your Cognito ids never land in the repo.
export const MANIFEST_URL = "./manifest.json";
export const API_BASE = "/api";
export const COGNITO_DOMAIN = "";     // e.g. https://your-albums.auth.ap-southeast-6.amazoncognito.com
export const COGNITO_CLIENT_ID = "";
export const REDIRECT_URI = "";       // e.g. https://albums.example.com/auth/callback
