# Content Automation

Generate a three-post LinkedIn campaign from one DEV.to article and place it
in Buffer as scheduled drafts.

The project is intentionally narrow:

- read article markdown with DEV.to-style front matter
- generate a launch post, follow-up post, and lesson post
- schedule them for the recommended Dublin windows
- create Buffer drafts only when explicitly requested

Buffer still requires manual approval before publication.

## Schedule

The default campaign cadence is:

| Post | Time |
| --- | --- |
| Launch | next Wednesday, 16:00 Europe/Dublin |
| Follow-up | following Friday, 15:30 Europe/Dublin |
| Lesson | following Tuesday, 11:30 Europe/Dublin |

This matches the recommendation derived from your Buffer history plus recent
LinkedIn timing benchmarks: Wednesday afternoon for the launch, Friday
afternoon for the native follow-up, Tuesday late morning for the reusable
lesson/checklist.

## Setup

Install dependencies:

```bash
uv sync
```

Export the Buffer access value and LinkedIn channel id in your shell or
secret manager. The variable names are defined in
`src/content_automation/config.py`.

List channels:

```bash
uv run content-automation buffer channels
```

## Build a Campaign Plan

This is the default, safe mode. It prints the three posts and schedule. It
does not call Buffer.

```bash
uv run content-automation campaign article \
  --file "/path/to/article.md" \
  --url "https://dev.to/andremmfaria/article-slug"
```

Machine-readable output:

```bash
uv run content-automation campaign article \
  --file "/path/to/article.md" \
  --url "https://dev.to/andremmfaria/article-slug" \
  --json-output
```

## Create Buffer Drafts

Creating drafts is an external action, so it is opt-in:

```bash
uv run content-automation campaign article \
  --file "/path/to/article.md" \
  --url "https://dev.to/andremmfaria/article-slug" \
  --create-drafts
```

The command creates three scheduled Buffer drafts:

1. Launch post: article summary and direct link.
2. Follow-up post: native LinkedIn explanation of the strongest idea.
3. Lesson post: reusable principle/checklist extracted from the article.

Approve, edit, or delete them in Buffer before they publish.

## Link Placement

By default, the article URL is included in the post body. That is deliberate:
for article promotion, a visible link is better than a hidden first-comment
link.

If your Buffer plan supports LinkedIn first comments, pass:

```bash
--first-comment
```

## Notes

- Hashtags are capped at four.
- Generated posts are capped at 1300 characters.
- The command uses Buffer's current GraphQL API through the local Python client
  module. Buffer's current public docs include Python `requests` examples, but
  no maintained official Python SDK was found. The old `bufferapp/buffer-python`
  client targets the deprecated v1 REST API and Python 2-era dependencies.
- No LinkedIn browser automation is used.
- DEV.to publishing is intentionally out of scope. Keep that in the articles
  repo; this tool starts from a published article URL and builds the LinkedIn
  Buffer campaign around it.
