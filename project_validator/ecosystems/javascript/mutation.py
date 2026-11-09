"""JavaScript's mutation testing tool: StrykerJS, configured in `stryker.config.*`."""

from project_validator.ecosystems.javascript import JS_LANGUAGES
from project_validator.facts.mutation import incremental_when, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by

STRYKER_SETTINGS = file_reader(
    "StrykerJS",
    (
        "stryker.config.json",
        "stryker.config.js",
        "stryker.config.mjs",
        "stryker.config.cjs",
        "stryker.conf.json",
        "stryker.conf.js",
    ),
)

STRYKER_JS = mutation_tool(
    name="StrykerJS",
    languages=JS_LANGUAGES,
    how="stryker run",
    # `npx stryker run`, and a package script running it, are expanded to `stryker run` by the profile.
    runs=incremental_when("stryker", "run", options=("--incremental",)),
    defined=defined_by(files=(STRYKER_SETTINGS.name,)),
    incremental_how="stryker run --incremental",
)
