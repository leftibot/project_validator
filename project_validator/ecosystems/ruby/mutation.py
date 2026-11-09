"""Ruby's mutation testing tool: mutant, configured in `.mutant.yml`."""

from project_validator.ecosystems.ruby import RUBY_ONLY
from project_validator.facts.mutation import incremental_when, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by

MUTANT_SETTINGS = file_reader("mutant", (".mutant.yml", "mutant.yml", "config/mutant.yml"))

MUTANT = mutation_tool(
    name="mutant",
    languages=RUBY_ONLY,
    how="mutant run",
    # `bundle exec mutant run` is expanded to `mutant run` by the profile's launcher.
    runs=incremental_when("mutant", "run", options=("--since",)),
    defined=defined_by(files=(MUTANT_SETTINGS.name,)),
    incremental_how="mutant run --since <branch>",
)
