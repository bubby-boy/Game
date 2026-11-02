# HTML Arcade (Flask + GitHub storage)

A Flask web app that lets you upload HTML projects and optional cover images, stores them in a GitHub repository through the GitHub Contents API, and runs them in a sandboxed iframe.

## 1. Create/configure a GitHub repository

1. Create a repository, for example `html-arcade-storage`.
2. In GitHub, create a **fine-grained personal access token**.
3. Give it access to only this repository and grant **Contents: Read and write**.
4. Copy the token once. Do not put it in source code or commit it.

The app creates this structure automatically:

```text
games/
  project-name-abc123/
    title.txt
    index.html
    cover.png
```

## 2. Environment variables

Set these in your hosting provider's environment/secrets settings:

- `GITHUB_TOKEN` — the fine-grained token.
- `GITHUB_REPO` — repository in `owner/repository` format.
- `GITHUB_BRANCH` — branch name, usually `main`.
- `UPLOAD_PASSWORD` — a private password required to upload.
- `FLASK_SECRET` — a long random secret.
- `PORT` — usually supplied automatically by the host.

Example (values are placeholders):

```text
GITHUB_TOKEN=github_pat_your_token_here
GITHUB_REPO=yourusername/html-arcade-storage
GITHUB_BRANCH=main
UPLOAD_PASSWORD=choose-a-long-private-password
FLASK_SECRET=replace-with-a-long-random-value
```

## 3. Run locally

```bash
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

## 4. Deploy

Push this project to your app repository and deploy it as a Python/Flask web service. Set the environment variables above in the host dashboard. The start command is:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

## Upload API

`POST /api/upload` accepts `multipart/form-data`:

- `html` — required `.html` or `.htm` file
- `image` — optional PNG/JPG/WEBP/GIF cover
- `title` — optional display title
- `password` — must match `UPLOAD_PASSWORD`

You can also send the password as `X-Upload-Password`.

Example:

```bash
curl -X POST https://YOUR-APP-DOMAIN/api/upload \
  -F "password=YOUR_UPLOAD_PASSWORD" \
  -F "title=My Project" \
  -F "html=@index.html" \
  -F "image=@cover.png"
```

`GET /api/games` returns the library as JSON.

## Security notes

- Never commit your GitHub token, upload password, or Flask secret.
- Anyone who knows the upload password can publish content to your storage repository.
- Uploaded HTML is user-provided executable content. The player embeds it in an iframe with a restrictive sandbox (scripts and forms are allowed, but same-origin access and top-level navigation are not).
- This is a personal-library design, not a multi-user account system.
