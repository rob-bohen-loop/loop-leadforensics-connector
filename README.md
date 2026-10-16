# Loop Lead Forensics — direct chat connector

This is a remote MCP connector for asking questions about Lead Forensics in chat.
It contains six read-only tools. It does not use Pipedrive, create tasks, send
messages or run a morning schedule. Your Lead Forensics credentials stay on the
host; chat receives the requested visitor data.

**Status:** built and tested locally with simulated API responses. Not deployed
or connected to your Lead Forensics account yet. Real GitHub sign-in and live
Lead Forensics responses must be checked after deployment. Designed for remote
MCP clients supporting Streamable HTTP and OAuth, including Claude and eligible
ChatGPT custom-app/plugin configurations; your account must allow custom MCP.

## Start here: upload the connector

1. Unzip this package on your Mac.
2. Create a **new private GitHub repository** named `loop-leadforensics-connector`.
   Keep the earlier `loop-leadforensics-sync` repository separate; it contains a
   different project and is not needed for this connection.
3. Select **uploading an existing file** on the empty repository page. Upload the
   files INSIDE the unzipped folder, not the ZIP or the enclosing folder.
4. Commit the files. At the repository's top level you should see `server.py`,
   `leadforensics.py`, `requirements.txt`, `Dockerfile` and this README. The test
   and settings-generator files can also be uploaded; they contain no real secrets.

## Set up your sign-in

This connector uses GitHub OAuth and checks your numeric GitHub account ID on
every authenticated request. Only the configured account can read visitor data.
GitHub sign-in here does not request repository-write access.

1. Open https://api.github.com/users/rob-bohen-loop in your browser. Copy the
   numeric `id` field (not `node_id`). This will be `ALLOWED_GITHUB_USER_ID`.
   If you sign in with a different GitHub account, use its username in the URL.
2. Open https://github.com/settings/developers → **OAuth Apps** → **New OAuth App**.
3. Application name: `Loop Lead Forensics`.
4. Homepage URL: your new GitHub repository URL.
5. For now set the callback URL to `https://example.com/auth/callback`.
   This is a temporary placeholder: sign-in cannot work until you replace it
   with your real hosting URL in the deployment steps below.
6. Register the application. Copy its **Client ID**, then generate a **Client
   secret**. These become `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` on the host.
   They are separate from your Lead Forensics Client ID and key.

## Prepare two connector encryption secrets

On your Mac, open Terminal, type `cd ` (including the space), drag the unzipped
folder into Terminal and press Return. Then run:

```sh
python3 generate_settings.py
```

Keep the two generated values private. They are for Render's environment settings.
If your Mac has no Python 3, stop at this step and ask for help with secret
generation; do not substitute memorable passwords.

## Deploy on Render

1. Sign in at https://dashboard.render.com using GitHub.
2. Choose **New → Web Service**, connect the new private repository, and grant
   Render access to that repository.
3. Choose **Docker** as the runtime/language. The Dockerfile supplies the build
   and start commands. Leave the root directory blank.
4. A Free instance can be used for an initial trial. It sleeps when idle and
   loses local authentication state on restart, so expect cold starts and
   reconnects. For regular use choose an always-on service with a persistent
   disk; review the current price in Render before purchasing.
5. Add these environment variables privately BEFORE deploying:

| Variable | Value |
| --- | --- |
| `LF_API_KEY` | Lead Forensics Authorization Token |
| `LF_CLIENT_ID` | Lead Forensics Client ID |
| `GITHUB_CLIENT_ID` | The GitHub OAuth app's Client ID |
| `GITHUB_CLIENT_SECRET` | The GitHub OAuth app's generated secret |
| `ALLOWED_GITHUB_USER_ID` | Your numeric GitHub account ID |
| `JWT_SIGNING_KEY` | Output of the local settings generator |
| `STORAGE_ENCRYPTION_KEY` | Output of the local settings generator |

Render supplies `RENDER_EXTERNAL_URL` automatically; the connector uses it as its
public HTTPS origin. On another host, set `PUBLIC_BASE_URL` to its HTTPS origin,
such as `https://your-connector.example.com`, with no `/mcp` suffix.

6. Deploy the web service. Copy the actual assigned HTTPS URL from Render.
7. Return to your GitHub OAuth app settings. Replace the placeholder callback
   with the actual service URL plus `/auth/callback`, for example
   `https://YOUR-ACTUAL-SERVICE.onrender.com/auth/callback`. Save the change.
