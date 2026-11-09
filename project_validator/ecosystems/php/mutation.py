"""PHP's mutation testing tool: Infection, configured in `infection.json5` (or `infection.json`)."""

from project_validator.ecosystems.php import PHP_ONLY
from project_validator.facts.mutation import incremental_when, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by

INFECTION_SETTINGS = file_reader(
    "Infection",
    ("infection.json5", "infection.json", "infection.json5.dist", "infection.json.dist"),
)

INFECTION = mutation_tool(
    name="Infection",
    languages=PHP_ONLY,
    how="vendor/bin/infection",
    # `vendor/bin/infection` matches by basename. `--git-diff-filter` and `--git-diff-lines` mutate the changes only.
    runs=incremental_when("infection", options=("--git-diff-filter", "--git-diff-lines")),
    defined=defined_by(files=(INFECTION_SETTINGS.name,)),
    incremental_how="vendor/bin/infection --git-diff-lines",
)
