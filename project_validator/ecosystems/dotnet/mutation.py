"""The .NET mutation testing tool: Stryker.NET (`dotnet stryker`), configured in `stryker-config.json`."""

from project_validator.ecosystems.dotnet import DOTNET_LANGUAGES
from project_validator.facts.mutation import incremental_when, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by

STRYKER_NET_SETTINGS = file_reader("Stryker.NET", ("stryker-config.json",))

STRYKER_NET = mutation_tool(
    name="Stryker.NET",
    languages=DOTNET_LANGUAGES,
    how="dotnet stryker",
    runs=incremental_when("dotnet", "stryker", options=("--since",)),
    defined=defined_by(files=(STRYKER_NET_SETTINGS.name,)),
    incremental_how="dotnet stryker --since",
)
