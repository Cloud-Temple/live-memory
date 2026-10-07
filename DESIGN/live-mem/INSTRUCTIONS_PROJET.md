# Live Memory project context

Live Memory provides shared working notes and a consolidated Memory Bank for
collaborative agents. The current implementation uses S3; see
[architecture](ARCHITECTURE.md), [S3 data model](S3_DATA_MODEL.md) and
[authentication and collaboration](AUTH_AND_COLLABORATION.md).

[Mission #836](https://github.com/Cloud-Temple/mcp-mission/issues/836) restores
the repository's working prerequisites: canonical rules, the exact existing
working-memory attachment and a demonstrated session bootstrap. Its scope
does not change application storage, permissions or server configuration.
The registered working-memory space is `live-mem` on `my-live-memory`, owned
by Christophe Lesur. No durable Graph Memory index identifier is established
for this repository's working context; the optional index is explicitly
disabled in the repository configuration. This does not disconnect the
application's Graph Bridge.

[Mission EPIC #824](https://github.com/Cloud-Temple/mcp-mission/issues/824)
defines the PostgreSQL qualification work. This current owner decision differs
from the historical Memory Bank project brief, which excludes relational
databases and describes S3-only storage. The existing architecture remains the
implemented reference until the corresponding lots are qualified and integrated;
the Memory Bank must not be treated as evidence that PostgreSQL is already
delivered. The future owner lots are currently tracked by
[Mission #837](https://github.com/Cloud-Temple/mcp-mission/issues/837) and
[Mission #838](https://github.com/Cloud-Temple/mcp-mission/issues/838).
Their transfer, dependency checks and the final closure evidence for #836 are
coordinated in Mission. No business PostgreSQL implementation belongs to #836.

The existing owner tracker is [Live Memory Project #15](https://github.com/orgs/Cloud-Temple/projects/15).
Its Status, Lot, Risk, Priority and Item Type fields keep their existing options.
The open lockfile, Graph Push guard and token pagination PRs are separate work;
their existence does not establish integration into `main`.

The public language is English, with French README and integration-guide
variants. `RULES/` and `WORKSPACE_*` contain reusable consumer templates;
the repository's own canonical rules and values are reached through
[AGENTS.md](../../AGENTS.md) and [project.config.yml](../../AGENTIC_RULES/project.config.yml).
