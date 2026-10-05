# Writing pipeline output into the Sheet

A brief for whoever builds `src/sync_sheet.py`. That script does not exist yet.

## The gap

The extraction pipeline ends at `data/volunteers.json` on the machine that ran
it. The site reads only the Google Sheet. Nothing connects the two: the Sheet's
current rows were produced once by a throwaway script and imported by hand. So
a newly extracted person, or a re-extraction, never reaches the site.

The script to write: read `data/volunteers.json`, write the three tooling tabs
of the Sheet, and add a `People` row for anyone new.

Read `README.md` first for the Sheet's tabs and the pipeline stages.
`web/js/data.js` (`shapePeople`) is the reader the output must satisfy.

## Input: `data/volunteers.json`

Written only by `src/aggregate.py`. Shape:

```
{ "models": [<model name>, ...],
  "volunteers": [ {
      "id", "url", "section", "source_type",
      "extractions": { <model name>: {
          "name", "headline", "summary", "location", "seniority", "years_experience",
          "categories": [ {"category", "level", "evidence"} ],
          "skills": [str], "tools": [str], "roles": [str], "education": [str],
          "is_personal_profile", "data_quality"        # good | sparse | not_a_profile
      } },
      # only for people with a curated gdrive doc:
      "name", "gdrive_headings": [str], "gdrive_summary",
      # only when an OpenAlex author matched with high confidence:
      "publications": { "openalex_url", "orcid", "works_count",
                        "works": [ {"title", "venue", "year", "doi", "citations"} ] }
  } ] }
```

Any field may be `null`. `category` is a key from `src/taxonomy.py`; `level` is
`familiar`, `proficient` or `expert`.

## Output: the Sheet

Header names are the contract. The site looks columns up by header text, so
column order does not matter but spelling does. Row 1 is the header on every
tab.

**`Profiles`**, one row per `id`:

| Column | Source |
|---|---|
| `id` | `id` |
| `model` | name of the extraction chosen (see "Choosing the extraction") |
| `data_quality`, `headline`, `summary`, `location`, `seniority`, `years_experience` | the chosen extraction |
| `skills`, `tools`, `roles`, `education` | the chosen extraction's lists, joined with `"; "` |
| `themes` | `gdrive_headings`, joined with `"; "` |
| `openalex_url`, `orcid`, `works_count` | `publications`, blank when there is none |

**`Categories`**, one row per person per category: `id, category, level,
evidence`, from the chosen extraction, in the extraction's order.

**`Publications`**, one row per work: `id, title, venue, year, doi, citations`,
from `publications.works`.

**`People`**: `id, name, email, status, group, source_url, source_type, notes`.
This tab belongs to humans. The script may only **append** a row for an `id`
that is not there yet:

- `name`: the top-level `name` if present, else the first extraction name that
  is not empty or `"Unknown"`, else the `id`
- `status`: `applied`
- `group`: `section`; `source_url`: `url`; `source_type`: `source_type`
- `email`, `notes`: blank

### Choosing the extraction

Each person has one extraction per model. Use `qwen/qwen3-30b-a3b-2507` if it
exists and its `data_quality` is not `not_a_profile`, else `google/gemma-4-31b`
under the same test, else whichever exists. Define that order once in the
script as a constant; nothing else in the repo holds it any more.

### List cells

The site splits list cells on `;`. No item in today's data contains one, but
replace any `;` inside an item with `,` before joining, or the item will split
in two.

## Rules

1. **Never modify or delete an existing `People` row.** No rewriting names,
   statuses, emails or notes, and no reordering. People edit that tab by hand
   and may have sorted or filtered it.
2. **Upsert by `id`, and only for ids in the local `data/volunteers.json`.**
   A collaborator may have extracted only a few new resumes, so their local
   data holds only those people. Rows for every other `id` must be left
   exactly as they are. Do not clear a tab and rewrite it.
   - `Profiles`: replace the row whose `id` matches, else append.
   - `Categories` and `Publications`: remove all rows for that `id`, then add
     the new ones.
3. **Find rows by reading the `id` column at run time**, never by remembered
   row numbers.
4. **Write values as raw text** (`valueInputOption=RAW`). The default,
   `USER_ENTERED`, parses input the way the Sheets UI does and will turn some
   strings into dates or numbers.
5. **Re-running with unchanged data must change nothing.**
6. **Give it a dry run** that prints what would be added, replaced and removed
   per tab without writing, and make that the default; write only with an
   explicit flag.
7. The Sheet id is an argument or environment variable. Do not hardcode it.

## Auth

The script writes as a Google identity that has edit access to the Sheet.
Neither route below has been tried in this project.

- **The user's own login.** `gcloud auth application-default login` with the
  `https://www.googleapis.com/auth/spreadsheets` scope added, then call the
  Sheets REST API with that token. This fits the project's pattern of acting as
  the signed-in person, and needs no shared secret. Google may refuse that scope
  for gcloud's built-in client; if it does, use the project's own OAuth client.
- **A service account** with the Sheet shared to its address. Simpler to run
  unattended, but it is a credential that must be kept out of git.

Either way no key, token or client secret goes in the repository.

## Style

Match the rest of `src/`: one file, plain functions, standard library where it
is enough (`urllib` can call the Sheets REST API; the other pipeline scripts
use it for OpenAlex), and loud failures rather than silent fallbacks. Assert
that each tab's header row contains the columns the script writes, and stop if
it does not.

## Checking it

- Dry run against the real Sheet with the full local dataset: it should report
  no changes to `Categories` and `Publications` and none to `People`, since the
  Sheet was imported from the same data. `Profiles` may show differences only
  if the data was re-extracted since.
- Then change one extraction locally, run for real, and confirm on the site
  that only that person's card changed.
- Confirm a second run reports nothing to do.
- Sheets keeps version history (File > Version history), which is the way back
  from a bad run.

## Not part of this

- The raw resume text (`data/raw/`) and the gdrive prose summary
  (`gdrive_summary`) are not in the Sheet and the site does not use them.
- Embeddings and the map are computed in the browser from the Sheet; there is
  nothing to upload for them.
- Signups and their links live in the storage bucket and are managed from the
  site.
