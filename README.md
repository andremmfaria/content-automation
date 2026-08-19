# Content Automation

Generate a three-post LinkedIn campaign from one published DEV.to article and place it in Buffer as scheduled drafts.

The project is intentionally narrow:

- read article markdown with DEV.to-style front matter
- generate a launch post, follow-up post, and lesson post
- schedule the posts for the recommended Dublin windows
- create Buffer drafts only when explicitly requested

Buffer still requires manual approval before publication.

## LinkedIn Guidance

The launch post should be a native LinkedIn post first and an article promo second. Do not open with "new article dropped" or "I published a new article". Start with the real problem, failure, constraint, or surprising lesson from the article.

Do not flatten the article into a generic technology summary. Preserve the human reason the project exists. For example, if an article is mainly about a screenless way for a child to message mom or dad, lead with communication and independence. Home Assistant actions, hardware, MQTT, and automation details are supporting material unless the article makes them the main point.

Use this shape:

1. Start with the human problem or technical failure.
2. Explain the core lesson in 4-6 short paragraphs.
3. Keep the post useful without requiring the click.
4. Put one clear DEV.to link near the end.
5. Use 3-5 specific hashtags, not a broad hashtag pile.

For article promotion, keep the link in the post body. No-link native posts can perform better for reach, but hiding the article URL in the first comment is too easy to miss.

When possible, add a native asset. The strongest version is usually a 5-8 slide PDF/carousel or multi-image post:

- slide 1: the uncomfortable claim
- slides 2-6: the key lessons
- final slide: "Full write-up on DEV.to"

For the first 60-90 minutes after posting:

- reply quickly to real comments
- leave 5-10 thoughtful comments on relevant posts before or after publishing
- avoid engagement pods and bait

LinkedIn appears to reward dwell time, comments, saves, and useful discussion more than raw likes.

## Schedule

The default campaign cadence is:

| Post | Time |
| --- | --- |
| Launch | next Wednesday, 16:00 Europe/Dublin |
| Follow-up | following Friday, 15:30 Europe/Dublin |
| Lesson | following Tuesday, 11:30 Europe/Dublin |

This matches the recommendation derived from Buffer history plus recent LinkedIn timing benchmarks: Wednesday afternoon for the launch, Friday afternoon for the native follow-up, and Tuesday late morning for the reusable lesson or checklist.

## Campaign Shape

The launch post is the direct article post. It should lead with the strongest human problem or technical lesson and include the DEV.to link near the end. Keep it concise. The goal is to make the point clearly, not compress the whole article into LinkedIn.

The follow-up post goes out two days later. It should repackage the strongest idea from the article as native LinkedIn content, such as a short story, before/after comparison, "what surprised me" post, mistake post, carousel, or diagram. It should not feel like a second link post.

The lesson post goes out the following Tuesday. It should extract a reusable principle or checklist from the article, with a lighter article reference or CTA.

## Setup

Install dependencies:

```bash
uv sync
```

Export the Buffer access value and LinkedIn channel id in your shell or secret manager. The variable names are defined in `src/content_automation/config.py`.

List channels:

```bash
uv run content-automation buffer channels
```

## Build a Campaign Plan

This is the default, safe mode. It prints the three posts and schedule. It does not call Buffer.

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

1. Launch post: problem-first native post with direct article link.
2. Follow-up post: native LinkedIn explanation of the strongest idea.
3. Lesson post: reusable principle or checklist extracted from the article.

Approve, edit, or delete the drafts in Buffer before they publish.

## Link Placement

By default, the article URL is included in the post body. That is deliberate: for article promotion, a visible link is better than a hidden first-comment link.

If your Buffer plan supports LinkedIn first comments, pass:

```bash
--first-comment
```

## Notes

- Hashtags are capped at four by the current implementation.
- Generated posts are capped at 1300 characters.
- The command uses Buffer's current GraphQL API through the local Python client module. Buffer's current public docs include Python `requests` examples, but no maintained official Python SDK was found. The old `bufferapp/buffer-python` client targets the deprecated v1 REST API and Python 2-era dependencies.
- No LinkedIn browser automation is used.
- DEV.to publishing is intentionally out of scope. Keep that in the articles repo; this tool starts from a published article URL and builds the LinkedIn Buffer campaign around it.
