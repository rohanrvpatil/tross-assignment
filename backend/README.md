# LinkedIn Profile API

FastAPI service that reverse-engineers LinkedIn's internal APIs to return structured
profile data from a public profile URL. The service uses your logged-in LinkedIn session
(cookies in `.env`) and calls LinkedIn endpoints directly, with no browser automation.

## Setup

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (recommended) or Docker
- A logged-in LinkedIn account in Chrome

### 1. Configure credentials

From the `backend/` directory, copy the example env file:

```bash
cp .env.example .env
```

Log in to LinkedIn in Chrome, open DevTools → Application → Cookies →
`https://www.linkedin.com`, and copy these values into `backend/.env`:

| Variable              | Description                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------- |
| `LINKEDIN_LI_AT`      | Value of the `li_at` cookie                                                               |
| `LINKEDIN_JSESSIONID` | Value of the `JSESSIONID` cookie (quotes optional; `ajax:` prefix is added automatically) |

**Never commit** `.env` **or real cookie values to git.**

### 2. Install dependencies

```bash
uv sync
```

## Run locally

From `backend/`:

```bash
uv run backend
```

The API listens on `http://127.0.0.1:8500`.

Interactive docs: `http://127.0.0.1:8500/docs`

### Docker

From the project root:

```bash
docker compose up --build
```

The container reads credentials from `backend/.env` and exposes port `8500`.

### Deployment

Pushes to `main` trigger a self-hosted GitHub Actions workflow that rebuilds and
restarts the Docker service (`docker compose up -d`).

## Approach

1. Logged in to dummy linkedin account and copied it's li_at, jsessionID, queryID from chrome devtools cookies section, added these 3 values to .env

2. In "Network" tab, searched for term "-chrome-extension://invalid/ graphql" to remove extension calls done by linkedin and show only graphql endpoints which actually fetch the data

3. I found below endpoint interesting as it had "Profile" word in it

GET /voyager/api/graphql?queryId=voyagerIdentityDashProfiles.<hash>&variables=...

I copied it's curl request and response from devtools and I was able to get main profile details like name, headline, about, profile image url etc from this endpoint

4. For other details like skills, certifications, test scores, languages: these details can be accessed when "Show all ... ->" button is clicked in the linkedin profile. So I observed which graphql endpoints are being called after clicking this button. I found below flagship endpoint as it had "profile.details.certifications"

https://www.linkedin.com/flagship-web/rsc-action/actions/pagination?sduiid=com.linkedin.sdui.pagers.profile.details.certifications

similarly did for

profile.details.languages
profile.details.testscores

I took there curl request by button "Copy curl request (cmd) and copied the response from "Preview" sub tab of "Network" tab and asked Cursor to implement the fetching of these specific profile details

## Known limitations

- **Manual session management**: Requires copying `li_at` and `JSESSIONID` from a
  browser session; cookies expire and must be refreshed periodically.
- **Viewer-dependent visibility**: Returned data reflects what LinkedIn exposes to
  the authenticated account (connection degree, privacy settings, and section
  visibility). Empty arrays or `null` do not necessarily mean the field is absent on
  LinkedIn; it may be privacy-gated for your session.
- **Contact info is often sparse**: Email, phone, and birthday are frequently hidden
  unless the profile owner shares them with your connection level.

## Challenges Faced

- 302 Found error on postman: while testing endpoints on postman, I was getting 302 Found with no response. On relogging into my linkedin profile and getting a fresh cookie + clearing stale cookies on postman, helped me resolve this 302 Found error and get a response.