8. Open the service URL plus `/health`. It should return `{"status":"ok"}`.
   This proves that the service is running, **not** that Lead Forensics credentials
   or OAuth sign-in have passed a live test.

### Keeping sign-in across restarts

For regular use, attach a persistent disk to a single service instance and set
`AUTH_STORAGE_DIR` to a writable folder on that disk (for example
`/var/data/lf-oauth`). Ensure the container's `appuser` can write there. OAuth
records are encrypted using `STORAGE_ENCRYPTION_KEY`. Keep both encryption/signing
keys stable. Back up the disk and keys using your hosting provider's private
controls. Without persistent storage, recreating the connection may be necessary
after a restart. Do not scale this file-backed setup to multiple instances.

## Add it to chat

The **MCP server URL** is your actual service URL plus `/mcp`.

### Claude

Open the custom-connector controls under Connectors/Customize and add a custom
connector named `Loop Lead Forensics`. Paste the `/mcp` URL and use OAuth sign-in.
The server supports automatic client registration: do not paste your Lead
Forensics key or GitHub OAuth app secret into Claude's optional client fields.
Connect, then sign in to the GitHub account whose numeric ID you configured.
Workspace controls may require the owner to add the connector first.

### ChatGPT

Where your account exposes custom MCP apps/plugins, create a connection to the
same `/mcp` URL using OAuth and follow the sign-in flow. Menu labels and creation
permissions vary by account/workspace. If you cannot see a custom MCP creation
option, share a screenshot of the app/plugin settings without secrets so we can
confirm the route for your account. This package alone does not install a plugin
or add tools to an existing conversation.

After connecting, start a fresh chat and enable the connector if required.

## First live checks

Ask these in order:

1. “Use Lead Forensics to list the assigned users and find Rob Bohen's user ID.”
2. “Show visitors assigned to Rob Bohen from 2026-10-01 to 2026-10-16. Say if the
   result covers only one page.” (Change the dates as appropriate.)
3. “For one of those businesses, show its visit history and which pages it viewed.”

If the first call rejects credentials, check API enablement, `LF_API_KEY` and
`LF_CLIENT_ID` in Render. The documented headers are `Authorization-Token` and
`ClientID`. If data shapes differ from expectations, the tools return the original
JSON structure without guessing record names. Inspect that first successful
response before building any aggregation or ranking.

If authentication fails, check the exact callback URL and numeric GitHub ID,
then disconnect and recreate the chat connector. A successful GitHub login by
another account deliberately does not grant access to Lead Forensics.

## Tools and coverage

| Tool | Purpose |
| --- | --- |
| `list_assigned_users` | Discover names and their Lead Forensics IDs |
| `recent_visitors` | Account-wide visitors within a date range |
| `assigned_visitors` | Visitors assigned to one verified client user ID |
| `business_details` | Details for one business ID |
| `business_visits` | Visits for one business in a date range |
| `visit_pages` | Pages associated with one visit ID |

Each list request returns one page (25 records by default, maximum 100). The
assistant must request further pages before claiming complete results or totals.
There is no “most active” aggregate endpoint in this package. Default dates are
the last seven calendar days including today, calculated in Europe/London.
The API receives timestamps without a timezone offset; verify your Lead Forensics
account timezone before relying on exact day boundaries. Explicit date ranges
are inclusive and limited to 93 days per call.

## Validation and maintenance

Local tests use fake credentials and simulated upstream responses:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest -v test_connector
```

Eleven tests passed during preparation: six-tool MCP discovery and calls,
correct API parameters and pagination, date/ID validation, sanitised failures,
unauthenticated HTTP rejection and OAuth discovery, approved-account checks,
and blocking unauthorised tools before any Lead Forensics request.
The complete browser OAuth exchange, live API permissions/response schemas and
hosting lifecycle have not yet been tested with your accounts.

Use the included dependency versions for the initial deployment. Review and test
dependency security updates periodically. Keep real credentials out of repository
files, screenshots, chat and log statements. To revoke access, remove the chat
connector and revoke the GitHub OAuth app authorisation; rotate hosting secrets
if they have been exposed.

## Official references checked 16 October 2026

- Lead Forensics assigned-business parameters (uses `clientuserid`):
  https://leadforensics-api.readme.io/reference/getbusinessesbyassignedto
- Lead Forensics API reference: https://leadforensics-api.readme.io/
- FastMCP GitHub OAuth: https://gofastmcp.com/integrations/github
- OpenAI MCP authentication: https://developers.openai.com/plugins/build/auth
- Claude custom connectors:
  https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Render hosting limitations: https://render.com/docs/free
